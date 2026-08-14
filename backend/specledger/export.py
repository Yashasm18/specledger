"""Export enriched catalogue data in commerce-ready formats.

Supports:
  - CSV: flat enriched rows with raw + canonical columns
  - JSON: structured with evidence and confidence metadata
  - Excel: formatted workbook with color-coded confidence
  - Audit: full transformation history per row

Designed to produce output directly importable by PIM, ERP, and
commerce platforms.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from .enrichment import EnrichedBatch
from .human_review import ReviewQueue
from .validation_engine import BatchValidationResult


# ---------------------------------------------------------------------------
# Export configuration
# ---------------------------------------------------------------------------

# Standard commerce output columns (in order)
COMMERCE_COLUMNS = [
    "row_number",
    "manufacturer",
    "brand",
    "part_number",
    "category",
    "description",
    "material",
    "size",
    "uom",
    "pressure_rating",
    "temperature_range",
    "connection_type",
]

# Status display labels
STATUS_LABELS = {
    "verified": "✓ Verified",
    "inferred": "⚠ Inferred",
    "review_required": "⚑ Review Required",
    "missing": "✗ Missing",
}


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def export_csv(
    enriched: EnrichedBatch,
    include_raw: bool = True,
    include_confidence: bool = True,
    include_status: bool = True,
) -> str:
    """Export enriched batch as CSV string.

    Columns: row_number, then for each field:
      - {field}_raw (if include_raw)
      - {field}_canonical
      - {field}_confidence (if include_confidence)
      - {field}_status (if include_status)
    """
    output = io.StringIO()

    # Collect all unique field columns across rows
    all_columns: list[str] = []
    seen: set[str] = set()
    for row in enriched.rows:
        for field in row.fields:
            if field.column not in seen:
                all_columns.append(field.column)
                seen.add(field.column)

    # Build header
    header = ["row_number"]
    for col in all_columns:
        if include_raw:
            header.append(f"{col}_raw")
        header.append(f"{col}_canonical")
        if include_confidence:
            header.append(f"{col}_confidence")
        if include_status:
            header.append(f"{col}_status")

    writer = csv.DictWriter(output, fieldnames=header)
    writer.writeheader()

    for row in enriched.rows:
        row_data: dict[str, Any] = {"row_number": row.row_number}
        field_map = row.field_map
        for col in all_columns:
            field = field_map.get(col)
            if field:
                if include_raw:
                    row_data[f"{col}_raw"] = field.raw_value or ""
                row_data[f"{col}_canonical"] = field.canonical_value or ""
                if include_confidence:
                    row_data[f"{col}_confidence"] = f"{field.confidence:.2f}"
                if include_status:
                    row_data[f"{col}_status"] = field.status
            else:
                if include_raw:
                    row_data[f"{col}_raw"] = ""
                row_data[f"{col}_canonical"] = ""
                if include_confidence:
                    row_data[f"{col}_confidence"] = ""
                if include_status:
                    row_data[f"{col}_status"] = ""
        writer.writerow(row_data)

    return output.getvalue()


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def export_json(
    enriched: EnrichedBatch,
    include_evidence: bool = True,
    validation: BatchValidationResult | None = None,
    review_queue: ReviewQueue | None = None,
    indent: int = 2,
) -> str:
    """Export enriched batch as structured JSON.

    Includes full field metadata, evidence, and optional validation
    and review state.
    """
    rows_data: list[dict] = []
    for row in enriched.rows:
        row_data: dict[str, Any] = {
            "row_number": row.row_number,
            "overall_status": row.overall_status,
            "overall_confidence": round(row.overall_confidence, 4),
            "fields": {},
        }
        for field in row.fields:
            field_data: dict[str, Any] = {
                "raw_value": field.raw_value,
                "canonical_value": field.canonical_value,
                "confidence": field.confidence,
                "status": field.status,
                "role": field.role,
            }
            if include_evidence and field.evidence:
                field_data["evidence"] = {
                    "source_file": field.evidence.source_file,
                    "source_row": field.evidence.source_row,
                    "source_column": field.evidence.source_column,
                    "raw_value": field.evidence.raw_value,
                }
            row_data["fields"][field.column] = field_data

        # Add review state if available
        if review_queue:
            reviewable = review_queue.get_row(enriched.batch_id if hasattr(enriched, "batch_id") else "", row.row_number)
            if reviewable:
                row_data["review_state"] = reviewable.state.value

        rows_data.append(row_data)

    output = {
        "batch": {
            "source_file": enriched.source_name,
            "row_count": enriched.row_count,
            "verified_rate": round(enriched.verified_rate, 4),
        },
        "rows": rows_data,
    }

    if validation:
        output["validation"] = {
            "auto_approve_count": validation.auto_approve_count,
            "review_required_count": validation.review_required_count,
            "total_issues": validation.total_issues,
        }

    return json.dumps(output, indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Commerce-ready flat export
# ---------------------------------------------------------------------------

def export_commerce_csv(enriched: EnrichedBatch) -> str:
    """Export as a flat commerce-ready CSV with only canonical values.

    This format is designed for direct import into PIM/ERP systems.
    Only includes fields from the standard commerce column set.
    """
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=COMMERCE_COLUMNS)
    writer.writeheader()

    for row in enriched.rows:
        field_map = row.field_map
        row_data: dict[str, Any] = {"row_number": row.row_number}
        for col in COMMERCE_COLUMNS:
            if col == "row_number":
                continue
            field = field_map.get(col)
            row_data[col] = field.canonical_value if field and field.canonical_value else ""
        writer.writerow(row_data)

    return output.getvalue()


# ---------------------------------------------------------------------------
# Audit export
# ---------------------------------------------------------------------------

def export_audit_json(
    enriched: EnrichedBatch,
    review_queue: ReviewQueue | None = None,
    batch_id: str = "",
    indent: int = 2,
) -> str:
    """Export full audit trail showing the transformation history.

    For each row and field, shows:
    - Original supplier value
    - Enrichment transformation applied
    - Canonical value produced
    - Confidence and status
    - Evidence source
    - Review decision (if available)
    """
    audit_rows: list[dict] = []
    for row in enriched.rows:
        transformations: list[dict] = []
        for field in row.fields:
            transform: dict[str, Any] = {
                "field": field.column,
                "role": field.role,
                "supplier_value": field.raw_value,
                "canonical_value": field.canonical_value,
                "was_transformed": field.raw_value != field.canonical_value if field.raw_value and field.canonical_value else False,
                "confidence": field.confidence,
                "status": field.status,
            }
            if field.evidence:
                transform["evidence"] = {
                    "source_file": field.evidence.source_file,
                    "source_row": field.evidence.source_row,
                    "source_column": field.evidence.source_column,
                }
            transformations.append(transform)

        row_audit: dict[str, Any] = {
            "row_number": row.row_number,
            "overall_status": row.overall_status,
            "transformations": transformations,
        }

        # Add review decision if available
        if review_queue and batch_id:
            reviewable = review_queue.get_row(batch_id, row.row_number)
            if reviewable:
                row_audit["review"] = {
                    "state": reviewable.state.value,
                    "audit_trail": [e.to_dict() for e in reviewable.audit_trail],
                }

        audit_rows.append(row_audit)

    output = {
        "export_type": "audit",
        "batch_id": batch_id,
        "row_count": len(audit_rows),
        "rows": audit_rows,
    }
    return json.dumps(output, indent=indent, ensure_ascii=False)


def export_unilog_template(enriched: EnrichedBatch) -> str:
    """Export enriched batch in Unilog's official 252-column CSV template format."""
    from .unilog_exporter import export_unilog_csv
    return export_unilog_csv(enriched)


# ---------------------------------------------------------------------------
# schema.org / Product JSON-LD export (Standard E-Commerce Structured Data)
# ---------------------------------------------------------------------------

def export_schema_org_jsonld(enriched: EnrichedBatch, indent: int = 2) -> str:
    """Export enriched batch as standard schema.org/Product JSON-LD graph.

    Complies with schema.org Product, Brand, Organization, and PropertyValue
    international standards for e-commerce search indexing and PIM syndication.
    """
    products: list[dict[str, Any]] = []

    for row in enriched.rows:
        field_map = row.field_map

        def get_val(col_name: str) -> str | None:
            f = field_map.get(col_name)
            return f.canonical_value if f and f.canonical_value else None

        mfr = get_val("manufacturer") or get_val("part_manuf") or "Industrial Manufacturer"
        brand = get_val("brand") or get_val("unilog_brand") or get_val("e1_brand") or mfr
        part_num = get_val("part_number") or get_val("mfg_part_num") or f"SKU-{row.row_number}"
        desc = get_val("description") or get_val("part_desc") or f"{mfr} {part_num}"
        category = get_val("category") or get_val("classpath") or "Industrial Supplies"

        # Build additionalProperty array conforming to schema.org/PropertyValue
        additional_props: list[dict[str, Any]] = []
        for prop_key, label, uom_key in [
            ("material", "Body Material", None),
            ("size", "Nominal Size", "uom"),
            ("pressure_rating", "Pressure Rating", None),
            ("temperature_range", "Temperature Range", None),
            ("connection_type", "Connection Type", None),
        ]:
            val = get_val(prop_key)
            if val:
                prop_dict: dict[str, Any] = {
                    "@type": "PropertyValue",
                    "name": label,
                    "value": val,
                }
                if uom_key:
                    uom_val = get_val(uom_key)
                    if uom_val:
                        prop_dict["unitText"] = uom_val
                additional_props.append(prop_dict)

        product_ld: dict[str, Any] = {
            "@context": "https://schema.org/",
            "@type": "Product",
            "name": f"{brand} {part_num} - {desc}".strip(),
            "sku": part_num,
            "mpn": part_num,
            "description": desc,
            "category": category,
            "brand": {
                "@type": "Brand",
                "name": brand,
            },
            "manufacturer": {
                "@type": "Organization",
                "name": mfr,
            },
        }

        if additional_props:
            product_ld["additionalProperty"] = additional_props

        products.append(product_ld)

    graph_output = {
        "@context": "https://schema.org/",
        "@graph": products,
    }
    return json.dumps(graph_output, indent=indent, ensure_ascii=False)

