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

import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, Query, Response
from pydantic import BaseModel, Field

from .auth import require_api_key
from .rate_limit import limiter
from .catalogue_ingestion import read_catalogue, CatalogueBatch, normalize_rows, SourceRow, clean_manufacturer_name
from .enrichment import enrich_batch
from .evaluator import evaluate, load_ground_truth_csv
from .reference_data import ReferenceStore
from .uom import normalize_uom, normalize_material
from .validation_engine import validate_batch
from .human_review import (
    route_batch_for_review, approve_row, reject_row, correct_row,
    ReviewQueue, ReviewError, ReviewState,
)
from .batch_processor import process_batch, BatchProcessingResult, SourceCache
from .export import (
    export_csv, export_json, export_commerce_csv, export_audit_json,
    export_unilog_template, export_schema_org_jsonld,
)
from .catalogue_persistence import CatalogueStore, InMemoryCatalogueStore, PostgresCatalogueStore
from .database import resolve_database_url
from .source_discovery import discover_sources_live, SourceStatus
from .unilog_exporter import row_to_unilog_dict
from .web_enricher import classify_category
from .llm_enricher import enrich_unresolved, is_llm_configured, needs_llm


router = APIRouter(prefix="/catalogue", tags=["catalogue"])

# Module-level reference store — loaded once, reused across requests
_reference_dir = os.getenv("SPECLEDGER_REFERENCE_DIR", "data/reference")
_reference_store = ReferenceStore(reference_dir=_reference_dir)

# PostgreSQL is the system of record. resolve_database_url() raises rather
# than returning None unless ephemeral storage was explicitly opted into, so
# a deployment can never silently end up writing to memory.
DATABASE_URL = resolve_database_url()
catalogue_store: CatalogueStore = (
    PostgresCatalogueStore(DATABASE_URL) if DATABASE_URL else InMemoryCatalogueStore()
)

# Active review queues & batch processing results cache
_review_queues: dict[str, ReviewQueue] = {}
_batch_results: dict[str, BatchProcessingResult] = {}
_source_cache = SourceCache()


def _ensure_seed_batch(organization_id: str = "default") -> str | None:
    """Ensure at least one sample or ground truth batch is loaded in store."""
    summaries = catalogue_store.list_batches(organization_id)
    if summaries:
        return summaries[0]["batch_id"]

    seed_paths = [
        "data/challenge/Unihack_ Sample Dataset - Input.csv",
        "Unihack_ Sample Dataset - Input.csv",
        "data/ground_truth/synthetic_200_valves.csv",
    ]
    for sp in seed_paths:
        if Path(sp).exists():
            try:
                raw_batch = read_catalogue(sp)
                batch = CatalogueBatch(Path(sp).name, raw_batch.columns, raw_batch.rows)
                batch_id = str(uuid4())
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

                batch_dict = {
                    "batch_id": batch_id,
                    "organization_id": organization_id,
                    "source_name": Path(sp).name,
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
                catalogue_store.save_batch(batch_dict)
                return batch_id
            except Exception:
                pass
    return None


def _resolve_batch_id(batch_id: str, organization_id: str = "default") -> str:
    """Resolve 'latest' or unknown alias to most recent batch ID."""
    if batch_id == "latest":
        resolved = _ensure_seed_batch(organization_id)
        if resolved:
            return resolved
    return batch_id


# Review states that record an actual human action, as opposed to the
# states the routing algorithm assigns on its own. Only these survive a
# queue rebuild — see _rebuild_review_queue().
_HUMAN_DECISION_STATES = frozenset({
    ReviewState.APPROVED.value,
    ReviewState.REJECTED.value,
    ReviewState.CORRECTED.value,
})


def _rebuild_review_queue(batch_id: str, organization_id: str = "default") -> ReviewQueue | None:
    """Rebuild the in-memory review queue for a batch from persisted Postgres
    state. `_review_queues`/`_batch_results` are process-local caches that
    don't survive a redeploy, but catalogue_rows.raw_values/review_state do —
    so re-run the deterministic enrichment/validation/routing pipeline against
    the persisted raw values, then overlay any human review decisions already
    recorded in Postgres so they aren't reset to their auto-routed state.
    """
    stored = catalogue_store.get_batch(organization_id, batch_id)
    if not stored or not stored.get("rows"):
        return None

    source_rows = tuple(
        SourceRow(
            row_number=r["row_number"],
            source_name=stored["source_name"],
            source_fingerprint=r["source_fingerprint"],
            values=r["raw_values"],
        )
        for r in stored["rows"]
    )
    batch = CatalogueBatch(stored["source_name"], tuple(stored["columns"]), source_rows)

    result = process_batch(
        batch=batch,
        store=_reference_store,
        source_cache=_source_cache,
        batch_id=batch_id,
    )
    queue = result.review_queue

    for r in stored["rows"]:
        persisted_state = r.get("review_state")
        # Only a real human decision may override the freshly recomputed
        # routing. "pending_review"/"auto_approved" are outputs of the
        # routing algorithm, not decisions — replaying a persisted copy of
        # them would freeze whatever validation logic was in effect at
        # ingest time, so an improvement to the rules could never reach
        # rows that were already stored (which is exactly what stranded
        # auto-approvable rows in the pending queue).
        if persisted_state not in _HUMAN_DECISION_STATES:
            continue
        reviewable = queue.get_row(batch_id, r["row_number"])
        if reviewable and reviewable.state.value != persisted_state:
            try:
                reviewable.state = ReviewState(persisted_state)
            except ValueError:
                pass

    _batch_results[batch_id] = result
    _review_queues[batch_id] = queue
    return queue


def _get_review_queue(batch_id: str, organization_id: str = "default") -> ReviewQueue | None:
    queue = _review_queues.get(batch_id)
    if queue is not None:
        return queue
    return _rebuild_review_queue(batch_id, organization_id)


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


@router.post("/ingest", dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def ingest_catalogue(
    request: Request,
    file: UploadFile = File(...),
    organization_id: str = Query(default="default", min_length=1),
    process_immediately: bool = Query(default=True, description="Process full pipeline on upload"),
    live_fetch: bool = Query(
        default=False,
        description="Discover sources via real HTTP fetches to manufacturer sites instead of templated candidates. Capped at 50 rows per request.",
    ),
    ai_assist: bool = Query(
        default=False,
        description=(
            "Run the LLM tier over rows the deterministic classifier left in "
            "the generic bucket. Requires GEMINI_API_KEY; a no-op without it. "
            "Suggestions are marked ai_inferred and always require human review."
        ),
    ),
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

    if live_fetch and len(batch.rows) > 50:
        raise HTTPException(
            status_code=422,
            detail=f"live_fetch is capped at 50 rows per request to bound real-network wall time; this file has {len(batch.rows)} rows. Disable live_fetch or split the file.",
        )

    batch_id = str(uuid4())

    if process_immediately:
        result = process_batch(
            batch=batch,
            store=_reference_store,
            source_cache=_source_cache,
            batch_id=batch_id,
            live_fetch=live_fetch,
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

    # Optional LLM tier — runs after deterministic enrichment, only on its
    # residue, and only when explicitly requested and configured.
    llm_suggestions, llm_usage = _run_llm_tier(batch) if ai_assist else ({}, None)

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

    # Attach AI suggestions to the rows they belong to. Stored alongside the
    # deterministic result rather than replacing it, so both remain visible
    # and the row still carries its rule-based classification.
    if llm_suggestions:
        for row_dict in batch_dict["rows"]:
            suggestion = llm_suggestions.get(row_dict["row_number"])
            if suggestion:
                row_dict["llm_suggestion"] = suggestion.to_dict()
    if llm_usage:
        batch_dict["llm_usage"] = llm_usage

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


def _run_llm_tier(
    batch: CatalogueBatch,
) -> tuple[dict[int, Any], dict[str, Any] | None]:
    """Run the optional LLM tier over rows deterministic rules left generic.

    Returns (suggestions_by_row_number, usage_summary). The deterministic
    classifier runs first and keeps whatever it resolved; only its residue is
    sent, so the LLM never overwrites a rule-based answer and never sees rows
    the free path already handled.
    """
    if not is_llm_configured():
        return {}, None

    unresolved: list[dict[str, Any]] = []
    for row in batch.rows:
        vals = row.values
        desc = vals.get("part_desc") or vals.get("description") or ""
        mfr = vals.get("part_manuf") or vals.get("manufacturer") or ""
        if not needs_llm(classify_category(desc, mfr)):
            continue
        unresolved.append({
            "id": row.row_number,
            "part_number": vals.get("mfg_part_num") or vals.get("part_number") or "",
            "manufacturer": mfr,
            "description": desc,
        })

    if not unresolved:
        return {}, None

    result = enrich_unresolved(unresolved)
    return result.suggestions, result.usage.to_dict()


def _unilog_args_from_raw(
    vals: dict[str, Any],
) -> tuple[str, Any, Any, Any, Any, Any]:
    """Map a row's raw source values onto row_to_unilog_dict()'s positional
    arguments. The official challenge columns (mfg_part_num, part_desc,
    part_manuf, ...) are checked first, with generic names as the fallback so
    an uploaded file that uses its own headers still resolves.
    """
    return (
        vals.get("mfg_part_num") or vals.get("part_number") or "",
        vals.get("part_manuf") or vals.get("manufacturer"),
        vals.get("part_desc") or vals.get("description"),
        vals.get("e1_brand"),
        vals.get("unilog_brand"),
        vals.get("dib_brand"),
    )


def _attach_categories(rows: list[dict[str, Any]]) -> None:
    """Inject a real, deterministic classpath into each row (mutates in
    place) — the raw 6-column input never has a category column, so
    findByRole-style role detection alone always resolves to "Uncategorized".
    classify_category() is the same keyword-based logic used for the real
    252-column export, just applied here without needing that full record.
    """
    for row in rows:
        vals = row.get("raw_values") or {f["column"]: f["raw_value"] for f in row.get("fields", [])}
        desc = vals.get("part_desc") or vals.get("description") or ""
        mfr = vals.get("part_manuf") or vals.get("manufacturer") or ""
        deterministic = classify_category(desc, mfr)
        row["category"] = deterministic
        row["category_source"] = "deterministic"

        # Where the rules produced only the generic bucket, surface the LLM's
        # suggestion instead — flagged as AI-derived, never silently merged,
        # and with the deterministic answer still available beside it.
        suggestion = row.get("llm_suggestion")
        if suggestion and needs_llm(deterministic):
            row["category"] = suggestion["classpath"]
            row["category_source"] = "ai_inferred"
            row["category_deterministic"] = deterministic
            row["category_confidence"] = suggestion.get("confidence")


def _overlay_live_review_state(
    rows: list[dict[str, Any]], batch_id: str, queue: ReviewQueue,
    result: BatchProcessingResult | None,
) -> None:
    """Refresh each row's review_state/overall_confidence in place from the
    live queue and recomputed enrichment (mutates `rows`).

    Both values are *derived*, and the copies persisted at ingest time were
    produced by whatever rules were in effect then. Serving those stale
    copies alongside a freshly computed review_summary put contradictory
    numbers in the same response — the row list said 988 rows needed review
    while the summary said 800. The queue is the current source of truth.
    """
    confidence_by_row = (
        {r.row_number: r.overall_confidence for r in result.enriched.rows}
        if result else {}
    )
    for row in rows:
        reviewable = queue.get_row(batch_id, row["row_number"])
        if reviewable:
            row["review_state"] = reviewable.state.value
        fresh_confidence = confidence_by_row.get(row["row_number"])
        if fresh_confidence is not None:
            row["overall_confidence"] = fresh_confidence


@router.get("/batches/{batch_id}")
def get_batch(
    batch_id: str,
    organization_id: str = Query(default="default"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_fields: bool = Query(
        default=False,
        description=(
            "Include each row's per-field enrichment evidence. Off by default "
            "because it is the bulk of the payload and list views don't read "
            "it — per-field detail belongs to the single-row endpoint."
        ),
    ),
) -> dict[str, Any]:
    """Retrieve a batch's metadata and one page of its enriched rows.

    Rows are paginated. Returning a whole batch inline does not survive real
    catalogue sizes — the 1,000-row sample alone was a 767 KB, 11-second
    response, and the target workload is 750,000 SKUs/month. `row_count` is
    always the batch total; `returned_rows`/`offset`/`limit`/`has_more`
    describe this page. Anything reporting a batch-wide figure must use
    `row_count` or `review_summary`, never the length of `rows`.
    """
    real_id = _resolve_batch_id(batch_id, organization_id)
    # Push the page down to the store so only these rows are ever loaded —
    # slicing after fetching everything defeats the purpose at scale.
    batch = catalogue_store.get_batch(
        organization_id, real_id, row_limit=limit, row_offset=offset,
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    # row_count comes from the batch record, so it stays the true total even
    # though only one page of rows was fetched.
    total_rows = batch.get("row_count", 0)
    # Copy the page: _attach_categories and the review-state overlay both
    # mutate, and the in-memory store hands back its rows by reference.
    page = [dict(row) for row in batch.get("rows", [])]

    _attach_categories(page)

    queue = _get_review_queue(real_id, organization_id)
    if queue:
        _overlay_live_review_state(page, real_id, queue, _batch_results.get(real_id))

    # Drop the per-field evidence after categories are attached — the
    # fallback path in _attach_categories reads it when raw_values is absent.
    if not include_fields:
        for row in page:
            row.pop("fields", None)

    response = {k: v for k, v in batch.items() if k != "rows"}
    response["rows"] = page
    response["row_count"] = batch.get("row_count", total_rows)
    response["returned_rows"] = len(page)
    response["offset"] = offset
    response["limit"] = limit
    response["has_more"] = offset + len(page) < total_rows

    if queue:
        response["review_summary"] = queue.get_batch_summary(real_id)

    result = _batch_results.get(real_id)
    if result:
        response["metrics"] = result.metrics.summary()
        response["cost"] = result.cost.summary()

    return response


@router.get("/batches/{batch_id}/rows/{row_number}")
def get_batch_row(batch_id: str, row_number: int, organization_id: str = Query(default="default")) -> dict[str, Any]:
    """Retrieve a single row from a batch with field details and review state."""
    real_id = _resolve_batch_id(batch_id, organization_id)
    batch = catalogue_store.get_batch(organization_id, real_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    for row in batch["rows"]:
        if row["row_number"] == row_number:
            _attach_categories([row])
            queue = _get_review_queue(real_id, organization_id)
            if queue:
                reviewable = queue.get_row(real_id, row_number)
                if reviewable:
                    row["review_detail"] = reviewable.to_dict()
                _overlay_live_review_state(
                    [row], real_id, queue, _batch_results.get(real_id),
                )
            return row
    raise HTTPException(status_code=404, detail=f"Row {row_number} not found in batch")


@router.get("/batches/{batch_id}/rows/{row_number}/unilog252")
def get_batch_row_unilog252(batch_id: str, row_number: int, organization_id: str = Query(default="default")) -> dict[str, Any]:
    """Retrieve one row's full real 252-column Unilog record.

    Reuses the same row_to_unilog_dict() that generates the actual CSV
    export, so this is the genuine computed record for this row — not a
    separate, client-rendered approximation of it.
    """
    real_id = _resolve_batch_id(batch_id, organization_id)
    batch = catalogue_store.get_batch(organization_id, real_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    for row in batch["rows"]:
        if row["row_number"] == row_number:
            # Postgres flattens fields -> raw_values at write time; the
            # in-memory dev store doesn't, so fall back to building it from
            # the fields array directly for parity between both backends.
            vals = row.get("raw_values") or {f["column"]: f["raw_value"] for f in row.get("fields", [])}
            return row_to_unilog_dict(*_unilog_args_from_raw(vals))
    raise HTTPException(status_code=404, detail=f"Row {row_number} not found in batch")


@router.get("/batches")
def list_batches(organization_id: str = Query(default="default")) -> dict[str, Any]:
    """List all ingested batches (summary only)."""
    summaries = catalogue_store.list_batches(organization_id)
    if not summaries:
        _ensure_seed_batch(organization_id)
        summaries = catalogue_store.list_batches(organization_id)
    return {"batches": summaries, "count": len(summaries)}


# ---------------------------------------------------------------------------
# Human Review Endpoints
# ---------------------------------------------------------------------------

@router.get("/batches/{batch_id}/review/pending")
def list_pending_review(
    batch_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    organization_id: str = Query(default="default"),
) -> dict[str, Any]:
    """List rows pending human review for a batch, ordered by priority.

    `total_pending` is the real number of rows awaiting review across the
    whole batch; `count` is only how many this page returned. They differ
    whenever the queue is longer than `limit`, so callers displaying a
    "rows needing review" figure must use `total_pending` — using `count`
    silently caps the reported backlog at the page size.
    """
    real_id = _resolve_batch_id(batch_id, organization_id)
    queue = _get_review_queue(real_id, organization_id)
    if not queue:
        return {
            "batch_id": real_id, "pending_rows": [], "count": 0,
            "total_pending": 0, "limit": limit, "summary": None,
        }

    pending = queue.get_pending(real_id, limit=limit)
    summary = queue.get_batch_summary(real_id)

    # Attach each row's confidence from the recomputed enrichment rather than
    # the value persisted at ingest time — the stored copy reflects whatever
    # scoring logic was in effect when the batch was first ingested, so a
    # reviewer would otherwise be shown a stale number next to freshly
    # recomputed validation issues.
    result = _batch_results.get(real_id)
    confidence_by_row = (
        {r.row_number: r.overall_confidence for r in result.enriched.rows}
        if result else {}
    )
    stored_batch = catalogue_store.get_batch(organization_id, real_id)
    stored_rows_by_number = (
        {row["row_number"]: row for row in stored_batch.get("rows", [])}
        if stored_batch else {}
    )

    # Identify each row inline. The queue is priority-ordered across the whole
    # batch, so its rows are mostly outside whatever page the catalogue view
    # has loaded — a reviewer looking these up in the page's own rows saw
    # "Row 743" instead of a part number for every entry, and could not tell
    # what they were approving.
    identity_by_row: dict[int, dict[str, Any]] = {}
    for stored_row in (stored_rows_by_number or {}).values():
        vals = stored_row.get("raw_values") or {}
        identity_by_row[stored_row["row_number"]] = {
            "part_number": vals.get("mfg_part_num") or vals.get("part_number"),
            "description": vals.get("part_desc") or vals.get("description"),
            "manufacturer": vals.get("part_manuf") or vals.get("manufacturer"),
        }

    rows_out = []
    for r in pending:
        row_dict = r.to_dict()
        row_dict["overall_confidence"] = confidence_by_row.get(r.row_number)
        row_dict.update(identity_by_row.get(r.row_number, {}))
        rows_out.append(row_dict)

    return {
        "batch_id": real_id,
        "count": len(pending),
        "total_pending": summary["pending_review"],
        "limit": limit,
        "summary": summary,
        "pending_rows": rows_out,
    }


@router.get("/batches/{batch_id}/audit")
def list_audit_events(
    batch_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    organization_id: str = Query(default="default"),
) -> dict[str, Any]:
    """List real audit events recorded for a batch, most recent first.

    Every ingest routes each row through route_batch_for_review, which
    records a real AuditEvent (auto_approve or submit_for_review) even
    before any human acts — so this reflects genuine pipeline activity,
    not a fixed illustrative sample.
    """
    real_id = _resolve_batch_id(batch_id, organization_id)
    queue = _get_review_queue(real_id, organization_id)
    if not queue:
        return {"batch_id": real_id, "events": [], "count": 0, "total_events": 0, "limit": limit}

    events = queue.get_audit_events(real_id, limit=limit)
    return {
        "batch_id": real_id,
        "count": len(events),
        "total_events": queue.count_audit_events(real_id),
        "limit": limit,
        "events": [e.to_dict() for e in events],
    }


@router.post("/batches/{batch_id}/rows/{row_number}/review", dependencies=[Depends(require_api_key)])
def review_row_endpoint(
    batch_id: str,
    row_number: int,
    payload: ReviewActionInput,
    organization_id: str = Query(default="default"),
) -> dict[str, Any]:
    """Approve, reject, or correct a single catalogue row."""
    real_id = _resolve_batch_id(batch_id, organization_id)
    queue = _get_review_queue(real_id, organization_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Batch not found")

    try:
        if payload.action == "approve":
            updated = approve_row(queue, real_id, row_number, payload.reviewer, payload.comment)
        elif payload.action == "reject":
            updated = reject_row(queue, real_id, row_number, payload.reviewer, payload.comment)
        elif payload.action == "correct":
            if not payload.corrections:
                raise HTTPException(status_code=400, detail="Corrections dict required for 'correct' action")
            updated = correct_row(queue, real_id, row_number, payload.reviewer, payload.corrections, payload.comment)
        else:
            raise HTTPException(status_code=400, detail=f"Invalid review action '{payload.action}'")

        # Persist review state change
        catalogue_store.update_row_review_state(
            organization_id, real_id, row_number,
            updated.state.value, payload.reviewer, payload.corrections,
        )

        return {
            "batch_id": real_id,
            "row_number": row_number,
            "review_state": updated.state.value,
            "updated_row": updated.to_dict(),
        }
    except ReviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Source Discovery & Verification
# ---------------------------------------------------------------------------

@router.post("/batches/{batch_id}/rows/{row_number}/verify", dependencies=[Depends(require_api_key)])
@limiter.limit("20/minute")
def verify_row_live(
    request: Request,
    batch_id: str,
    row_number: int,
    organization_id: str = Query(default="default"),
) -> dict[str, Any]:
    """Verify one row against live manufacturer sources, on demand.

    Everything returned here is fetched during this request. The point is not
    that the pipeline claims a value — it is that the caller can check the
    claim: each verified source carries the URL that was fetched and the
    visible page text surrounding the part number, so opening the link and
    searching the page reproduces the match.

    Honest failure is a first-class outcome. When nothing is found this
    returns verified=false with the URLs that were tried, rather than a
    plausible-looking guess. On real catalogue data that happens often —
    manufacturers retire pages, some parts were never published, and some
    sites refuse automated requests.
    """
    real_id = _resolve_batch_id(batch_id, organization_id)
    stored = catalogue_store.get_batch_row(organization_id, real_id, row_number)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Row {row_number} not found in batch")

    vals = stored.get("raw_values") or {
        f["column"]: f["raw_value"] for f in stored.get("fields", [])
    }
    part_number = (vals.get("mfg_part_num") or vals.get("part_number") or "").strip()
    raw_manufacturer = (vals.get("part_manuf") or vals.get("manufacturer") or "").strip()
    description = (vals.get("part_desc") or vals.get("description") or "").strip()
    if not part_number:
        raise HTTPException(status_code=422, detail="Row has no part number to verify")

    # The raw field carries a distributor code, e.g.
    # "Jam Industrial Supply LLC (JAMIN)". Compare against the cleaned name so
    # stripping that code is not mistaken for resolving a different company.
    cleaned_manufacturer = clean_manufacturer_name(raw_manufacturer) or raw_manufacturer

    started = time.perf_counter()
    discovery = discover_sources_live(
        manufacturer=cleaned_manufacturer,
        part_number=part_number,
        description=description,
        # Interactive: report what was found within a bounded wait rather than
        # trying every candidate at full timeout.
        budget_seconds=20.0,
        timeout=5.0,
    )
    elapsed = time.perf_counter() - started

    sources = []
    attributes: list[dict[str, str]] = []
    for source in discovery.sources:
        item = source.to_dict()
        item["is_verified"] = source.status == SourceStatus.VERIFIED
        sources.append(item)
        for label, value in source.extracted_attributes:
            attributes.append({"label": label, "value": value, "source_url": source.url})

    verified = [s for s in sources if s["is_verified"]]

    # The raw input's manufacturer field is frequently a distributor. Saying
    # so explicitly is the point of the exercise, not an incidental detail.
    resolved = discovery.resolved_manufacturer
    return {
        "batch_id": real_id,
        "row_number": row_number,
        "part_number": part_number,
        "input_manufacturer": raw_manufacturer,
        "resolved_manufacturer": resolved,
        "cleaned_manufacturer": cleaned_manufacturer,
        "manufacturer_was_corrected": bool(
            resolved and resolved.strip().casefold() != cleaned_manufacturer.strip().casefold()
        ),
        "verified": bool(verified),
        "verified_source_count": len(verified),
        "sources": sources,
        "urls_attempted": discovery.search_queries,
        "blocked_urls": discovery.blocked_urls,
        "extracted_attributes": attributes,
        "seconds": round(elapsed, 2),
        "fetched_at_request_time": True,
    }


@router.get("/batches/{batch_id}/sources")
def get_batch_sources(
    batch_id: str,
    organization_id: str = Query(default="default"),
) -> dict[str, Any]:
    """Retrieve manufacturer source discovery results for a batch."""
    real_id = _resolve_batch_id(batch_id, organization_id)
    result = _batch_results.get(real_id)
    if not result:
        _get_review_queue(real_id, organization_id)
        result = _batch_results.get(real_id)
    if not result:
        return {"batch_id": real_id, "source_count": 0, "sources": []}

    sources = []
    verified_count = 0
    for discovery in result.sources:
        for source in discovery.sources:
            item = source.to_dict()
            item["discovery_mode"] = discovery.discovery_mode
            is_verified = source.status.value == "verified"
            item["evidence_status"] = "verified_live" if is_verified else "candidate_unverified"
            if is_verified:
                verified_count += 1
            sources.append(item)

    discovery_modes = {discovery.discovery_mode for discovery in result.sources if discovery.sources or discovery.search_queries}

    return {
        "batch_id": real_id,
        "source_count": len(sources),
        "sources": sources,
        "verified_source_count": verified_count,
        "discovery_mode": "live" if "live" in discovery_modes else "simulated_candidates",
    }


# ---------------------------------------------------------------------------
# Export Endpoints
# ---------------------------------------------------------------------------

@router.get("/batches/{batch_id}/export")
def export_batch_endpoint(
    batch_id: str,
    format: Literal["csv", "json", "commerce_csv", "audit", "unilog_template", "schema_org", "jsonld"] = Query(default="csv"),
    organization_id: str = Query(default="default"),
) -> Response:
    """Export an enriched batch in CSV, JSON, Commerce CSV, Audit JSON, Unilog 252-column template, or schema.org JSON-LD format."""
    real_id = _resolve_batch_id(batch_id, organization_id)
    batch_dict = catalogue_store.get_batch(organization_id, real_id)
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
    # Look the queue up by the resolved id, not the alias the caller passed —
    # "latest" is never a key — and via the accessor that rebuilds from
    # Postgres, since the in-memory cache is empty after any redeploy. Both
    # bugs silently produced an audit export containing transformations but
    # no review decisions at all, which is the half that makes it an audit.
    queue = _get_review_queue(real_id, organization_id)

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
    elif format in ("schema_org", "jsonld"):
        content = export_schema_org_jsonld(enriched)
        return Response(
            content=content,
            media_type="application/ld+json",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}_schema_org.jsonld"'},
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
        content = export_audit_json(enriched, review_queue=queue, batch_id=real_id)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}_audit.json"'},
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format '{format}'")



# ---------------------------------------------------------------------------
# Pipeline Benchmark
# ---------------------------------------------------------------------------

@router.post("/batches/{batch_id}/benchmark")
@limiter.limit("6/minute")
def benchmark_batch(
    request: Request,
    batch_id: str,
    organization_id: str = Query(default="default"),
) -> dict[str, Any]:
    """Re-run the deterministic pipeline over this batch and time it for real.

    Every number returned here is measured during this request, not replayed
    from a previous run — including when the batch is one the caller uploaded
    themselves. The pipeline re-runs from the batch's persisted *raw* values,
    so it exercises the same code path as the original ingest rather than
    re-reading a cached result.

    Cost is genuinely $0: the deterministic path makes no external API calls
    at all (no LLM, no search). Only `live_fetch` ingestion hits a paid
    dependency, and this endpoint never invokes it.
    """
    real_id = _resolve_batch_id(batch_id, organization_id)
    stored = catalogue_store.get_batch(organization_id, real_id)
    if not stored or not stored.get("rows"):
        raise HTTPException(status_code=404, detail="Batch not found")

    source_rows = tuple(
        SourceRow(
            row_number=r["row_number"],
            source_name=stored["source_name"],
            source_fingerprint=r["source_fingerprint"],
            values=r["raw_values"],
        )
        for r in stored["rows"]
    )
    batch = CatalogueBatch(stored["source_name"], tuple(stored["columns"]), source_rows)

    # Stage 1 — enrichment (cleaning, LOV matching, UOM/material normalization)
    t0 = time.perf_counter()
    enriched = enrich_batch(batch, _reference_store)
    t_enrich = time.perf_counter() - t0

    # Stage 2 — deterministic validation & auto-approval routing
    t1 = time.perf_counter()
    validation = validate_batch(enriched)
    t_validate = time.perf_counter() - t1

    # Stage 3 — 252-column Unilog CX1 record synthesis (the real export path)
    t2 = time.perf_counter()
    for r in stored["rows"]:
        row_to_unilog_dict(*_unilog_args_from_raw(r["raw_values"]))
    t_synthesize = time.perf_counter() - t2

    total = t_enrich + t_validate + t_synthesize
    row_count = enriched.row_count

    return {
        "batch_id": real_id,
        "source_name": stored["source_name"],
        "row_count": row_count,
        "measured_at_request_time": True,
        "total_seconds": round(total, 4),
        "throughput_rows_per_sec": round(row_count / total) if total > 0 else 0,
        "stages": [
            {"name": "Enrich & normalize", "seconds": round(t_enrich, 4),
             "rows_per_sec": round(row_count / t_enrich) if t_enrich > 0 else 0},
            {"name": "Validate & route", "seconds": round(t_validate, 4),
             "rows_per_sec": round(row_count / t_validate) if t_validate > 0 else 0},
            {"name": "Synthesize 252 columns", "seconds": round(t_synthesize, 4),
             "rows_per_sec": round(row_count / t_synthesize) if t_synthesize > 0 else 0},
        ],
        "verified_rate": round(enriched.verified_rate, 4),
        "auto_approve_rate": round(validation.auto_approve_rate, 4),
        "auto_approve_count": validation.auto_approve_count,
        "review_required_count": validation.review_required_count,
        "total_issues": validation.total_issues,
        "external_api_calls": 0,
        "cost_usd": 0.0,
        "cost_note": "Deterministic path makes no LLM or search API calls.",
    }


# ---------------------------------------------------------------------------
# Ground-Truth Evaluation
# ---------------------------------------------------------------------------

# The self-generated benchmark pair shipped in the repo. This is *not*
# official Unilog ground truth — it is fictional data useful only for
# catching regressions in our own normalization logic, and every surface
# that reports it must say so.
_SYNTHETIC_BENCHMARK_INPUT = "data/ground_truth/synthetic_200_input.csv"
_SYNTHETIC_BENCHMARK_TRUTH = "data/ground_truth/synthetic_200_valves.csv"


@router.get("/evaluation/synthetic")
@limiter.limit("6/minute")
def evaluate_synthetic_benchmark(request: Request) -> dict[str, Any]:
    """Run the bundled 200-row synthetic benchmark and return real scores.

    Computed on request against the committed input/ground-truth pair, so
    the figures always reflect the pipeline as it currently stands. They
    were previously hardcoded in the dashboard and had silently drifted
    from what the pipeline actually scores.
    """
    input_path = Path(_SYNTHETIC_BENCHMARK_INPUT)
    truth_path = Path(_SYNTHETIC_BENCHMARK_TRUTH)
    if not input_path.exists() or not truth_path.exists():
        raise HTTPException(status_code=404, detail="Synthetic benchmark data not bundled")

    try:
        batch = read_catalogue(str(input_path))
        enriched = enrich_batch(batch, _reference_store)
        report = evaluate(enriched, load_ground_truth_csv(truth_path)).to_dict()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Benchmark evaluation failed: {exc}") from exc

    summary = report["summary"]
    return {
        "dataset": "self-generated 200-row synthetic benchmark",
        "is_official_unilog_ground_truth": False,
        "caveat": (
            "Fictional data generated by this project, not Unilog's. Useful "
            "for regression-checking our own normalization, not as evidence "
            "of accuracy on real catalogue data."
        ),
        "measured_at_request_time": True,
        "rows_evaluated": summary["ground_truth_rows"],
        "overall_exact_accuracy": summary["overall_exact_accuracy"],
        "complete_row_accuracy": summary["complete_row_accuracy"],
        "field_accuracy": {
            name: metrics["exact_accuracy"]
            for name, metrics in report["field_metrics"].items()
        },
    }

@router.post("/batches/{batch_id}/evaluate")
@limiter.limit("10/minute")
def evaluate_batch(
    request: Request,
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
