"""Field-level enrichment pipeline for ingested catalogue rows.

Every field passes through a deterministic pipeline:
  raw → clean → LOV match → UOM normalize → validate → status assign

Every transformation is recorded as evidence. No AI is used — this is
purely deterministic matching against the reference-data store.

Fields that cannot be matched are preserved as-is with status
``review_required`` and confidence 0.0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from .catalogue_ingestion import CatalogueBatch, SourceRow
from .reference_data import ReferenceStore, CanonicalMatch
from .uom import normalize_uom, normalize_material, NormalizedUOM, NormalizedMaterial, MATERIAL_CANONICAL


# -- Column role detection -------------------------------------------------

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
    "uom", "unit", "units", "unit_of_measure", "measure", "size_uom", "pressure_uom",
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
    "pressure", "pressure_rating", "pressure_class", "cwp", "wog",
    "working_pressure", "max_pressure",
})
_CONNECTION_TYPE_KEYS = frozenset({
    "connection_type", "connection", "end_connection", "ends", "joint",
})


PLACEHOLDER_VALUES = frozenset({
    "n/a", "na", "--", "---", "-", "null", "none", "n\\a", "n.a.", "n.a",
})


# Part number 3-letter prefix -> Canonical Manufacturer name
PART_NUMBER_MFR_PREFIXES: dict[str, str] = {
    "APO": "Apollo Valves",
    "BRA": "Bray International",
    "CAM": "Cameron (Schlumberger)",
    "CRA": "Crane Co.",
    "FLO": "Flowserve",
    "GRA": "Graco",
    "GRU": "Grundfos",
    "HON": "Honeywell",
    "ITT": "ITT Inc.",
    "KIT": "Kitz Corporation",
    "MIL": "Milwaukee Valve",
    "NIB": "Nibco",
    "PAR": "Parker Hannifin",
    "PEN": "Pentair",
    "SWA": "Swagelok",
    "VEL": "Velan",
    "VIC": "Victaulic",
    "WAT": "Watts Water Technologies",
    "XYL": "Xylem",
}

KNOWN_CONNECTION_TYPES = [
    "FNPT", "MNPT", "NPT", "Flanged", "Threaded", "Compression", "Solder", "BSP", "BSPT", "Socket Weld",
]


@dataclass(frozen=True)
class FieldEvidence:
    """Evidence for a single enrichment decision."""
    source_file: str
    source_row: int
    source_column: str
    raw_value: str | None
    transformation: str  # "exact_match", "alias_match", "normalized", "placeholder", "passthrough", "missing", "extracted_from_description", "extracted_from_part_number"


@dataclass(frozen=True)
class EnrichedField:
    """A single field after enrichment."""
    column: str
    raw_value: str | None
    canonical_value: str | None
    confidence: float
    status: str  # "verified", "inferred", "missing", "review_required"
    role: str  # "manufacturer", "brand", "material", "uom", "category", "part_number", "description", "size", "pressure", "connection_type", "other"
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
    reference_source: str = "seed"

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
    if column_key in _CONNECTION_TYPE_KEYS:
        return "connection_type"
    return "other"


# -- Status assignment logic -----------------------------------------------

_STATUS_PRIORITY = {"missing": 0, "review_required": 1, "inferred": 2, "verified": 3}


def _worst_status(statuses: Sequence[str]) -> str:
    """Return the worst (lowest-priority) status from a collection."""
    if not statuses:
        return "missing"
    return min(statuses, key=lambda s: _STATUS_PRIORITY.get(s, 1))


def _extract_from_part_number(
    column: str,
    role: str,
    part_number: str,
    source_name: str,
    row_number: int,
    store: ReferenceStore,
) -> EnrichedField | None:
    """Infer manufacturer or brand from part number prefix."""
    if not part_number or not part_number.strip():
        return None

    prefix = part_number.strip()[:3].upper()
    mfr_canonical = PART_NUMBER_MFR_PREFIXES.get(prefix)
    if not mfr_canonical:
        return None

    if role == "manufacturer":
        match = store.match_manufacturer(mfr_canonical)
        evidence = FieldEvidence(source_name, row_number, column, f"from SKU prefix: {prefix}", "extracted_from_part_number")
        return EnrichedField(column, None, match.canonical, 0.85, "inferred", role, evidence)

    return None


def _extract_from_description(
    column: str,
    role: str,
    description: str,
    source_name: str,
    row_number: int,
    store: ReferenceStore,
) -> EnrichedField | None:
    """Extract missing or placeholder attribute from description text."""
    if not description or not description.strip():
        return None

    desc = description.strip()

    if role == "manufacturer":
        match = store.match_manufacturer(desc)
        if match.confidence >= 0.80:
            evidence = FieldEvidence(source_name, row_number, column, f"from desc: {desc}", "extracted_from_description")
            return EnrichedField(column, None, match.canonical, match.confidence, "inferred", role, evidence)

    if role == "brand":
        match = store.match_brand(desc)
        if match.confidence >= 0.80:
            evidence = FieldEvidence(source_name, row_number, column, f"from desc: {desc}", "extracted_from_description")
            return EnrichedField(column, None, match.canonical, match.confidence, "inferred", role, evidence)

    if role == "material":
        sorted_keys = sorted(MATERIAL_CANONICAL.keys(), key=len, reverse=True)
        for key in sorted_keys:
            if re.search(r'\b' + re.escape(key) + r'\b', desc, re.IGNORECASE):
                canonical = MATERIAL_CANONICAL[key]
                evidence = FieldEvidence(source_name, row_number, column, f"from desc: {desc}", "extracted_from_description")
                return EnrichedField(column, None, canonical, 0.85, "inferred", role, evidence)

    if role == "pressure":
        if "uom" in column.lower():
            m = re.search(r'\b(\d+)\s*(psi|bar|wog|cwp|swp|kpa|mpa)\b', desc, re.IGNORECASE)
            if m:
                uom_canonical = normalize_uom(m.group(2)).canonical
                evidence = FieldEvidence(source_name, row_number, column, f"from desc: {desc}", "extracted_from_description")
                return EnrichedField(column, None, uom_canonical, 0.85, "inferred", role, evidence, uom_canonical)
        else:
            m = re.search(r'\b(\d+)\s*(?:psi|bar|wog|cwp|swp|kpa|mpa)\b', desc, re.IGNORECASE)
            if m:
                val = m.group(1)
                evidence = FieldEvidence(source_name, row_number, column, f"from desc: {desc}", "extracted_from_description")
                return EnrichedField(column, None, val, 0.85, "inferred", role, evidence)

    if role == "connection_type":
        for conn_type in KNOWN_CONNECTION_TYPES:
            if re.search(r'\b' + re.escape(conn_type) + r'\b', desc, re.IGNORECASE):
                evidence = FieldEvidence(source_name, row_number, column, f"from desc: {desc}", "extracted_from_description")
                return EnrichedField(column, None, conn_type, 0.85, "inferred", role, evidence)

    if role == "size":
        m = re.search(r'\b(\d+(?:[-/]\d+)?|\d+\.\d+)\s*(?:in|inch|inches|mm|cm)\b', desc, re.IGNORECASE)
        if m:
            val = m.group(1)
            evidence = FieldEvidence(source_name, row_number, column, f"from desc: {desc}", "extracted_from_description")
            return EnrichedField(column, None, val, 0.85, "inferred", role, evidence)

    if role == "uom":
        m = re.search(r'\b\d+(?:[-/]\d+)?\s*(in|inch|inches|mm|cm)\b', desc, re.IGNORECASE)
        if m:
            uom_canonical = normalize_uom(m.group(1)).canonical
            evidence = FieldEvidence(source_name, row_number, column, f"from desc: {desc}", "extracted_from_description")
            return EnrichedField(column, None, uom_canonical, 0.85, "inferred", role, evidence, uom_canonical)

    return None


def _enrich_field(
    column: str,
    raw_value: str | None,
    role: str,
    source_name: str,
    row_number: int,
    store: ReferenceStore,
    description: str | None = None,
    part_number: str | None = None,
) -> EnrichedField:
    """Enrich a single field based on its detected role."""
    base_evidence = FieldEvidence(source_name, row_number, column, raw_value, "passthrough")

    # Missing or placeholder values
    is_missing = raw_value is None or not raw_value.strip()
    is_placeholder = raw_value is not None and raw_value.strip().casefold() in PLACEHOLDER_VALUES

    if is_missing or is_placeholder:
        # Try extracting from part_number if manufacturer
        if part_number and role == "manufacturer":
            extracted = _extract_from_part_number(column, role, part_number, source_name, row_number, store)
            if extracted:
                return extracted

        # Try extracting from description if available
        if description:
            extracted = _extract_from_description(column, role, description, source_name, row_number, store)
            if extracted:
                return extracted

        evidence = FieldEvidence(source_name, row_number, column, raw_value, "missing" if is_missing else "placeholder")
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
        evidence = FieldEvidence(source_name, raw_value, column, raw_value, "passthrough")
        return EnrichedField(column, raw_value, raw_value, 0.0, "review_required", role, evidence)

    if role in {"part_number", "description"}:
        evidence = FieldEvidence(source_name, row_number, column, raw_value, "passthrough")
        return EnrichedField(column, raw_value, raw_value, 1.0, "verified", role, evidence)

    if role in {"size", "pressure", "connection_type"}:
        evidence = FieldEvidence(source_name, row_number, column, raw_value, "passthrough")
        return EnrichedField(column, raw_value, raw_value, 0.9, "verified", role, evidence)

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
    """Enrich every field in a CatalogueBatch using the reference store."""
    if store is None:
        store = ReferenceStore()

    column_roles = {col: detect_role(col) for col in batch.columns}

    enriched_rows: list[EnrichedRow] = []
    for source_row in batch.rows:
        description_text = None
        part_number_text = None
        for col, role in column_roles.items():
            if role == "description":
                description_text = source_row.values.get(col)
            elif role == "part_number":
                part_number_text = source_row.values.get(col)

        fields: list[EnrichedField] = []
        for column in batch.columns:
            raw_value = source_row.values.get(column)
            role = column_roles[column]
            enriched = _enrich_field(
                column, raw_value, role, batch.source_name, source_row.row_number, store,
                description_text, part_number_text
            )
            fields.append(enriched)

        statuses = [f.status for f in fields]
        confidences = [f.confidence for f in fields if f.raw_value is not None or f.canonical_value is not None]
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
    )
