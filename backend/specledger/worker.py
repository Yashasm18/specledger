"""Document-processing worker for PostgreSQL-backed tasks."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from .object_store import LocalObjectStore
from .tasks import ProcessingTask, TaskQueue


@dataclass(frozen=True)
class ExtractedPage:
    page: int
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    document_id: str
    pages: tuple[ExtractedPage, ...]

    def to_dict(self) -> dict:
        return {"document_id": self.document_id, "pages": [asdict(page) for page in self.pages]}


class DocumentProcessingWorker:
    def __init__(self, queue: TaskQueue, object_store: LocalObjectStore, worker_id: str | None = None) -> None:
        self.queue = queue
        self.object_store = object_store
        self.worker_id = worker_id or f"worker-{uuid4().hex}"

    def run_once(self, organization_id: str | None = None) -> ExtractedDocument | None:
        task = self.queue.claim(self.worker_id, "pdf_extract", organization_id)
        if task is None:
            return None
        try:
            result = self._extract(task)
            artifact_key = f"artifacts/{task.organization_id}/{task.document_id}/{uuid4().hex}.json"
            self.object_store.put_json(artifact_key, result.to_dict() | {"schema_version": "extraction.v1"})
            self.queue.record_artifact(task.organization_id, task.document_id, artifact_key,
                                       fact_count=sum(bool(page.text) for page in result.pages))
            self.queue.complete(task.organization_id, task.task_id)
            return result
        except Exception as exc:
            self.queue.fail(task.organization_id, task.task_id, str(exc))
            raise

    def _extract(self, task: ProcessingTask) -> ExtractedDocument:
        if not task.document_id:
            raise ValueError("PDF extraction task has no document_id")
        content = self.object_store.get(task.document_id)
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("PyMuPDF is required for PDF worker tasks") from exc

        temporary_path = Path(self.object_store.root) / f".worker-{uuid4().hex}.pdf"
        temporary_path.write_bytes(content)
        try:
            document = fitz.open(str(temporary_path))
            pages = tuple(ExtractedPage(index + 1, page.get_text("text").strip()) for index, page in enumerate(document))
            document.close()
        finally:
            temporary_path.unlink(missing_ok=True)
        return ExtractedDocument(task.document_id, pages)
