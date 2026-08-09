"""PostgreSQL adapter for production deployments.

The local SQLite repository remains useful for development. This adapter keeps
the same domain boundary while using PostgreSQL JSONB, constraints, indexes,
and a connection pool in production.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Iterator

from .models import AttributeValue, Evidence, Product, ProductVersion, ValueStatus


POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS organizations (
    organization_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS products (
    organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
    product_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, product_id),
    UNIQUE (organization_id, sku)
);

CREATE TABLE IF NOT EXISTS product_versions (
    organization_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (organization_id, version_id),
    FOREIGN KEY (organization_id, product_id)
        REFERENCES products(organization_id, product_id)
);

CREATE TABLE IF NOT EXISTS attributes (
    organization_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    name TEXT NOT NULL,
    value JSONB NOT NULL,
    unit TEXT,
    status TEXT NOT NULL,
    confidence DOUBLE PRECISION,
    PRIMARY KEY (organization_id, version_id, name),
    FOREIGN KEY (organization_id, version_id)
        REFERENCES product_versions(organization_id, version_id)
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id BIGSERIAL PRIMARY KEY,
    organization_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    attribute_name TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    page INTEGER,
    locator TEXT,
    excerpt TEXT,
    captured_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (organization_id, version_id, attribute_name)
        REFERENCES attributes(organization_id, version_id, name)
);

CREATE INDEX IF NOT EXISTS products_org_category_idx
    ON products (organization_id, category);
CREATE INDEX IF NOT EXISTS products_org_updated_idx
    ON products (organization_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS versions_org_product_idx
    ON product_versions (organization_id, product_id, created_at DESC);
"""


class PostgresRepository:
    def __init__(self, database_url: str | None = None, min_size: int = 1, max_size: int = 10) -> None:
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise RuntimeError("Install psycopg[binary] and psycopg_pool to use PostgreSQL") from exc
        self.pool = ConnectionPool(database_url or os.environ["DATABASE_URL"], min_size=min_size, max_size=max_size, open=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            yield connection

    def initialize(self) -> None:
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(POSTGRES_SCHEMA)
            connection.commit()

    def close(self) -> None:
        self.pool.close()

    def ensure_organization(self, organization_id: str, name: str | None = None) -> None:
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO organizations(organization_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (organization_id, name or organization_id),
                )
            connection.commit()

    def save_product(self, product: Product, organization_id: str = "default") -> None:
        self.ensure_organization(organization_id)
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO products(organization_id, product_id, sku, name, category)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (organization_id, product_id) DO UPDATE SET
                    sku = EXCLUDED.sku, name = EXCLUDED.name, category = EXCLUDED.category,
                    updated_at = NOW()""",
                    (organization_id, product.product_id, product.sku, product.name, product.category),
                )
                for version in product.versions:
                    cursor.execute(
                        """INSERT INTO product_versions(organization_id, version_id, product_id, created_at)
                        VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                        (organization_id, version.version_id, version.product_id, version.created_at),
                    )
                    for attribute in version.attributes:
                        cursor.execute(
                            """INSERT INTO attributes(organization_id, version_id, name, value, unit, status, confidence)
                            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
                            ON CONFLICT (organization_id, version_id, name) DO UPDATE SET
                            value = EXCLUDED.value, unit = EXCLUDED.unit, status = EXCLUDED.status,
                            confidence = EXCLUDED.confidence""",
                            (organization_id, version.version_id, attribute.name, json.dumps(attribute.value),
                             attribute.unit, attribute.status.value, attribute.confidence),
                        )
                        cursor.execute(
                            "DELETE FROM evidence WHERE organization_id = %s AND version_id = %s AND attribute_name = %s",
                            (organization_id, version.version_id, attribute.name),
                        )
                        for source in attribute.evidence:
                            cursor.execute(
                                """INSERT INTO evidence
                                (organization_id, version_id, attribute_name, source_name, source_type, page, locator, excerpt, captured_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                (organization_id, version.version_id, attribute.name, source.source_name,
                                 source.source_type, source.page, source.locator, source.excerpt, source.captured_at),
                            )
            connection.commit()

