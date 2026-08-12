"""FastAPI router for catalogue ingestion, enrichment, validation, review, and export.

Provides endpoints for:
  - Uploading CSV/TSV/XLSX catalogue files
  - Ingesting, enriching, and processing batches
  - Deterministic validation & review routing
  - Human review queue & actions (approve, reject, correct)
  - Source discovery & evidence tracking (manufacturer verified)
  - Batch metrics & cost tracking
  - Commerce-ready exports (CSV, JSON, Commerce CSV, Audit JSON)
  - Managing reference data (manufacturers, brands, UOM, materials)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile, Query, Response
from pydantic import BaseModel, Field

from .catalogue_ingestion import read_catalogue, CatalogueBatch, normalize_rows
from .enrichment import enrich_batch, EnrichedBatch
from .evaluator import evaluate, load_ground_truth_csv, EvaluationReport, GroundTruthRow
from .reference_data import ReferenceStore
from .uom import normalize_uom, normalize_material
from .validation_engine import validate_batch, validate_row, BatchValidationResult
from .human_review import (
    route_batch_for_review, approve_row, reject_row, correct_row,
    ReviewQueue, ReviewState, ReviewError,
)
from .source_discovery import discover_sources_simulated, is_blocked_source
from .batch_processor import process_batch, BatchProcessingResult, SourceCache
from .export import export_csv, export_json, export_commerce_csv, export_audit_json, export_unilog_template
from .catalogue_persistence import CatalogueStore, InMemoryCatalogueStore, PostgresCatalogueStore


router = APIRouter(prefix="/catalogue", tags=["catalogue"])

# Module-level reference store — loaded once, reused across requests
_reference_dir = os.getenv("SPECLEDGER_REFERENCE_DIR", "data/reference")
_reference_store = ReferenceStore(reference_dir=_reference_dir)

# Catalogue persistence store — uses Postgres if DATABASE_URL is set, else in-memory
DATABASE_URL = os.getenv("DATABASE_URL")
catalogue_store: CatalogueStore = PostgresCatalogueStore(DATABASE_URL) if DATABASE_URL else InMemoryCatalogueStore()

# Active review queues & batch processing results cache
_review_queues: dict[str, ReviewQueue] = {}
_batch_results: dict[str, BatchProcessingResult] = {}
_source_cache = SourceCache()


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class ManufacturerInput(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list)


class EvaluationInput(BaseModel):
    ground_truth_path: str = Field(min_length=1, description="Path to ground-truth CSV")


class ReviewActionInput(BaseModel):
    action: Literal["approve", "reject", "correct"]
    reviewer: str = Field(min_length=1, description="Email or ID of reviewer")
    comment: str | None = None
    corrections: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Reference Data Endpoints
# ---------------------------------------------------------------------------

@router.get("/reference/manufacturers")
def list_manufacturers() -> dict[str, Any]:
    """List all canonical manufacturers in the reference store."""
    return {
        "count": _reference_store.manufacturer_count,
        "source": "seed + private overrides",
    }


@router.get("/reference/brands")
def list_brands() -> dict[str, Any]:
    """List all canonical brands in the reference store."""
    return {
        "count": _reference_store.brand_count,
        "source": "seed + private overrides",
    }


@router.get("/reference/categories")
def list_categories() -> dict[str, Any]:
    """List all canonical categories in the reference store."""
    return {
        "count": _reference_store.category_count,
        "source": "seed + private overrides",
    }


@router.post("/reference/match/manufacturer")
def match_manufacturer(raw: str = Query(min_length=1)) -> dict[str, Any]:
    """Match a raw manufacturer name against the reference store."""
    result = _reference_store.match_manufacturer(raw)
    return {
        "raw_value": result.raw_value,
        "canonical": result.canonical,
        "confidence": result.confidence,
        "match_type": result.match_type,
        "entry_source": result.entry_source,
    }


@router.post("/reference/match/brand")
def match_brand(raw: str = Query(min_length=1)) -> dict[str, Any]:
    """Match a raw brand name against the reference store."""
    result = _reference_store.match_brand(raw)
    return {
        "raw_value": result.raw_value,
        "canonical": result.canonical,
        "confidence": result.confidence,
        "match_type": result.match_type,
    }


@router.post("/reference/normalize/uom")
def normalize_uom_endpoint(raw: str = Query(min_length=1)) -> dict[str, Any]:
    """Normalize a raw unit-of-measure string."""
    result = normalize_uom(raw)
    return {
        "raw": result.raw,
        "canonical": result.canonical,
        "dimension": result.dimension,
        "confidence": result.confidence,
        "recognized": result.recognized,
    }


@router.post("/reference/normalize/material")
def normalize_material_endpoint(raw: str = Query(min_length=1)) -> dict[str, Any]:
    """Normalize a raw material name."""
    result = normalize_material(raw)
    return {
        "raw": result.raw,
        "canonical": result.canonical,
        "confidence": result.confidence,
    }


# ---------------------------------------------------------------------------
# Ingestion & Batch Processing
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {".csv", ".tsv", ".xlsx"}


@router.post("/ingest")
async def ingest_catalogue(
    file: UploadFile = File(...),
    organization_id: str = Query(default="default", min_length=1),
    process_immediately: bool = Query(default=True, description="Process full pipeline on upload"),
) -> dict[str, Any]:
    """Upload a CSV/TSV/XLSX catalogue file, ingest, enrich, validate, and route."""
    filename = file.filename or "uploaded.csv"
    suffix = Path(filename).suffix.casefold()

    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file format '{suffix}'. Use CSV, TSV, or XLSX.",
        )

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File must be 10 MB or smaller")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        raw_batch = read_catalogue(tmp_path)
        batch = CatalogueBatch(filename, raw_batch.columns, raw_batch.rows)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    batch_id = str(uuid4())

    if process_immediately:
        result = process_batch(
            batch=batch,
            store=_reference_store,
            source_cache=_source_cache,
            batch_id=batch_id,
        )
        _batch_results[batch_id] = result
        _review_queues[batch_id] = result.review_queue

        enriched = result.enriched
        validation = result.validation
    else:
        enriched = enrich_batch(batch, _reference_store)
        validation = validate_batch(enriched)
        queue = route_batch_for_review(batch_id, enriched, validation)
        _review_queues[batch_id] = queue

    # Construct batch record
    batch_dict = {
        "batch_id": batch_id,
        "organization_id": organization_id,
        "source_name": filename,
        "columns": list(enriched.columns),
        "row_count": enriched.row_count,
        "total_fields": enriched.total_fields,
        "verified_rate": round(enriched.verified_rate, 4),
        "rows": [
            {
                "row_number": row.row_number,
                "source_fingerprint": row.source_fingerprint,
                "overall_status": row.overall_status,
                "overall_confidence": row.overall_confidence,
                "verified_count": row.verified_count,
                "review_count": row.review_count,
                "review_state": (_review_queues[batch_id].get_row(batch_id, row.row_number).state.value
                                if batch_id in _review_queues and _review_queues[batch_id].get_row(batch_id, row.row_number)
                                else "pending_review"),
                "fields": [
                    {
                        "column": f.column,
                        "raw_value": f.raw_value,
                        "canonical_value": f.canonical_value,
                        "confidence": f.confidence,
                        "status": f.status,
                        "role": f.role,
                        "normalized_unit": f.normalized_unit,
                        "evidence": {
                            "source_file": f.evidence.source_file,
                            "source_row": f.evidence.source_row,
                            "source_column": f.evidence.source_column,
                            "raw_value": f.evidence.raw_value,
                            "transformation": f.evidence.transformation,
                        },
                    }
                    for f in row.fields
                ],
            }
            for row in enriched.rows
        ],
    }

    # Save to persistence store
    catalogue_store.save_batch(batch_dict)

    return {
        "batch_id": batch_id,
        "source_name": filename,
        "row_count": enriched.row_count,
        "total_fields": enriched.total_fields,
        "verified_rate": round(enriched.verified_rate, 4),
        "columns": list(enriched.columns),
        "validation_summary": {
            "auto_approve_count": validation.auto_approve_count,
            "review_required_count": validation.review_required_count,
            "auto_approve_rate": round(validation.auto_approve_rate, 4),
            "total_issues": validation.total_issues,
        },
    }


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, organization_id: str = Query(default="default")) -> dict[str, Any]:
    """Retrieve a previously ingested batch with full enrichment and review state."""
    batch = catalogue_store.get_batch(organization_id, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Attach live review queue state if available
    queue = _review_queues.get(batch_id)
    if queue:
        batch["review_summary"] = queue.get_batch_summary(batch_id)

    # Attach processing metrics if available
    result = _batch_results.get(batch_id)
    if result:
        batch["metrics"] = result.metrics.summary()
        batch["cost"] = result.cost.summary()

    return batch


@router.get("/batches/{batch_id}/rows/{row_number}")
def get_batch_row(batch_id: str, row_number: int, organization_id: str = Query(default="default")) -> dict[str, Any]:
    """Retrieve a single row from a batch with field details and review state."""
    batch = catalogue_store.get_batch(organization_id, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    for row in batch["rows"]:
        if row["row_number"] == row_number:
            queue = _review_queues.get(batch_id)
            if queue:
                reviewable = queue.get_row(batch_id, row_number)
                if reviewable:
                    row["review_detail"] = reviewable.to_dict()
            return row
    raise HTTPException(status_code=404, detail=f"Row {row_number} not found in batch")


@router.get("/batches")
def list_batches(organization_id: str = Query(default="default")) -> dict[str, Any]:
    """List all ingested batches (summary only)."""
    summaries = catalogue_store.list_batches(organization_id)
    return {"batches": summaries, "count": len(summaries)}


# ---------------------------------------------------------------------------
# Human Review Endpoints
# ---------------------------------------------------------------------------

@router.get("/batches/{batch_id}/review/pending")
def list_pending_review(
    batch_id: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """List rows pending human review for a batch, ordered by priority."""
    queue = _review_queues.get(batch_id)
    if not queue:
        return {"batch_id": batch_id, "pending_rows": [], "count": 0}

    pending = queue.get_pending(batch_id, limit=limit)
    return {
        "batch_id": batch_id,
        "count": len(pending),
        "pending_rows": [r.to_dict() for r in pending],
    }


@router.post("/batches/{batch_id}/rows/{row_number}/review")
def review_row_endpoint(
    batch_id: str,
    row_number: int,
    payload: ReviewActionInput,
    organization_id: str = Query(default="default"),
) -> dict[str, Any]:
    """Approve, reject, or correct a single catalogue row."""
    queue = _review_queues.get(batch_id)
    if not queue:
        # Reconstruct queue from batch if available
        batch = catalogue_store.get_batch(organization_id, batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")

    try:
        if payload.action == "approve":
            updated = approve_row(queue, batch_id, row_number, payload.reviewer, payload.comment)
        elif payload.action == "reject":
            updated = reject_row(queue, batch_id, row_number, payload.reviewer, payload.comment)
        elif payload.action == "correct":
            if not payload.corrections:
                raise HTTPException(status_code=400, detail="Corrections dict required for 'correct' action")
            updated = correct_row(queue, batch_id, row_number, payload.reviewer, payload.corrections, payload.comment)
        else:
            raise HTTPException(status_code=400, detail=f"Invalid review action '{payload.action}'")

        # Persist review state change
        catalogue_store.update_row_review_state(
            organization_id, batch_id, row_number,
            updated.state.value, payload.reviewer, payload.corrections,
        )

        return {
            "batch_id": batch_id,
            "row_number": row_number,
            "review_state": updated.state.value,
            "updated_row": updated.to_dict(),
        }
    except ReviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Source Discovery & Verification
# ---------------------------------------------------------------------------

@router.get("/batches/{batch_id}/sources")
def get_batch_sources(
    batch_id: str,
    organization_id: str = Query(default="default"),
) -> dict[str, Any]:
    """Retrieve manufacturer source discovery results for a batch."""
    result = _batch_results.get(batch_id)
    if not result:
        return {"batch_id": batch_id, "source_count": 0, "sources": []}

    return {
        "batch_id": batch_id,
        "source_count": len(result.sources),
        "sources": [s.to_dict() for s in result.sources],
    }


# ---------------------------------------------------------------------------
# Export Endpoints
# ---------------------------------------------------------------------------

@router.get("/batches/{batch_id}/export")
def export_batch_endpoint(
    batch_id: str,
    format: Literal["csv", "json", "commerce_csv", "audit", "unilog_template"] = Query(default="csv"),
    organization_id: str = Query(default="default"),
) -> Response:
    """Export an enriched batch in CSV, JSON, Commerce CSV, Audit JSON, or Unilog 252-column template format."""
    batch_dict = catalogue_store.get_batch(organization_id, batch_id)
    if not batch_dict:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Reconstruct EnrichedBatch from stored dict
    raw_rows = [
        {f["column"]: f["raw_value"] for f in row.get("fields", [])}
        for row in batch_dict["rows"]
    ] if "fields" in batch_dict["rows"][0] else [
        row.get("raw_values", {}) for row in batch_dict["rows"]
    ]

    ingested = normalize_rows(batch_dict["source_name"], raw_rows)
    enriched = enrich_batch(ingested, _reference_store)
    queue = _review_queues.get(batch_id)

    filename_base = Path(batch_dict["source_name"]).stem

    if format == "csv":
        content = export_csv(enriched)
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}_enriched.csv"'},
        )
    elif format == "commerce_csv":
        content = export_commerce_csv(enriched)
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}_commerce.csv"'},
        )
    elif format == "unilog_template":
        content = export_unilog_template(enriched)
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}_unilog_252.csv"'},
        )
    elif format == "json":
        validation = validate_batch(enriched)
        content = export_json(enriched, validation=validation, review_queue=queue)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}_enriched.json"'},
        )
    elif format == "audit":
        content = export_audit_json(enriched, review_queue=queue, batch_id=batch_id)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}_audit.json"'},
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format '{format}'")



# ---------------------------------------------------------------------------
# Ground-Truth Evaluation
# ---------------------------------------------------------------------------

@router.post("/batches/{batch_id}/evaluate")
def evaluate_batch(
    batch_id: str,
    payload: EvaluationInput,
    organization_id: str = Query(default="default"),
) -> dict[str, Any]:
    """Evaluate a batch against a ground-truth CSV file."""
    batch_dict = catalogue_store.get_batch(organization_id, batch_id)
    if batch_dict is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    gt_path = Path(payload.ground_truth_path)
    if not gt_path.exists():
        raise HTTPException(status_code=404, detail=f"Ground truth file not found: {gt_path}")

    try:
        gt_rows = load_ground_truth_csv(gt_path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to load ground truth: {exc}") from exc

    raw_rows = [
        {f["column"]: f["raw_value"] for f in row.get("fields", [])}
        for row in batch_dict["rows"]
    ] if "fields" in batch_dict["rows"][0] else [
        row.get("raw_values", {}) for row in batch_dict["rows"]
    ]

    try:
        ingested = normalize_rows(batch_dict["source_name"], raw_rows)
        enriched = enrich_batch(ingested, _reference_store)
        report = evaluate(enriched, gt_rows)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {exc}") from exc

    return report.to_dict()
