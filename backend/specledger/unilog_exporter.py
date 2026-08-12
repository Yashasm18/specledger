"""Unilog 252-Column Template Exporter for SpecLedger.

Exports enriched batch records into Unilog's official delivery format
matching ``Unihack_ Expected Output - Delivery Format.csv`` (252 columns exact).

Column Structure:
  - Source & Reference URLs (MFR URL, Ref URL 1-5)
  - Identity & Classification (PART_NUMBER, Dept, Class, Fine, Classpath, etc.)
  - Descriptions (6 levels: MOBILE_DESC, SHORT_DESC, LONG_DESC1, RETAIL_DESC, MARKETING_DESCRIPTION, etc.)
  - Feature Bullet Slots (ITEM_FEATURES_1 to 20)
  - Dynamic Attribute Triplets (ATTRIBUTE_LABEL/VALUE/UOM 1 to 50)
  - Physical Dimensions & Commercial Metadata (LENGTH, WIDTH, HEIGHT, WEIGHT, VOLUME + UOMs, UPC, EAN, GTIN, UNSPSC, Warranty)
  - Media & Documentation Links (Product Image, Alt Images 1-4, SDS, Spec Sheet, Manuals, Video Links)
"""

from __future__ import annotations

import csv
import io
from typing import Any, Mapping

from .catalogue_ingestion import CatalogueBatch, clean_manufacturer_name
from .enrichment import EnrichedBatch
from .web_enricher import enrich_product_web, WebEnrichmentResult


UNILOG_252_HEADERS: list[str] = [
    'MFR URL', 'Ref URL 1', 'Ref URL 2', 'Ref URL 3', 'Ref URL 4', 'Ref URL 5',
    'PART_NUMBER', 'Dept', 'Class', 'Fine', 'SKU - MY_PART_NUMBER', 'Mfg_Part_Num',
    'Part_Desc', 'E1_Brand', 'Unilog_Brand', 'DIB_Brand', 'Part_Manuf',
    'MANUFACTURER_NAME', 'BRAND_NAME', 'TRADE_NAME', 'MANUFACTURER_PART_NUMBER',
    'ALTERNATE_PART_NUMBER', 'Classpath', 'MOBILE_DESC', 'INVOICE_DESC', 'SHORT_DESC',
    'LONG_DESC1', 'RETAIL_DESC', 'MARKETING_DESCRIPTION',
    'ITEM_FEATURES_1', 'ITEM_FEATURES_2', 'ITEM_FEATURES_3', 'ITEM_FEATURES_4', 'ITEM_FEATURES_5',
    'ITEM_FEATURES_6', 'ITEM_FEATURES_7', 'ITEM_FEATURES_8', 'ITEM_FEATURES_9', 'ITEM_FEATURES_10',
    'ITEM_FEATURES_11', 'ITEM_FEATURES_12', 'ITEM_FEATURES_13', 'ITEM_FEATURES_14', 'ITEM_FEATURES_15',
    'ITEM_FEATURES_16', 'ITEM_FEATURES_17', 'ITEM_FEATURES_18', 'ITEM_FEATURES_19', 'ITEM_FEATURES_20',
    'With', 'Standard/Approvals', 'Prop 65', 'Application', 'Includes', 'Product Name',
]

# Add ATTRIBUTE_LABEL 1..50, ATTRIBUTE_VALUE 1..50, ATTRIBUTE_UOM 1..50
for i in range(1, 51):
    UNILOG_252_HEADERS.extend([
        f'ATTRIBUTE_LABEL {i}',
        f'ATTRIBUTE_VALUE {i}',
        f'ATTRIBUTE_UOM {i}',
    ])

# Add commercial, physical, media & document headers
UNILOG_252_HEADERS.extend([
    'UPC', 'EAN', 'GTIN', 'UNSPSC', 'Warranty', 'List Price', 'Selling Qty', 'Selling UOM',
    'Standard Packaging Information', 'LENGTH', 'LENGTH_UOM', 'HEIGHT', 'HEIGHT_UOM',
    'WIDTH', 'WIDTH_UOM', 'WEIGHT', 'WEIGHT_UOM', 'VOLUME', 'VOLUME_UOM',
    'Product Image', 'Alternate Image 1', 'Alternate Image 2', 'Alternate Image 3', 'Alternate Image 4',
    'SDS', 'SDS_1', 'Warranty Information', 'Catalog', 'Specification Sheet',
    'Instruction/Installation Manual', 'Service Manual', 'Owners/User Manual', 'Line Drawing',
    'MTR', 'RoHS', 'Full Engineering Drawing', 'Energy Star Guide', 'Technical Bulletin',
    'Submittal', 'Compatibility Chart', 'Size Chart', 'Product Label/Insert',
    'Video Link', 'Video Link 1', 'Country Of Origin', 'Discontinued', 'Actual Image (Yes/No)',
])


def row_to_unilog_dict(
    part_number: str,
    raw_manufacturer: str | None,
    raw_description: str | None,
    e1_brand: str | None = None,
    unilog_brand: str | None = None,
    dib_brand: str | None = None,
    enriched_fields: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Convert a single product record into a full 252-column Unilog row dict."""
    web_res: WebEnrichmentResult = enrich_product_web(
        part_number=part_number,
        raw_manufacturer=raw_manufacturer,
        raw_description=raw_description,
        e1_brand=e1_brand,
        unilog_brand=unilog_brand,
        dib_brand=dib_brand,
    )

    row: dict[str, str] = {header: "" for header in UNILOG_252_HEADERS}

    # URLs
    row['MFR URL'] = web_res.mfr_url or ""
    for idx, ref_url in enumerate(web_res.ref_urls[:5], start=1):
        row[f'Ref URL {idx}'] = ref_url

    # Identity & Input fields
    pn = web_res.part_number or part_number or ""
    mfr_name = web_res.manufacturer_clean or clean_manufacturer_name(raw_manufacturer) or ""
    brand = web_res.brand_name or mfr_name

    row['PART_NUMBER'] = pn
    row['Mfg_Part_Num'] = part_number or pn
    row['SKU - MY_PART_NUMBER'] = pn
    row['Part_Desc'] = raw_description or ""
    row['E1_Brand'] = e1_brand or "-- Unbranded --"
    row['Unilog_Brand'] = unilog_brand or "-- No Unilog Brand --"
    row['DIB_Brand'] = dib_brand or "-- No DIB Brand --"
    row['Part_Manuf'] = raw_manufacturer or mfr_name
    row['MANUFACTURER_NAME'] = mfr_name
    row['BRAND_NAME'] = brand
    row['TRADE_NAME'] = web_res.trade_name or f"{brand}®"
    row['MANUFACTURER_PART_NUMBER'] = pn
    row['Product Name'] = f"{brand} {pn}"

    # Classification
    row['Dept'] = web_res.dept or ""
    row['Class'] = web_res.class_name or ""
    row['Fine'] = web_res.fine or ""
    row['Classpath'] = web_res.classpath or ""

    # Descriptions
    row['MOBILE_DESC'] = web_res.mobile_desc or ""
    row['INVOICE_DESC'] = web_res.invoice_desc or ""
    row['SHORT_DESC'] = web_res.short_desc or ""
    row['LONG_DESC1'] = web_res.long_desc1 or ""
    row['RETAIL_DESC'] = web_res.retail_desc or ""
    row['MARKETING_DESCRIPTION'] = web_res.marketing_desc or ""

    # Features (up to 20)
    for idx, feature in enumerate(web_res.features[:20], start=1):
        row[f'ITEM_FEATURES_{idx}'] = feature

    # Standards
    row['Standard/Approvals'] = web_res.standards_approvals or ""

    # Dynamic Attributes (up to 50 triplets)
    for idx, attr in enumerate(web_res.attributes[:50], start=1):
        row[f'ATTRIBUTE_LABEL {idx}'] = attr.label
        row[f'ATTRIBUTE_VALUE {idx}'] = attr.value
        row[f'ATTRIBUTE_UOM {idx}'] = attr.uom or ""

    # Physical Dimensions & Commercial
    row['LENGTH'] = web_res.length or ""
    row['LENGTH_UOM'] = web_res.length_uom or ""
    row['HEIGHT'] = web_res.height or ""
    row['HEIGHT_UOM'] = web_res.height_uom or ""
    row['WIDTH'] = web_res.width or ""
    row['WIDTH_UOM'] = web_res.width_uom or ""
    row['WEIGHT'] = web_res.weight or ""
    row['WEIGHT_UOM'] = web_res.weight_uom or ""
    row['Warranty'] = web_res.warranty or ""

    # Media & Documents
    row['Product Image'] = web_res.product_image or ""
    row['Specification Sheet'] = web_res.spec_sheet_url or ""
    row['Actual Image (Yes/No)'] = web_res.actual_image

    return row


def export_unilog_csv(batch: CatalogueBatch | EnrichedBatch) -> str:
    """Export a batch to Unilog's exact 252-column CSV format."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=UNILOG_252_HEADERS, lineterminator="\n")
    writer.writeheader()

    if isinstance(batch, EnrichedBatch):
        for enriched_row in batch.rows:
            fmap = enriched_row.field_map
            part_number = fmap.get("mfg_part_num", fmap.get("part_number")).canonical_value or "" if ("mfg_part_num" in fmap or "part_number" in fmap) else ""
            raw_mfr = fmap.get("part_manuf", fmap.get("manufacturer")).raw_value if ("part_manuf" in fmap or "manufacturer" in fmap) else None
            raw_desc = fmap.get("part_desc", fmap.get("description")).raw_value if ("part_desc" in fmap or "description" in fmap) else None
            e1_brand = fmap.get("e1_brand").raw_value if "e1_brand" in fmap else None
            unilog_brand = fmap.get("unilog_brand").raw_value if "unilog_brand" in fmap else None
            dib_brand = fmap.get("dib_brand").raw_value if "dib_brand" in fmap else None

            row_dict = row_to_unilog_dict(part_number, raw_mfr, raw_desc, e1_brand, unilog_brand, dib_brand)
            writer.writerow(row_dict)
    else:
        for source_row in batch.rows:
            vals = source_row.values
            part_number = vals.get("mfg_part_num") or vals.get("part_number") or ""
            raw_mfr = vals.get("part_manuf") or vals.get("manufacturer")
            raw_desc = vals.get("part_desc") or vals.get("description")
            e1_brand = vals.get("e1_brand")
            unilog_brand = vals.get("unilog_brand")
            dib_brand = vals.get("dib_brand")

            row_dict = row_to_unilog_dict(part_number, raw_mfr, raw_desc, e1_brand, unilog_brand, dib_brand)
            writer.writerow(row_dict)

    return output.getvalue()
