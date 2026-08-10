"""Field-level enrichment pipeline for ingested catalogue rows.

Every field passes through a deterministic pipeline:
  raw → clean → LOV match → UOM normalize → validate → status assign

Every transformation is recorded as evidence. No AI is used — this is
purely deterministic matching against the reference-data store.

Fields that cannot be matched are preserved as-is with status
``review_required`` and confidence 0.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .catalogue_ingestion import CatalogueBatch, SourceRow
from .reference_data import ReferenceStore, CanonicalMatch
from .uom import normalize_uom, normalize_material, NormalizedUOM, NormalizedMaterial


# -- Column role detection -------------------------------------------------
# Maps canonical column keys to their semantic role so the enrichment
# pipeline knows which LOV to match against.

_MANUFACTURER_KEYS = frozenset({
    "manufacturer", "mfr", "mfg", "manufacturer_name", "mfr_name", "mfg_name",
    "vendor", "supplier", "brand_manufacturer",
})
_BRAND_KEYS = frozenset({
    "brand", "brand_name", "product_brand", "trade_name",
})
_MATERIAL_KEYS = frozenset({
    "material", "body_material", "construction", "material_type", "mat",
    "shell_material", "seat_material", "trim_material",
})
_UOM_KEYS = frozenset({
    "uom", "unit", "units", "unit_of_measure", "measure",
})
_CATEGORY_KEYS = frozenset({
    "category", "product_category", "type", "product_type", "class",
    "sub_category", "subcategory",
})
_PART_NUMBER_KEYS = frozenset({
    "part_number", "part_num", "part_no", "mfg_part_num", "mfr_part_num",
    "sku", "item_number", "item_num", "item_no", "catalog_number",
    "cat_no", "model", "model_number", "model_num",
})
_DESCRIPTION_KEYS = frozenset({
    "description", "desc", "part_desc", "product_description", "item_description",
    "short_description", "long_description", "product_name", "name", "title",
})
_SIZE_KEYS = frozenset({
    "size", "pipe_size", "nominal_size", "diameter", "dia", "dn", "nps",
})
_PRESSURE_KEYS = frozenset({
    "pressure", "pressure_rating", "pressure_class", "class", "cwp", "wog",
    "working_pressure", "max_pressure",
})


@dataclass(frozen=True)
class FieldEvidence:
    """Evidence for a single enrichment decision."""
    source_file: str
    source_row: int
    source_column: str
    raw_value: str | None
    transformation: str  # "exact_match", "alias_match", "normalized", "placeholder", "passthrough", "missing"


@dataclass(frozen=True)
class EnrichedField:
    """A single field after enrichment."""
    column: str
    raw_value: str | None
    canonical_value: str | None
    confidence: float
    status: str  # "verified", "inferred", "missing", "review_required"
    role: str  # "manufacturer", "brand", "material", "uom", "category", "part_number", "description", "size", "pressure", "other"
    evidence: FieldEvidence
    normalized_unit: str | None = None


@dataclass(frozen=True)
class EnrichedRow:
    """A complete row with per-field enrichment results."""
    row_number: int
    source_name: str
    source_fingerprint: str
    fields: tuple[EnrichedField, ...]
    overall_confidence: float
    overall_status: str  # worst-case status across fields

    @property
    def field_map(self) -> dict[str, EnrichedField]:
        return {f.column: f for f in self.fields}

    @property
    def verified_count(self) -> int:
        return sum(1 for f in self.fields if f.status == "verified")

    @property
    def review_count(self) -> int:
        return sum(1 for f in self.fields if f.status == "review_required")


@dataclass(frozen=True)
class EnrichedBatch:
    """A complete batch with per-row enrichment results."""
    source_name: str
    columns: tuple[str, ...]
    rows: tuple[EnrichedRow, ...]
    reference_source: str  # "seed", "file:...", etc.

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def total_fields(self) -> int:
        return sum(len(row.fields) for row in self.rows)

    @property
    def verified_rate(self) -> float:
        total = self.total_fields
        if total == 0:
            return 0.0
        verified = sum(row.verified_count for row in self.rows)
        return verified / total


def detect_role(column_key: str) -> str:
    """Detect the semantic role of a column based on its normalized key."""
    if column_key in _MANUFACTURER_KEYS:
        return "manufacturer"
    if column_key in _BRAND_KEYS:
        return "brand"
    if column_key in _MATERIAL_KEYS:
        return "material"
    if column_key in _UOM_KEYS:
        return "uom"
    if column_key in _CATEGORY_KEYS:
        return "category"
    if column_key in _PART_NUMBER_KEYS:
        return "part_number"
    if column_key in _DESCRIPTION_KEYS:
        return "description"
    if column_key in _SIZE_KEYS:
        return "size"
    if column_key in _PRESSURE_KEYS:
        return "pressure"
    return "other"


# -- Status assignment logic -----------------------------------------------

_STATUS_PRIORITY = {"missing": 0, "review_required": 1, "inferred": 2, "verified": 3}


def _worst_status(statuses: Sequence[str]) -> str:
    """Return the worst (lowest-priority) status from a collection."""
    if not statuses:
        return "missing"
    return min(statuses, key=lambda s: _STATUS_PRIORITY.get(s, 1))


def _enrich_field(
    column: str,
    raw_value: str | None,
    role: str,
    source_name: str,
    row_number: int,
    store: ReferenceStore,
) -> EnrichedField:
    """Enrich a single field based on its detected role."""
    base_evidence = FieldEvidence(source_name, row_number, column, raw_value, "passthrough")

    # Missing or None values
    if raw_value is None or not raw_value.strip():
        evidence = FieldEvidence(source_name, row_number, column, raw_value, "missing")
        return EnrichedField(column, raw_value, None, 0.0, "missing", role, evidence)

    # Role-specific enrichment
    if role == "manufacturer":
        match = store.match_manufacturer(raw_value)
        return _from_canonical_match(column, raw_value, match, role, source_name, row_number)

    if role == "brand":
        match = store.match_brand(raw_value)
        return _from_canonical_match(column, raw_value, match, role, source_name, row_number)

    if role == "category":
        match = store.match_category(raw_value)
        return _from_canonical_match(column, raw_value, match, role, source_name, row_number)

    if role == "material":
        mat = normalize_material(raw_value)
        if mat.confidence >= 0.9:
            evidence = FieldEvidence(source_name, row_number, column, raw_value, "exact_match")
            return EnrichedField(column, raw_value, mat.canonical, mat.confidence, "verified", role, evidence)
        if mat.confidence > 0:
            evidence = FieldEvidence(source_name, row_number, column, raw_value, "normalized")
            return EnrichedField(column, raw_value, mat.canonical, mat.confidence, "inferred", role, evidence)
        evidence = FieldEvidence(source_name, row_number, column, raw_value, "passthrough")
        return EnrichedField(column, raw_value, raw_value, 0.0, "review_required", role, evidence)

    if role == "uom":
        uom = normalize_uom(raw_value)
        if uom.recognized:
            evidence = FieldEvidence(source_name, row_number, column, raw_value, "exact_match")
            return EnrichedField(column, raw_value, uom.canonical, uom.confidence, "verified", role, evidence, uom.canonical)
        evidence = FieldEvidence(source_name, row_number, column, raw_value, "passthrough")
        return EnrichedField(column, raw_value, raw_value, 0.0, "review_required", role, evidence)

    # For part_number, description, size, pressure, and other — pass through
    # These are preserved as-is; the values are not LOV-constrained.
    if role in {"part_number", "description"}:
        evidence = FieldEvidence(source_name, row_number, column, raw_value, "passthrough")
        return EnrichedField(column, raw_value, raw_value, 1.0, "verified", role, evidence)

    # Size and pressure: pass through with verified status (they have their
    # own extraction-time normalization in extraction.py)
    if role in {"size", "pressure"}:
        evidence = FieldEvidence(source_name, row_number, column, raw_value, "passthrough")
        return EnrichedField(column, raw_value, raw_value, 0.9, "verified", role, evidence)

    # Other / unknown columns
    evidence = FieldEvidence(source_name, row_number, column, raw_value, "passthrough")
    return EnrichedField(column, raw_value, raw_value, 0.5, "review_required", role, evidence)


def _from_canonical_match(
    column: str,
    raw_value: str,
    match: CanonicalMatch,
    role: str,
    source_name: str,
    row_number: int,
) -> EnrichedField:
    """Convert a CanonicalMatch to an EnrichedField."""
    if match.confidence >= 0.95:
        evidence = FieldEvidence(source_name, row_number, column, raw_value,
                                 "exact_match" if match.match_type == "exact" else "alias_match")
        return EnrichedField(column, raw_value, match.canonical, match.confidence, "verified", role, evidence)
    if match.confidence > 0:
        evidence = FieldEvidence(source_name, row_number, column, raw_value, "normalized")
        return EnrichedField(column, raw_value, match.canonical, match.confidence, "inferred", role, evidence)
    evidence = FieldEvidence(source_name, row_number, column, raw_value, "passthrough")
    return EnrichedField(column, raw_value, raw_value, 0.0, "review_required", role, evidence)


def enrich_batch(batch: CatalogueBatch, store: ReferenceStore | None = None) -> EnrichedBatch:
    """Enrich every field in a CatalogueBatch using the reference store.

    If no store is provided, a default store with seed data is created.
    """
    if store is None:
        store = ReferenceStore()

    column_roles = {col: detect_role(col) for col in batch.columns}

    enriched_rows: list[EnrichedRow] = []
    for source_row in batch.rows:
        fields: list[EnrichedField] = []
        for column in batch.columns:
            raw_value = source_row.values.get(column)
            role = column_roles[column]
            enriched = _enrich_field(column, raw_value, role, batch.source_name, source_row.row_number, store)
            fields.append(enriched)

        statuses = [f.status for f in fields]
        confidences = [f.confidence for f in fields if f.raw_value is not None]
        overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        overall_status = _worst_status(statuses)

        enriched_rows.append(EnrichedRow(
            source_row.row_number,
            source_row.source_name,
            source_row.source_fingerprint,
            tuple(fields),
            round(overall_confidence, 4),
            overall_status,
        ))

    return EnrichedBatch(
        batch.source_name,
        batch.columns,
        tuple(enriched_rows),
        "seed",
    )
