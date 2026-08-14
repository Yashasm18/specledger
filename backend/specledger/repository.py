"""SQLite persistence for SpecLedger's evidence-backed product records."""

from __future__ import annotations

import json
import sqlite3
from threading import RLock
from pathlib import Path

from .models import AttributeValue, Evidence, Product, ProductVersion, ValueStatus


class ProductRepository:
    def __init__(self, database_path: str | Path = ":memory:") -> None:
        self.database_path = str(database_path)
        self.connection = sqlite3.connect(self.database_path, check_same_thread=False, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def _create_schema(self) -> None:
        with self._lock:
            self.connection.executescript(
                """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS products (
                product_id TEXT PRIMARY KEY,
                sku TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                category TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS product_versions (
                version_id TEXT PRIMARY KEY,
                product_id TEXT NOT NULL REFERENCES products(product_id),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS attributes (
                version_id TEXT NOT NULL REFERENCES product_versions(version_id),
                name TEXT NOT NULL,
                value_json TEXT NOT NULL,
                unit TEXT,
                status TEXT NOT NULL,
                confidence REAL,
                PRIMARY KEY (version_id, name)
            );

            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id TEXT NOT NULL,
                attribute_name TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                page INTEGER,
                locator TEXT,
                excerpt TEXT,
                captured_at TEXT NOT NULL,
                FOREIGN KEY (version_id, attribute_name)
                    REFERENCES attributes(version_id, name)
            );
                """
            )
            self.connection.commit()

    def save_product(self, product: Product) -> None:
        with self._lock:
            self.connection.execute(
                "INSERT OR REPLACE INTO products(product_id, sku, name, category) VALUES (?, ?, ?, ?)",
                (product.product_id, product.sku, product.name, product.category),
            )
            for version in product.versions:
                self.connection.execute(
                    "INSERT OR REPLACE INTO product_versions(version_id, product_id, created_at) VALUES (?, ?, ?)",
                    (version.version_id, version.product_id, version.created_at),
                )
                for attribute in version.attributes:
                    self.connection.execute(
                        """INSERT OR REPLACE INTO attributes
                        (version_id, name, value_json, unit, status, confidence)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            version.version_id,
                            attribute.name,
                            json.dumps(attribute.value),
                            attribute.unit,
                            attribute.status.value,
                            attribute.confidence,
                        ),
                    )
                    self.connection.execute(
                        "DELETE FROM evidence WHERE version_id = ? AND attribute_name = ?",
                        (version.version_id, attribute.name),
                    )
                    for source in attribute.evidence:
                        self.connection.execute(
                            """INSERT INTO evidence
                            (version_id, attribute_name, source_name, source_type, page, locator, excerpt, captured_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                version.version_id,
                                attribute.name,
                                source.source_name,
                                source.source_type,
                                source.page,
                                source.locator,
                                source.excerpt,
                                source.captured_at,
                            ),
                        )
            self.connection.commit()

    def get_product(self, product_id: str) -> Product | None:
        with self._lock:
            product_row = self.connection.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
            if product_row is None:
                return None

            version_rows = self.connection.execute(
                "SELECT * FROM product_versions WHERE product_id = ? ORDER BY created_at, version_id",
                (product_id,),
            ).fetchall()
            versions = tuple(self._read_version(row) for row in version_rows)
            return Product(product_id, product_row["sku"], product_row["name"], product_row["category"], versions)

    def _read_version(self, version_row: sqlite3.Row) -> ProductVersion:
        attribute_rows = self.connection.execute(
            "SELECT * FROM attributes WHERE version_id = ? ORDER BY name",
            (version_row["version_id"],),
        ).fetchall()
        attributes: list[AttributeValue] = []
        for row in attribute_rows:
            evidence_rows = self.connection.execute(
                "SELECT * FROM evidence WHERE version_id = ? AND attribute_name = ? ORDER BY evidence_id",
                (version_row["version_id"], row["name"]),
            ).fetchall()
            evidence = tuple(
                Evidence(
                    source_name=item["source_name"],
                    source_type=item["source_type"],
                    page=item["page"],
                    locator=item["locator"],
                    excerpt=item["excerpt"],
                    captured_at=item["captured_at"],
                )
                for item in evidence_rows
            )
            attributes.append(
                AttributeValue(
                    name=row["name"],
                    value=json.loads(row["value_json"]),
                    unit=row["unit"],
                    evidence=evidence,
                    status=ValueStatus(row["status"]),
                    confidence=row["confidence"],
                )
            )
        return ProductVersion(version_row["version_id"], version_row["product_id"], tuple(attributes), version_row["created_at"])
