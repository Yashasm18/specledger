"""PostgreSQL-backed import job repository."""

from __future__ import annotations

from .batch import ImportJob, ItemState, JobState, product_fingerprint
from .models import Product
from .postgres_repository import PostgresRepository


class PostgresJobRepository:
    def __init__(self, database_url: str) -> None:
        self.database = PostgresRepository(database_url)

    def close(self) -> None:
        self.database.close()

    def create_job(self, job_id: str, organization_id: str, products: list[Product]) -> None:
        self.database.ensure_organization(organization_id)
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO import_jobs(organization_id, job_id, state, total_items)
                    VALUES (%s, %s, %s, %s)""",
                    (organization_id, job_id, JobState.QUEUED.value, len(products)),
                )
                for number, product in enumerate(products, start=1):
                    cursor.execute(
                        """INSERT INTO import_items
                        (organization_id, job_id, item_number, product_id, fingerprint, state)
                        VALUES (%s, %s, %s, %s, %s, %s)""",
                        (organization_id, job_id, number, product.product_id,
                         product_fingerprint(product), ItemState.QUEUED.value),
                    )
            connection.commit()

    def set_job_state(self, job_id: str, state: JobState, organization_id: str = "default") -> None:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE import_jobs SET state = %s, updated_at = NOW() WHERE organization_id = %s AND job_id = %s",
                    (state.value, organization_id, job_id),
                )
            connection.commit()

    def set_item_state(self, job_id: str, item_number: int, state: ItemState, error: str | None = None, organization_id: str = "default") -> None:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE import_items SET state = %s, error_message = %s
                    WHERE organization_id = %s AND job_id = %s AND item_number = %s""",
                    (state.value, error, organization_id, job_id, item_number),
                )
            connection.commit()

    def mark_fingerprint_processed(self, organization_id: str, product: Product) -> bool:
        fingerprint = product_fingerprint(product)
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO processed_fingerprints(organization_id, fingerprint, product_id)
                    VALUES (%s, %s, %s) ON CONFLICT DO NOTHING RETURNING fingerprint""",
                    (organization_id, fingerprint, product.product_id),
                )
                inserted = cursor.fetchone() is not None
            connection.commit()
            return inserted

    def refresh_counts(self, job_id: str, organization_id: str = "default") -> None:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE import_jobs SET
                    completed_items = (SELECT COUNT(*) FROM import_items WHERE organization_id = %s AND job_id = %s AND state = 'completed'),
                    failed_items = (SELECT COUNT(*) FROM import_items WHERE organization_id = %s AND job_id = %s AND state = 'failed'),
                    review_items = (SELECT COUNT(*) FROM import_items WHERE organization_id = %s AND job_id = %s AND state = 'needs_review'),
                    updated_at = NOW()
                    WHERE organization_id = %s AND job_id = %s""",
                    (organization_id, job_id, organization_id, job_id, organization_id, job_id, organization_id, job_id),
                )
            connection.commit()

    def get_job(self, job_id: str, organization_id: str = "default") -> ImportJob | None:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT job_id, organization_id, state, total_items, completed_items, failed_items, review_items
                    FROM import_jobs WHERE organization_id = %s AND job_id = %s""",
                    (organization_id, job_id),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return ImportJob(row[0], row[1], JobState(row[2]), row[3], row[4], row[5], row[6])

