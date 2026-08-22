"""Document-processing worker for PostgreSQL-backed tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import uuid4

from .object_store import LocalObjectStore
from .document_text import extract_pages
from .extraction import extract_facts, validate_facts
from .schemas import get_schema
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
            facts = extract_facts([asdict(page) for page in result.pages])
            schema = get_schema(task.category)
            self.object_store.put_json(artifact_key, result.to_dict() | {
                "schema_version": "extraction.v1",
                "catalogue_schema": {"id": schema.schema_id, "version": schema.version},
                "facts": [fact.to_dict() for fact in facts],
                "validation": {"issues": validate_facts(facts, schema.required_attributes)},
            })
            self.queue.record_artifact(task.organization_id, task.document_id, artifact_key,
                                       fact_count=len(facts))
            self.queue.complete(task.organization_id, task.task_id)
            return result
        except Exception as exc:
            self.queue.fail(task.organization_id, task.task_id, str(exc))
            raise

    def _extract(self, task: ProcessingTask) -> ExtractedDocument:
        if not task.document_id:
            raise ValueError("Extraction task has no document_id")
        content = self.object_store.get(task.document_id)

        # Read from memory, and let document_text pick the reader. This used
        # to open PDFs only, and wrote the bytes to a temporary file inside
        # object_store.root first — an attribute only the local development
        # store has, so against the deployed Supabase-backed store every
        # extraction failed and an uploaded file was accepted then never
        # processed. The content is already in hand by this point.
        #
        # A task registered before filenames were recorded carries none;
        # those are all PDFs, which was the only format that existed then.
        filename = task.filename or "document.pdf"
        pages = tuple(
            ExtractedPage(page["page"], page["text"])
            for page in extract_pages(filename, content)
        )
        return ExtractedDocument(task.document_id, pages)
