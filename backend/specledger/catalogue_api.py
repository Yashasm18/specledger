"""FastAPI router for catalogue ingestion, enrichment, and evaluation.

Provides endpoints for:
  - Uploading CSV/TSV/XLSX catalogue files
  - Viewing ingested batches with enrichment results
  - Running ground-truth evaluations
  - Managing reference data (manufacturers, brands)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile, Query
from pydantic import BaseModel, Field

from .catalogue_ingestion import read_catalogue, CatalogueBatch
from .enrichment import enrich_batch, EnrichedBatch
from .evaluator import evaluate, load_ground_truth_csv, EvaluationReport, GroundTruthRow
from .reference_data import ReferenceStore
from .uom import normalize_uom, normalize_material

router = APIRouter(prefix="/catalogue", tags=["catalogue"])

# Module-level reference store — loaded once, reused across requests
_reference_dir = os.getenv("SPECLEDGER_REFERENCE_DIR", "data/reference")
_reference_store = ReferenceStore(reference_dir=_reference_dir)

# In-memory batch cache for the prototype. Production uses PostgreSQL.
_batch_cache: dict[str, dict[str, Any]] = {}


class ManufacturerInput(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list)


class EvaluationInput(BaseModel):
    ground_truth_path: str = Field(min_length=1, description="Path to ground-truth CSV")


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


ALLOWED_CONTENT_TYPES = {
    "text/csv",
    "text/tab-separated-values",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/octet-stream",  # Some clients send this for CSV
}

ALLOWED_EXTENSIONS = {".csv", ".tsv", ".xlsx"}


@router.post("/ingest")
async def ingest_catalogue(
    file: UploadFile = File(...),
    organization_id: str = Query(default="default", min_length=1),
) -> dict[str, Any]:
    """Upload a CSV/TSV/XLSX catalogue file, ingest, and enrich.

    Returns the batch_id and summary metrics. The full enriched data
    can be retrieved via GET /catalogue/batches/{batch_id}.
    """
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

    # Write to temp file for reading
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        batch = read_catalogue(tmp_path)
        # Override source_name with the original filename
        batch = CatalogueBatch(filename, batch.columns, batch.rows)
        enriched = enrich_batch(batch, _reference_store)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # Store in memory cache (production: PostgreSQL)
    batch_id = str(uuid4())
    _batch_cache[batch_id] = {
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

    return {
        "batch_id": batch_id,
        "source_name": filename,
        "row_count": enriched.row_count,
        "total_fields": enriched.total_fields,
        "verified_rate": round(enriched.verified_rate, 4),
        "columns": list(enriched.columns),
    }


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str) -> dict[str, Any]:
    """Retrieve a previously ingested batch with full enrichment data."""
    batch = _batch_cache.get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


@router.get("/batches/{batch_id}/rows/{row_number}")
def get_batch_row(batch_id: str, row_number: int) -> dict[str, Any]:
    """Retrieve a single row from a batch."""
    batch = _batch_cache.get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    for row in batch["rows"]:
        if row["row_number"] == row_number:
            return row
    raise HTTPException(status_code=404, detail=f"Row {row_number} not found in batch")


@router.get("/batches")
def list_batches() -> dict[str, Any]:
    """List all ingested batches (summary only)."""
    summaries = [
        {
            "batch_id": b["batch_id"],
            "source_name": b["source_name"],
            "row_count": b["row_count"],
            "verified_rate": b["verified_rate"],
        }
        for b in _batch_cache.values()
    ]
    return {"batches": summaries, "count": len(summaries)}


@router.post("/batches/{batch_id}/evaluate")
def evaluate_batch(batch_id: str, payload: EvaluationInput) -> dict[str, Any]:
    """Evaluate a batch against a ground-truth CSV file.

    The ground_truth_path must point to an accessible CSV file on the server.
    """
    batch = _batch_cache.get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    gt_path = Path(payload.ground_truth_path)
    if not gt_path.exists():
        raise HTTPException(status_code=404, detail=f"Ground truth file not found: {gt_path}")

    try:
        gt_rows = load_ground_truth_csv(gt_path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to load ground truth: {exc}") from exc

    # Reconstruct enriched batch from cache for evaluation
    from .catalogue_ingestion import normalize_rows
    raw_rows = [
        {f["column"]: f["raw_value"] for f in row["fields"]}
        for row in batch["rows"]
    ]

    try:
        ingested = normalize_rows(batch["source_name"], raw_rows)
        enriched = enrich_batch(ingested, _reference_store)
        report = evaluate(enriched, gt_rows)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {exc}") from exc

    return report.to_dict()
