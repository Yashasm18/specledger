"""Persistence store for catalogue batches, rows, and evaluation runs.

Supports both PostgreSQL (for production / migration 007 schema)
and an in-memory store (for testing and local dev).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class PersistedBatch:
    batch_id: str
    organization_id: str
    source_name: str
    source_fingerprint: str
    column_list: list[str]
    row_count: int
    verified_rate: float
    rows: list[dict[str, Any]]
    ingested_at: str | None = None


class CatalogueStore:
    """Abstract interface for catalogue batch and row persistence."""

    def save_batch(self, batch_data: dict[str, Any]) -> str:
        raise NotImplementedError

    def get_batch(self, organization_id: str, batch_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def get_batch_row(self, organization_id: str, batch_id: str, row_number: int) -> dict[str, Any] | None:
        raise NotImplementedError

    def list_batches(self, organization_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def update_row_review_state(
        self, organization_id: str, batch_id: str, row_number: int,
        review_state: str, reviewed_by: str | None = None,
        corrections: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        raise NotImplementedError


class InMemoryCatalogueStore(CatalogueStore):
    """In-memory catalogue store for testing and fallback."""

    def __init__(self) -> None:
        # (org_id, batch_id) -> batch_dict
        self._batches: dict[tuple[str, str], dict[str, Any]] = {}

    def save_batch(self, batch_data: dict[str, Any]) -> str:
        org_id = batch_data.get("organization_id", "default")
        batch_id = batch_data["batch_id"]
        # PostgresCatalogueStore derives raw_values/enriched_values from the
        # row's "fields" array on write and returns them on read. Readers
        # (e.g. the review-queue rebuild) rely on that shape, so derive them
        # here too rather than storing the input dict verbatim — otherwise
        # the same code path works against Postgres and KeyErrors locally.
        for row in batch_data.get("rows", []):
            fields = row.get("fields", [])
            row.setdefault("raw_values", {f["column"]: f["raw_value"] for f in fields})
            row.setdefault(
                "enriched_values", {f["column"]: f["canonical_value"] for f in fields}
            )
            row.setdefault("review_state", None)
        self._batches[(org_id, batch_id)] = batch_data
        return batch_id

    def get_batch(self, organization_id: str, batch_id: str) -> dict[str, Any] | None:
        return self._batches.get((organization_id, batch_id))

    def get_batch_row(self, organization_id: str, batch_id: str, row_number: int) -> dict[str, Any] | None:
        batch = self.get_batch(organization_id, batch_id)
        if not batch:
            return None
        for row in batch.get("rows", []):
            if row.get("row_number") == row_number:
                return row
        return None

    def list_batches(self, organization_id: str) -> list[dict[str, Any]]:
        # Postgres orders by ingested_at DESC on write; match that here too
        # (most-recently-ingested first) — dict insertion order alone would
        # put the oldest batch first, which is the opposite of "latest".
        return [
            {
                "batch_id": b["batch_id"],
                "source_name": b["source_name"],
                "row_count": b["row_count"],
                "verified_rate": b["verified_rate"],
            }
            for (org_id, _), b in reversed(list(self._batches.items()))
            if org_id == organization_id
        ]

    def update_row_review_state(
        self, organization_id: str, batch_id: str, row_number: int,
        review_state: str, reviewed_by: str | None = None,
        corrections: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        batch = self.get_batch(organization_id, batch_id)
        if not batch:
            return None
        for row in batch.get("rows", []):
            if row.get("row_number") == row_number:
                row["review_state"] = review_state
                row["reviewed_by"] = reviewed_by
                if corrections:
                    row["corrections"] = corrections
                return row
        return None


class PostgresCatalogueStore(CatalogueStore):
    """PostgreSQL catalogue store using psycopg (v3) and migration 007 schema."""

    def __init__(self, connection_url: str) -> None:
        self.connection_url = connection_url

    def _get_connection(self) -> Any:
        import psycopg
        return psycopg.connect(self.connection_url)

    def save_batch(self, batch_data: dict[str, Any]) -> str:
        org_id = batch_data.get("organization_id", "default")
        batch_id = batch_data["batch_id"]

        conn = self._get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    # Ensure org exists
                    cur.execute(
                        "INSERT INTO organizations (organization_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (org_id, org_id.capitalize()),
                    )
                    # Insert batch
                    cur.execute(
                        """
                        INSERT INTO catalogue_batches
                            (organization_id, batch_id, source_name, source_fingerprint, column_list, row_count, verified_rate)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (organization_id, batch_id) DO UPDATE SET
                            verified_rate = EXCLUDED.verified_rate,
                            row_count = EXCLUDED.row_count
                        """,
                        (
                            org_id,
                            batch_id,
                            batch_data["source_name"],
                            batch_data.get("source_fingerprint", batch_id),
                            json.dumps(batch_data.get("columns", [])),
                            batch_data["row_count"],
                            batch_data.get("verified_rate", 0.0),
                        ),
                    )

                    # Insert rows
                    for row in batch_data.get("rows", []):
                        raw_values = {f["column"]: f["raw_value"] for f in row.get("fields", [])}
                        enriched_values = {f["column"]: f["canonical_value"] for f in row.get("fields", [])}
                        cur.execute(
                            """
                            INSERT INTO catalogue_rows
                                (organization_id, batch_id, row_number, source_fingerprint, raw_values, enriched_values, overall_status, overall_confidence, review_state)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (organization_id, batch_id, row_number) DO UPDATE SET
                                enriched_values = EXCLUDED.enriched_values,
                                overall_status = EXCLUDED.overall_status,
                                overall_confidence = EXCLUDED.overall_confidence,
                                review_state = EXCLUDED.review_state
                            """,
                            (
                                org_id,
                                batch_id,
                                row["row_number"],
                                row.get("source_fingerprint", f"{batch_id}-{row['row_number']}"),
                                json.dumps(raw_values),
                                json.dumps(enriched_values),
                                row.get("overall_status", "review_required"),
                                row.get("overall_confidence", 0.0),
                                row.get("review_state", "pending_review"),
                            ),
                        )
            return batch_id
        finally:
            conn.close()

    def get_batch(self, organization_id: str, batch_id: str) -> dict[str, Any] | None:
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT batch_id, source_name, column_list, row_count, verified_rate, ingested_at
                    FROM catalogue_batches
                    WHERE organization_id = %s AND batch_id = %s
                    """,
                    (organization_id, batch_id),
                )
                batch_row = cur.fetchone()
                if not batch_row:
                    return None

                cur.execute(
                    """
                    SELECT row_number, source_fingerprint, raw_values, enriched_values, overall_status, overall_confidence, review_state, reviewed_by, reviewed_at
                    FROM catalogue_rows
                    WHERE organization_id = %s AND batch_id = %s
                    ORDER BY row_number
                    """,
                    (organization_id, batch_id),
                )
                rows = cur.fetchall()

                return {
                    "batch_id": batch_row[0],
                    "organization_id": organization_id,
                    "source_name": batch_row[1],
                    "columns": batch_row[2] if isinstance(batch_row[2], list) else json.loads(batch_row[2]),
                    "row_count": batch_row[3],
                    "verified_rate": batch_row[4],
                    "ingested_at": str(batch_row[5]),
                    "rows": [
                        {
                            "row_number": r[0],
                            "source_fingerprint": r[1],
                            "raw_values": r[2] if isinstance(r[2], dict) else json.loads(r[2]),
                            "enriched_values": r[3] if isinstance(r[3], dict) else json.loads(r[3]),
                            "overall_status": r[4],
                            "overall_confidence": r[5],
                            "review_state": r[6],
                            "reviewed_by": r[7],
                            "reviewed_at": str(r[8]) if r[8] else None,
                        }
                        for r in rows
                    ],
                }
        finally:
            conn.close()

    def get_batch_row(self, organization_id: str, batch_id: str, row_number: int) -> dict[str, Any] | None:
        batch = self.get_batch(organization_id, batch_id)
        if not batch:
            return None
        for row in batch.get("rows", []):
            if row.get("row_number") == row_number:
                return row
        return None

    def list_batches(self, organization_id: str) -> list[dict[str, Any]]:
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT batch_id, source_name, row_count, verified_rate
                    FROM catalogue_batches
                    WHERE organization_id = %s
                    ORDER BY ingested_at DESC
                    """,
                    (organization_id,),
                )
                rows = cur.fetchall()
                return [
                    {
                        "batch_id": r[0],
                        "source_name": r[1],
                        "row_count": r[2],
                        "verified_rate": r[3],
                    }
                    for r in rows
                ]
        finally:
            conn.close()

    def update_row_review_state(
        self, organization_id: str, batch_id: str, row_number: int,
        review_state: str, reviewed_by: str | None = None,
        corrections: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        conn = self._get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE catalogue_rows
                        SET review_state = %s, reviewed_by = %s, reviewed_at = NOW()
                        WHERE organization_id = %s AND batch_id = %s AND row_number = %s
                        RETURNING row_number, review_state, reviewed_by
                        """,
                        (review_state, reviewed_by, organization_id, batch_id, row_number),
                    )
                    res = cur.fetchone()
                    if res:
                        return {
                            "row_number": res[0],
                            "review_state": res[1],
                            "reviewed_by": res[2],
                            "corrections": corrections,
                        }
                    return None
        finally:
            conn.close()
