"""Batch-import contracts and a durable local job runner.

The runner is intentionally storage-backed and chunked. In production, the
same job states can be consumed by queue workers instead of this local runner.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Iterable

from .models import Product
from .repository import ProductRepository
from .validation import validate_version


class JobState(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class ItemState(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


@dataclass(frozen=True)
class ImportJob:
    job_id: str
    organization_id: str
    state: JobState
    total_items: int
    completed_items: int
    failed_items: int
    review_items: int

    @property
    def progress(self) -> float:
        return self.completed_items / self.total_items if self.total_items else 1.0


def product_fingerprint(product: Product) -> str:
    """Stable content hash used to make repeated imports idempotent."""
    encoded = json.dumps(product.to_dict(), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class BatchJobRepository:
    def __init__(self, database_path: str | Path = ":memory:") -> None:
        self.connection = sqlite3.connect(str(database_path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._lock = RLock()
        with self._lock:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS import_jobs (
                    job_id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    total_items INTEGER NOT NULL,
                    completed_items INTEGER NOT NULL DEFAULT 0,
                    failed_items INTEGER NOT NULL DEFAULT 0,
                    review_items INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS import_items (
                    job_id TEXT NOT NULL,
                    organization_id TEXT NOT NULL,
                    item_number INTEGER NOT NULL,
                    product_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,
                    error_message TEXT,
                    PRIMARY KEY (job_id, item_number)
                );
                """
            )
            # SQLite cannot add organization_id to the table definition above
            # after the fact in this first local adapter, so use a separate
            # uniqueness table for cross-job idempotency.
            self.connection.execute(
                """CREATE TABLE IF NOT EXISTS processed_fingerprints (
                    organization_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    PRIMARY KEY (organization_id, fingerprint)
                )"""
            )
            self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def create_job(self, job_id: str, organization_id: str, products: list[Product]) -> None:
        with self._lock:
            self.connection.execute(
                "INSERT INTO import_jobs(job_id, organization_id, state, total_items) VALUES (?, ?, ?, ?)",
                (job_id, organization_id, JobState.QUEUED.value, len(products)),
            )
            for number, product in enumerate(products, start=1):
                self.connection.execute(
                    "INSERT INTO import_items(job_id, organization_id, item_number, product_id, fingerprint, state) VALUES (?, ?, ?, ?, ?, ?)",
                    (job_id, organization_id, number, product.product_id, product_fingerprint(product), ItemState.QUEUED.value),
                )
            self.connection.commit()

    def set_job_state(self, job_id: str, state: JobState) -> None:
        with self._lock:
            self.connection.execute("UPDATE import_jobs SET state = ? WHERE job_id = ?", (state.value, job_id))
            self.connection.commit()

    def set_item_state(self, job_id: str, item_number: int, state: ItemState, error: str | None = None) -> None:
        with self._lock:
            self.connection.execute(
                "UPDATE import_items SET state = ?, error_message = ? WHERE job_id = ? AND item_number = ?",
                (state.value, error, job_id, item_number),
            )
            self.connection.commit()

    def mark_fingerprint_processed(self, organization_id: str, product: Product) -> bool:
        fingerprint = product_fingerprint(product)
        with self._lock:
            existing = self.connection.execute(
                "SELECT 1 FROM processed_fingerprints WHERE organization_id = ? AND fingerprint = ?",
                (organization_id, fingerprint),
            ).fetchone()
            if existing:
                return False
            self.connection.execute(
                "INSERT INTO processed_fingerprints(organization_id, fingerprint, product_id) VALUES (?, ?, ?)",
                (organization_id, fingerprint, product.product_id),
            )
            self.connection.commit()
            return True

    def get_job(self, job_id: str) -> ImportJob | None:
        with self._lock:
            row = self.connection.execute("SELECT * FROM import_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                return None
            return ImportJob(
                row["job_id"], row["organization_id"], JobState(row["state"]), row["total_items"],
                row["completed_items"], row["failed_items"], row["review_items"],
            )

    def refresh_counts(self, job_id: str) -> None:
        with self._lock:
            self.connection.execute(
                """UPDATE import_jobs SET
                completed_items = (SELECT COUNT(*) FROM import_items WHERE job_id = ? AND state = 'completed'),
                failed_items = (SELECT COUNT(*) FROM import_items WHERE job_id = ? AND state = 'failed'),
                review_items = (SELECT COUNT(*) FROM import_items WHERE job_id = ? AND state = 'needs_review')
                WHERE job_id = ?""",
                (job_id, job_id, job_id, job_id),
            )
            self.connection.commit()


class BatchImportService:
    def __init__(self, products: ProductRepository, jobs: BatchJobRepository, chunk_size: int = 100) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        self.products = products
        self.jobs = jobs
        self.chunk_size = chunk_size

    def run(self, job_id: str, organization_id: str, products: Iterable[Product]) -> ImportJob:
        product_list = list(products)
        self.jobs.create_job(job_id, organization_id, product_list)
        self.jobs.set_job_state(job_id, JobState.PROCESSING)
        for start in range(0, len(product_list), self.chunk_size):
            for offset, product in enumerate(product_list[start:start + self.chunk_size], start=start + 1):
                try:
                    self.jobs.set_item_state(job_id, offset, ItemState.PROCESSING)
                    if not self.jobs.mark_fingerprint_processed(organization_id, product):
                        self.jobs.set_item_state(job_id, offset, ItemState.COMPLETED)
                        continue
                    issues = validate_version(product.latest_version())
                    self.products.save_product(product)
                    state = ItemState.NEEDS_REVIEW if issues else ItemState.COMPLETED
                    self.jobs.set_item_state(job_id, offset, state)
                except Exception as exc:  # isolate one bad record from the batch
                    self.jobs.set_item_state(job_id, offset, ItemState.FAILED, str(exc))
            self.jobs.refresh_counts(job_id)

        self.jobs.refresh_counts(job_id)
        current = self.jobs.get_job(job_id)
        assert current is not None
        final_state = JobState.COMPLETED_WITH_ERRORS if current.failed_items or current.review_items else JobState.COMPLETED
        self.jobs.set_job_state(job_id, final_state)
        return self.jobs.get_job(job_id)  # type: ignore[return-value]
