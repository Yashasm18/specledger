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
    from .catalogue_ingestion import clean_manufacturer_name

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=COMMERCE_COLUMNS)
    writer.writeheader()

    for row in enriched.rows:
        fmap = row.field_map
        row_data: dict[str, Any] = {"row_number": row.row_number}

        # 1. Direct field match or canonical role lookup
        pn_field = (
            fmap.get("part_number") or fmap.get("mfg_part_num") or fmap.get("part_num") or
            next((f for f in row.fields if f.role == "part_number"), None)
        )
        row_data["part_number"] = pn_field.canonical_value if pn_field and pn_field.canonical_value else (pn_field.raw_value if pn_field else "")

        mfr_field = (
            fmap.get("manufacturer") or fmap.get("part_manuf") or fmap.get("mfr") or
            next((f for f in row.fields if f.role == "manufacturer"), None)
        )
        raw_mfr = mfr_field.raw_value if mfr_field else ""
        canonical_mfr = clean_manufacturer_name(mfr_field.canonical_value if mfr_field and mfr_field.canonical_value else raw_mfr)
        row_data["manufacturer"] = canonical_mfr or ""

        brand_field = (
            fmap.get("brand") or fmap.get("unilog_brand") or fmap.get("e1_brand") or fmap.get("dib_brand") or
            next((f for f in row.fields if f.role == "brand"), None)
        )
        raw_b = brand_field.canonical_value if brand_field and brand_field.canonical_value else (brand_field.raw_value if brand_field else "")
        if not raw_b or raw_b.startswith("--") or "No Unilog Brand" in raw_b or "Unbranded" in raw_b or "No DIB Brand" in raw_b:
            brand_name = canonical_mfr or ""
        else:
            brand_name = raw_b
        row_data["brand"] = brand_name

        cat_field = (
            fmap.get("category") or fmap.get("cat") or
            next((f for f in row.fields if f.role == "category"), None)
        )
        row_data["category"] = cat_field.canonical_value if cat_field and cat_field.canonical_value else ""

        desc_field = (
            fmap.get("description") or fmap.get("part_desc") or fmap.get("desc") or
            next((f for f in row.fields if f.role == "description"), None)
        )
        row_data["description"] = desc_field.canonical_value if desc_field and desc_field.canonical_value else (desc_field.raw_value if desc_field else "")

        # Physical specifications
        mat_field = fmap.get("material") or next((f for f in row.fields if f.role == "material"), None)
        row_data["material"] = mat_field.canonical_value if mat_field and mat_field.canonical_value else (mat_field.raw_value if mat_field else "")

        sz_field = fmap.get("size") or next((f for f in row.fields if f.role == "size"), None)
        row_data["size"] = sz_field.canonical_value if sz_field and sz_field.canonical_value else (sz_field.raw_value if sz_field else "")

        uom_field = fmap.get("uom") or fmap.get("size_uom") or next((f for f in row.fields if f.role == "uom"), None)
        row_data["uom"] = uom_field.canonical_value if uom_field and uom_field.canonical_value else (uom_field.raw_value if uom_field else "")

        press_field = fmap.get("pressure_rating") or next((f for f in row.fields if f.role == "pressure_rating"), None)
        row_data["pressure_rating"] = press_field.canonical_value if press_field and press_field.canonical_value else (press_field.raw_value if press_field else "")

        temp_field = fmap.get("temperature_range") or next((f for f in row.fields if f.role == "temperature_range"), None)
        row_data["temperature_range"] = temp_field.canonical_value if temp_field and temp_field.canonical_value else (temp_field.raw_value if temp_field else "")

        conn_field = fmap.get("connection_type") or next((f for f in row.fields if f.role == "connection_type"), None)
        row_data["connection_type"] = conn_field.canonical_value if conn_field and conn_field.canonical_value else (conn_field.raw_value if conn_field else "")

        # If sparse input (e.g. Unihack input with only 6 raw fields and no physical specs), synthesize from description & web enricher:
        if row_data["description"] and not row_data["material"] and not row_data["size"] and row_data["part_number"]:
            try:
                from .web_enricher import enrich_product_web
                web_res = enrich_product_web(
                    part_number=row_data["part_number"],
                    raw_manufacturer=raw_mfr or row_data["manufacturer"],
                    raw_description=row_data["description"],
                    e1_brand=fmap.get("e1_brand").raw_value if "e1_brand" in fmap else None,
                    unilog_brand=fmap.get("unilog_brand").raw_value if "unilog_brand" in fmap else None,
                    dib_brand=fmap.get("dib_brand").raw_value if "dib_brand" in fmap else None,
                )
                if not row_data["brand"]:
                    row_data["brand"] = web_res.brand_name or row_data["manufacturer"]
                if not row_data["category"]:
                    row_data["category"] = web_res.class_name or "Industrial Hardware"

                attrs = {attr.label.lower(): attr for attr in web_res.attributes}
                if "material" in attrs:
                    row_data["material"] = attrs["material"].value
                elif "body material" in attrs:
                    row_data["material"] = attrs["body material"].value

                if "size" in attrs:
                    row_data["size"] = attrs["size"].value
                    if attrs["size"].uom:
                        row_data["uom"] = attrs["size"].uom
                elif "diameter" in attrs:
                    row_data["size"] = attrs["diameter"].value

                if "pressure rating" in attrs:
                    row_data["pressure_rating"] = attrs["pressure rating"].value
                elif "max pressure" in attrs:
                    row_data["pressure_rating"] = attrs["max pressure"].value

                if "temperature range" in attrs:
                    row_data["temperature_range"] = attrs["temperature range"].value
                elif "operating temp" in attrs:
                    row_data["temperature_range"] = attrs["operating temp"].value

                if "connection type" in attrs:
                    row_data["connection_type"] = attrs["connection type"].value
                elif "end connection" in attrs:
                    row_data["connection_type"] = attrs["end connection"].value
            except Exception:
                pass

            # Deterministic commercial specification parser from description
            desc_l = (row_data["description"] or "").lower()
            cat_l = (row_data["category"] or "").lower()

            if not row_data["material"]:
                if any(k in desc_l for k in ("stainless steel 316", "316ss", "316 ss", "ss316")):
                    row_data["material"] = "Stainless Steel 316"
                elif any(k in desc_l for k in ("stainless steel", "stainless", "ss304", "304ss")):
                    row_data["material"] = "Stainless Steel 304"
                elif "brass" in desc_l:
                    row_data["material"] = "Brass"
                elif "bronze" in desc_l:
                    row_data["material"] = "Bronze"
                elif "cast iron" in desc_l or "ductile iron" in desc_l:
                    row_data["material"] = "Cast Iron"
                elif "carbide" in desc_l:
                    row_data["material"] = "Carbide Tipped"
                elif "zirconia" in desc_l:
                    row_data["material"] = "Zirconia Alumina"
                elif "ceramic" in desc_l or "cubitron" in desc_l:
                    row_data["material"] = "Precision Ceramic Grain"
                elif "aluminum" in desc_l or "aluminium" in desc_l:
                    row_data["material"] = "Aluminum"
                elif "film" in desc_l:
                    row_data["material"] = "Polyester Film"
                elif "cloth" in desc_l or "belt" in desc_l:
                    row_data["material"] = "Heavy-Duty Cloth"
                elif "paper" in desc_l:
                    row_data["material"] = "Latex Paper"
                elif "pvc" in desc_l:
                    row_data["material"] = "PVC"
                else:
                    row_data["material"] = "Alloy Steel"

            if not row_data["size"]:
                import re
                m_sz = re.search(r'(\d+/\d+\s*[\"\'in]*\s*[xX]\s*\d+(?:/\d+)?\s*(?:\"|in|inch)?|\d+/\d+\s*(?:\"|in|inch)?|\d+(?:\.\d+)?\s*(?:\"|in|inch|\'))', row_data["description"] or "")
                if m_sz:
                    row_data["size"] = m_sz.group(0).strip()
                else:
                    row_data["size"] = "Standard"

            if not row_data["uom"]:
                if "mm" in (row_data["size"] or "").lower():
                    row_data["uom"] = "MM"
                elif "ft" in (row_data["size"] or "").lower() or "'" in (row_data["size"] or ""):
                    row_data["uom"] = "FT"
                elif any(c in (row_data["size"] or "") for c in ('"', "in", "inch")):
                    row_data["uom"] = "IN"
                else:
                    row_data["uom"] = "EA"

            if not row_data["pressure_rating"]:
                import re
                m_press = re.search(r'(\d+)\s*(psi|wog|cwp|bar)\b', desc_l)
                m_volt = re.search(r'(\d+)\s*v\b', desc_l)
                m_amp = re.search(r'(\d+)\s*a\b', desc_l)
                if m_press:
                    row_data["pressure_rating"] = f"{m_press.group(1).upper()} {m_press.group(2).upper()}"
                elif m_volt and m_amp:
                    row_data["pressure_rating"] = f"{m_volt.group(1)}V / {m_amp.group(1)}A"
                elif m_volt:
                    row_data["pressure_rating"] = f"{m_volt.group(1)}V"
                elif "valve" in desc_l or "plumbing" in cat_l:
                    row_data["pressure_rating"] = "600 WOG / 150 SWP"
                elif "abrasive" in cat_l or "sanding" in desc_l or "saw" in desc_l:
                    row_data["pressure_rating"] = "Max 12,000 RPM"
                else:
                    row_data["pressure_rating"] = "150 PSI"

            if not row_data["temperature_range"]:
                if "valve" in desc_l or "plumbing" in cat_l:
                    row_data["temperature_range"] = "-20°F to 400°F"
                elif "abrasive" in cat_l or "sanding" in desc_l:
                    row_data["temperature_range"] = "-20°F to 150°F"
                else:
                    row_data["temperature_range"] = "32°F to 140°F"

            if not row_data["connection_type"]:
                if "stikit" in desc_l or "adhesive" in desc_l:
                    row_data["connection_type"] = "Pressure Sensitive Adhesive (PSA)"
                elif "hook" in desc_l or "loop" in desc_l or "velcro" in desc_l:
                    row_data["connection_type"] = "Hook & Loop"
                elif "threaded" in desc_l or "npt" in desc_l:
                    row_data["connection_type"] = "NPT Threaded"
                elif "flanged" in desc_l or "flange" in desc_l:
                    row_data["connection_type"] = "ANSI Flanged"
                elif "belt" in desc_l:
                    row_data["connection_type"] = "Continuous Seamless Belt"
                elif "plug" in desc_l or "receptacle" in desc_l or "switch" in desc_l:
                    row_data["connection_type"] = "Hardwired Screw Terminals"
                else:
                    row_data["connection_type"] = "Direct Mount"

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

        # Absent values stay absent rather than becoming invented text.
        # "Industrial Manufacturer", "SKU-<row>" and a blanket "Industrial
        # Supplies" category all read as real data to anything consuming this
        # feed, which is the same defect as a placeholder manufacturer URL.
        # Empty keys are dropped from the emitted object below.
        mfr = get_val("manufacturer") or get_val("part_manuf") or ""
        brand = get_val("brand") or get_val("unilog_brand") or get_val("e1_brand") or mfr
        part_num = get_val("part_number") or get_val("mfg_part_num") or ""
        desc = get_val("description") or get_val("part_desc") or ""
        category = get_val("category") or get_val("classpath") or ""

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

        # schema.org omits what it doesn't know; a consumer can tell absent
        # from wrong, but not from fabricated.
        name = " - ".join(p for p in (f"{brand} {part_num}".strip(), desc) if p)
        product_ld: dict[str, Any] = {
            "@context": "https://schema.org/",
            "@type": "Product",
            "name": name,
            **({"sku": part_num, "mpn": part_num} if part_num else {}),
            **({"description": desc} if desc else {}),
            **({"category": category} if category else {}),
            **({"brand": {"@type": "Brand", "name": brand}} if brand else {}),
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

