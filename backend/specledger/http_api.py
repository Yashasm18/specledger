"""FastAPI adapter for the SpecLedger application service."""

from __future__ import annotations

import os
import tempfile
import hashlib
from uuid import uuid4
from typing import Any

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .api import SpecLedgerService
from .batch import BatchImportService, BatchJobRepository
from .models import AttributeValue, Evidence, Product, ProductVersion, ValueStatus
from .repository import ProductRepository
from .postgres_repository import PostgresRepository
from .postgres_jobs import PostgresJobRepository
from .object_store import LocalObjectStore
from .tasks import TaskQueue
from .extraction import validate_facts, ExtractedFact
from .catalogue_api import router as catalogue_router


DATABASE_PATH = os.getenv("SPECLEDGER_DATABASE", "specledger.db")
DATABASE_URL = os.getenv("DATABASE_URL")
DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173,http://localhost:5174,http://localhost:3000,"
    "http://127.0.0.1:5173,http://127.0.0.1:5174,http://127.0.0.1:3000,"
    "https://specledger-app.vercel.app"
)
cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",") if origin.strip()]
repository = PostgresRepository(DATABASE_URL) if DATABASE_URL else ProductRepository(DATABASE_PATH)
service = SpecLedgerService(repository)
# Local development uses a separate job database to avoid SQLite's single-file
# writer lock. Production uses PostgreSQL for both stores.
job_repository = PostgresJobRepository(DATABASE_URL) if DATABASE_URL else BatchJobRepository(f"{DATABASE_PATH}.jobs")
task_queue = TaskQueue(DATABASE_URL) if DATABASE_URL else None
artifact_store = LocalObjectStore(os.getenv("SPECLEDGER_OBJECT_STORE", "object-data"))
batch_service = BatchImportService(repository, job_repository)


@asynccontextmanager
async def lifespan(application: FastAPI):
    yield
    if hasattr(repository, "close"):
        repository.close()
    job_repository.close()
    if task_queue:
        task_queue.close()


app = FastAPI(title="SpecLedger API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(catalogue_router)


class EvidenceInput(BaseModel):
    source_name: str
    source_type: str
    page: int | None = Field(default=None, ge=1)
    locator: str | None = None
    excerpt: str | None = None


class AttributeInput(BaseModel):
    name: str
    value: Any
    unit: str | None = None
    evidence: list[EvidenceInput] = Field(min_length=1)
    status: ValueStatus = ValueStatus.VERIFIED
    confidence: float | None = Field(default=None, ge=0, le=1)


class VersionInput(BaseModel):
    version_id: str
    attributes: list[AttributeInput]


class ProductInput(BaseModel):
    product_id: str
    sku: str
    name: str
    category: str
    versions: list[VersionInput] = Field(min_length=1)


class BatchImportInput(BaseModel):
    organization_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    products: list[ProductInput] = Field(min_length=1, max_length=10000)


class ArtifactReviewInput(BaseModel):
    review_state: str = Field(pattern="^(pending_review|approved|rejected)$")
    actor_id: str = Field(min_length=1, max_length=200)
    comment: str | None = Field(default=None, max_length=2000)


def to_domain_product(payload: ProductInput) -> Product:
    versions = tuple(
        ProductVersion(
            version_id=version.version_id,
            product_id=payload.product_id,
            attributes=tuple(
                AttributeValue(
                    name=attribute.name,
                    value=attribute.value,
                    unit=attribute.unit,
                    evidence=tuple(Evidence(**source.model_dump()) for source in attribute.evidence),
                    status=attribute.status,
                    confidence=attribute.confidence,
                )
                for attribute in version.attributes
            ),
        )
        for version in payload.versions
    )
    return Product(payload.product_id, payload.sku, payload.name, payload.category, versions)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "specledger"}


@app.post("/products")
def create_product(payload: ProductInput) -> dict[str, Any]:
    try:
        product = to_domain_product(payload)
        return service.create_or_update_product(product)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/products/{product_id}")
def get_product(product_id: str) -> dict[str, Any]:
    product = service.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product.to_dict()


@app.get("/products/{product_id}/validation")
def validate_product(product_id: str) -> dict[str, Any]:
    try:
        issues = service.validate_latest(product_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"product_id": product_id, "issues": issues, "issue_count": len(issues)}


@app.get("/products/{product_id}/changes")
def compare_product_versions(product_id: str) -> dict[str, Any]:
    try:
        changes = service.compare_latest_versions(product_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"product_id": product_id, "changes": changes, "change_count": len(changes)}


@app.post("/imports")
def run_import(payload: BatchImportInput) -> dict[str, Any]:
    try:
        products = [to_domain_product(product) for product in payload.products]
        result = batch_service.run(payload.job_id, payload.organization_id, products)
        return {"job_id": result.job_id, "state": result.state.value, "progress": result.progress,
                "total_items": result.total_items, "completed_items": result.completed_items,
                "failed_items": result.failed_items, "review_items": result.review_items}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/imports/{job_id}")
def get_import(job_id: str, organization_id: str = Query(default="default", min_length=1)) -> dict[str, Any]:
    result = job_repository.get_job(job_id, organization_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Import job not found")
    return {"job_id": result.job_id, "organization_id": result.organization_id, "state": result.state.value,
            "progress": result.progress, "total_items": result.total_items,
            "completed_items": result.completed_items, "failed_items": result.failed_items,
            "review_items": result.review_items}


@app.post("/documents/extract")
async def extract_document(file: UploadFile = File(...)) -> dict[str, Any]:
    """Extract text with page evidence; semantic attribute extraction comes later."""
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Only PDF files are supported in this milestone")

    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="PDF extraction dependency is not installed") from exc

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded PDF is empty")
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PDF must be 5 MB or smaller")

    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporary_file:
            temporary_file.write(contents)
            temporary_path = temporary_file.name
        document = fitz.open(temporary_path)
        pages = [
            {
                "page": index + 1,
                "text": page.get_text("text").strip(),
                "source_name": file.filename or "uploaded.pdf",
                "source_type": "pdf",
            }
            for index, page in enumerate(document)
        ]
        document.close()
    finally:
        if temporary_path:
            os.unlink(temporary_path)

    return {"filename": file.filename, "page_count": len(pages), "pages": pages}


@app.post("/documents/intake")
async def intake_document(file: UploadFile = File(...), organization_id: str = Query(default="default", min_length=1),
                          category: str = Query(default="generic", min_length=1)) -> dict[str, Any]:
    """Persist a source document and enqueue durable worker extraction."""
    if task_queue is None:
        raise HTTPException(status_code=503, detail="Durable intake requires PostgreSQL")
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Only PDF files are supported")
    contents = await file.read()
    if not contents or len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PDF must be between 1 byte and 5 MB")
    content_hash = hashlib.sha256(contents).hexdigest()
    existing = task_queue.find_document_by_hash(organization_id, content_hash)
    if existing:
        return {"document_id": existing["document_id"], "task_id": None, "state": "already_registered",
                "filename": existing["filename"], "category": existing["category"]}
    document_id = str(uuid4())
    object_key = document_id
    artifact_store.put(object_key, contents)
    task_queue.register_document(organization_id, document_id, file.filename or "uploaded.pdf",
                                 "application/pdf", object_key, content_hash, len(contents), category)
    task = task_queue.enqueue(organization_id, "pdf_extract", document_id)
    return {"document_id": document_id, "task_id": task.task_id, "state": task.state,
            "filename": file.filename, "category": category}


@app.get("/documents/tasks/{task_id}")
def document_task_status(task_id: str, organization_id: str = Query(default="default", min_length=1)) -> dict[str, Any]:
    if task_queue is None:
        raise HTTPException(status_code=503, detail="Task status requires PostgreSQL")
    task = task_queue.get(organization_id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Processing task not found")
    payload = {"task_id": task.task_id, "document_id": task.document_id, "state": task.state,
               "attempts": task.attempts, "error_message": task.error_message}
    if task.state == "completed" and task.document_id:
        artifact = task_queue.latest_artifact(organization_id, task.document_id)
        if artifact:
            if artifact_store.exists(artifact["object_key"]):
                import json
                artifact["data"] = json.loads(artifact_store.get(artifact["object_key"]))
            payload["artifact"] = artifact
    return payload

@app.get("/documents/{document_id}/artifact")
def get_latest_artifact(document_id: str, organization_id: str = Query(default="default", min_length=1)) -> dict[str, Any]:
    if task_queue is None:
        raise HTTPException(status_code=503, detail="Durable document artifacts require PostgreSQL")
    artifact = task_queue.latest_artifact(organization_id, document_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="No extraction artifact found")
    if not artifact_store.exists(artifact["object_key"]):
        raise HTTPException(status_code=409, detail="Artifact metadata exists but its object is unavailable")
    import json
    artifact["data"] = json.loads(artifact_store.get(artifact["object_key"]))
    facts = [ExtractedFact(**fact) for fact in artifact["data"].get("facts", [])]
    artifact["validation"] = {"issues": validate_facts(facts)}
    return artifact


@app.get("/documents/latest/artifact")
def get_latest_any_artifact(organization_id: str = Query(default="default", min_length=1)) -> dict[str, Any]:
    if task_queue is None:
        raise HTTPException(status_code=503, detail="Durable artifacts require PostgreSQL")
    artifact = task_queue.latest_any_artifact(organization_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="No extraction artifact found")
    if artifact_store.exists(artifact["object_key"]):
        import json
        artifact["data"] = json.loads(artifact_store.get(artifact["object_key"]))
    return artifact


@app.patch("/documents/{document_id}/artifact/{artifact_id}/review")
def review_artifact(document_id: str, artifact_id: str, payload: ArtifactReviewInput,
                    organization_id: str = Query(default="default", min_length=1)) -> dict[str, str]:
    if task_queue is None:
        raise HTTPException(status_code=503, detail="Artifact review requires PostgreSQL")
    try:
        task_queue.set_artifact_review_state(organization_id, artifact_id, payload.review_state,
                                             payload.actor_id, payload.comment)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc
    return {"document_id": document_id, "artifact_id": artifact_id, "review_state": payload.review_state}


@app.get("/documents/{document_id}/artifact/{artifact_id}/audit")
def artifact_audit(document_id: str, artifact_id: str,
                   organization_id: str = Query(default="default", min_length=1)) -> dict[str, Any]:
    if task_queue is None:
        raise HTTPException(status_code=503, detail="Artifact audit requires PostgreSQL")
    return {"document_id": document_id, "artifact_id": artifact_id,
            "events": task_queue.artifact_audit(organization_id, artifact_id)}
