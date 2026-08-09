"""Worker-ready PostgreSQL task queue primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from .postgres_repository import PostgresRepository


@dataclass(frozen=True)
class ProcessingTask:
    task_id: str
    organization_id: str
    task_type: str
    state: str
    attempts: int
    document_id: str | None
    error_message: str | None


class TaskQueue:
    def __init__(self, database_url: str) -> None:
        self.database = PostgresRepository(database_url)

    def close(self) -> None:
        self.database.close()

    def enqueue(self, organization_id: str, task_type: str, document_id: str | None = None) -> ProcessingTask:
        task_id = str(uuid4())
        self.database.ensure_organization(organization_id)
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO processing_tasks(organization_id, task_id, document_id, task_type)
                    VALUES (%s, %s, %s, %s)""",
                    (organization_id, task_id, document_id, task_type),
                )
            connection.commit()
        return self.get(organization_id, task_id)  # type: ignore[return-value]

    def register_document(self, organization_id: str, document_id: str, filename: str,
                          media_type: str, object_key: str, content_hash: str, size_bytes: int) -> None:
        self.database.ensure_organization(organization_id)
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO document_assets
                    (organization_id, document_id, filename, media_type, object_key, content_hash, size_bytes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (organization_id, document_id) DO UPDATE SET
                    filename = EXCLUDED.filename, object_key = EXCLUDED.object_key,
                    content_hash = EXCLUDED.content_hash, size_bytes = EXCLUDED.size_bytes""",
                    (organization_id, document_id, filename, media_type, object_key, content_hash, size_bytes),
                )
            connection.commit()

    def claim(self, worker_id: str, task_type: str | None = None, organization_id: str | None = None) -> ProcessingTask | None:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """WITH candidate AS (
                        SELECT organization_id, task_id FROM processing_tasks
                        WHERE state = 'queued' AND available_at <= NOW()
                          AND (%s::text IS NULL OR task_type = %s::text)
                          AND (%s::text IS NULL OR organization_id = %s::text)
                        ORDER BY created_at
                        FOR UPDATE SKIP LOCKED LIMIT 1
                    )
                    UPDATE processing_tasks AS task SET state = 'processing', locked_by = %s,
                        locked_at = NOW(), attempts = task.attempts + 1, updated_at = NOW()
                    FROM candidate WHERE task.organization_id = candidate.organization_id
                      AND task.task_id = candidate.task_id
                    RETURNING task.task_id, task.organization_id, task.task_type, task.state,
                              task.attempts, task.document_id, task.error_message""",
                    (task_type, task_type, organization_id, organization_id, worker_id),
                )
                row = cursor.fetchone()
            connection.commit()
        return self._task(row) if row else None

    def complete(self, organization_id: str, task_id: str) -> None:
        self._set_state(organization_id, task_id, "completed", None)

    def fail(self, organization_id: str, task_id: str, message: str) -> None:
        self._set_state(organization_id, task_id, "failed", message)

    def get(self, organization_id: str, task_id: str) -> ProcessingTask | None:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT task_id, organization_id, task_type, state, attempts, document_id, error_message
                    FROM processing_tasks WHERE organization_id = %s AND task_id = %s""",
                    (organization_id, task_id),
                )
                row = cursor.fetchone()
        return self._task(row) if row else None

    def record_artifact(self, organization_id: str, document_id: str, object_key: str,
                        fact_count: int = 0, schema_version: str = "extraction.v1") -> str:
        artifact_id = str(uuid4())
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO extraction_artifacts
                    (organization_id, artifact_id, document_id, object_key, schema_version, fact_count)
                    VALUES (%s, %s, %s, %s, %s, %s)""",
                    (organization_id, artifact_id, document_id, object_key, schema_version, fact_count),
                )
            connection.commit()
        return artifact_id

    def latest_artifact(self, organization_id: str, document_id: str) -> dict | None:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT artifact_id, document_id, object_key, schema_version, fact_count, created_at, review_state
                    FROM extraction_artifacts WHERE organization_id = %s AND document_id = %s
                    ORDER BY created_at DESC LIMIT 1""", (organization_id, document_id))
                row = cursor.fetchone()
        if not row:
            return None
        return {"artifact_id": row[0], "document_id": row[1], "object_key": row[2],
                "schema_version": row[3], "fact_count": row[4], "created_at": row[5].isoformat(),
                "review_state": row[6]}

    def set_artifact_review_state(self, organization_id: str, artifact_id: str, state: str) -> None:
        if state not in {"pending_review", "approved", "rejected"}:
            raise ValueError("Invalid artifact review state")
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""UPDATE extraction_artifacts SET review_state = %s
                    WHERE organization_id = %s AND artifact_id = %s""", (state, organization_id, artifact_id))
                if cursor.rowcount != 1:
                    raise KeyError("Artifact not found")
                cursor.execute("""INSERT INTO audit_events
                    (organization_id, entity_type, entity_id, event_type, payload)
                    VALUES (%s, 'extraction_artifact', %s, 'review_state_changed', %s::jsonb)""",
                    (organization_id, artifact_id,
                     '{"review_state": "' + state + '"}'))
            connection.commit()

    def artifact_audit(self, organization_id: str, artifact_id: str) -> list[dict]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""SELECT event_id, event_type, payload, created_at
                    FROM audit_events WHERE organization_id = %s AND entity_type = 'extraction_artifact'
                    AND entity_id = %s ORDER BY created_at""", (organization_id, artifact_id))
                rows = cursor.fetchall()
        return [{"event_id": row[0], "event_type": row[1], "payload": row[2],
                 "created_at": row[3].isoformat()} for row in rows]

    def _set_state(self, organization_id: str, task_id: str, state: str, error: str | None) -> None:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE processing_tasks SET state = %s, error_message = %s,
                    locked_by = NULL, locked_at = NULL, updated_at = NOW()
                    WHERE organization_id = %s AND task_id = %s""",
                    (state, error, organization_id, task_id),
                )
            connection.commit()

    @staticmethod
    def _task(row: tuple) -> ProcessingTask:
        return ProcessingTask(row[0], row[1], row[2], row[3], row[4], row[5], row[6])
