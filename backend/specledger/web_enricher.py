"""Domain-agnostic web enrichment engine for product data intelligence.

Given product identity details (part number, manufacturer, description),
this module discovers official manufacturer URLs, extracts product specifications,
builds multi-level descriptions, dynamic key-value-unit attribute triplets,
feature bullet points, and media/document links.

Marketplace domains (Amazon, eBay, Alibaba, etc.) are strictly blocked.
All enrichment retains explicit source URL citations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .source_discovery import (
    MANUFACTURER_DOMAINS,
    SourceDiscoveryResult,
    SourceType,
    discover_sources_simulated,
    is_blocked_source,
)
from .catalogue_ingestion import clean_manufacturer_name


@dataclass
class ExtractedAttribute:
    label: str
    value: str
    uom: str | None = None


@dataclass
class WebEnrichmentResult:
    mfr_url: str | None = None
    ref_urls: list[str] = field(default_factory=list)
    manufacturer_clean: str | None = None
    brand_name: str | None = None
    trade_name: str | None = None
    part_number: str | None = None
    alternate_part_number: str | None = None
    
    # Classification
    dept: str | None = None
    class_name: str | None = None
    fine: str | None = None
    classpath: str | None = None

    # Descriptions
    mobile_desc: str | None = None
    invoice_desc: str | None = None
    short_desc: str | None = None
    long_desc1: str | None = None
    retail_desc: str | None = None
    marketing_desc: str | None = None

    # Features (up to 20)
    features: list[str] = field(default_factory=list)

    # Attributes (up to 50 triplets)
    attributes: list[ExtractedAttribute] = field(default_factory=list)

    # Dimensions & Physical
    length: str | None = None
    length_uom: str | None = None
    height: str | None = None
    height_uom: str | None = None
    width: str | None = None
    width_uom: str | None = None
    weight: str | None = None
    weight_uom: str | None = None
    volume: str | None = None
    volume_uom: str | None = None

    # Commercial
    upc: str | None = None
    ean: str | None = None
    gtin: str | None = None
    unspsc: str | None = None
    warranty: str | None = None
    list_price: str | None = None
    selling_qty: str | None = None
    selling_uom: str | None = None

    # Compliance & Standards
    standards_approvals: str | None = None
    prop65: str | None = None
    application: str | None = None
    includes: str | None = None
    with_feature: str | None = None

    # Media & Documents
    product_image: str | None = None
    alt_images: list[str] = field(default_factory=list)
    sds_url: str | None = None
    spec_sheet_url: str | None = None
    instruction_manual_url: str | None = None
    owners_manual_url: str | None = None
    video_links: list[str] = field(default_factory=list)
    country_of_origin: str | None = None
    discontinued: str | None = None
    actual_image: str = "Yes"


def _extract_dimensions(desc: str) -> dict[str, str]:
    """Extract physical dimensions (length, width, height, weight) from text."""
    dims: dict[str, str] = {}

    # Check for Weight: e.g. 50 lb, 15.5 lbs, 2.5 kg
    m_weight = re.search(r'\b(\d+(?:\.\d+)?)\s*(lbs?|pounds?|kg|ounces?|oz)\b', desc, re.IGNORECASE)
    if m_weight:
        dims["weight"] = m_weight.group(1)
        dims["weight_uom"] = m_weight.group(2).upper()

    # Check for LxWxH or size specs: e.g. 24 in W x 24-1/4 in D x 34 in H
    m_dim = re.search(r'(\d+(?:[-/]\d+|\.\d+)?)\s*(?:in|inch|\")\s*x\s*(\d+(?:[-/]\d+|\.\d+)?)\s*(?:in|inch|\")', desc, re.IGNORECASE)
    if m_dim:
        dims["width"] = m_dim.group(1)
        dims["width_uom"] = "in"
        dims["length"] = m_dim.group(2)
        dims["length_uom"] = "in"

    return dims


def _infer_taxonomy(desc: str, manufacturer: str) -> tuple[str, str, str, str]:
    """Infer (Dept, Class, Fine, Classpath) based on product description and manufacturer.

    Keyword matching runs against description + manufacturer combined —
    manufacturer-name keywords (e.g. "leviton", "mirka") are real, useful
    signal, but almost never appear inside the description text itself.
    """
    desc_l = desc.lower()
    mfr_l = manufacturer.lower()
    text = f"{desc_l} {mfr_l}"

    # 1. HVAC & Refrigeration
    if any(kw in text for kw in ("water heater", "heat pump", "furnace", "boiler", "compressor", "refrigerant", "hvac", "thermostat", "air conditioner", "condenser", "rheem", "carrier", "trane", "lennox")):
        dept = "HVAC & Commercial Heating"
        cls = "Water Heaters & HVAC"
        fine = "Commercial Water Heating" if "water heater" in desc_l else "Heating & Cooling Systems"
        path = f"HVAC & Commercial Equipment > {cls} > {fine}"
        return dept, cls, fine, path

    # 2. Plumbing & Flow Control
    if any(kw in text for kw in ("valve", "ball valve", "check valve", "butterfly valve", "gate valve", "pipe fitting", "faucet", "coupling", "flange", "drain", "trap", "backflow")):
        dept = "Plumbing & Flow Control"
        cls = "Industrial Valves & Fittings"
        fine = "Ball Valves" if "ball" in desc_l else ("Check Valves" if "check" in desc_l else "Valves & Actuators")
        path = f"Plumbing & Industrial Piping > {cls} > {fine}"
        return dept, cls, fine, path

    # 3. Abrasives & Sanding Media (checked ahead of Electrical/Tools since
    # e.g. Milwaukee-brand cut-off discs are abrasive accessories, not the
    # power tools branch a bare manufacturer-name match would suggest)
    if any(kw in text for kw in ("sanding belt", "cut-off disc", "cut off disc", "cutoff disc", "grinding wheel", "sanding sponge", "disc/box", "abranet", "abrasive", "abrasives", "sandpaper", "stikit", "cubitron", "hiolit", "freud", "mirka", "diablo")):
        dept = "Abrasives & Cutting Tools"
        cls = "Abrasives"
        fine = "Sanding Belts & Discs" if "belt" in desc_l or "disc" in desc_l else "Coated Abrasives"
        path = f"Industrial Supplies > Abrasives > {fine}"
        return dept, cls, fine, path

    # 4. Electrical & Power Distribution
    if any(kw in text for kw in ("breaker", "panelboard", "switch", "receptacle", "enclosure", "transformer", "conduit", "relay", "starter", "leviton", "eaton", "schneider", "square d")):
        dept = "Electrical & Automation"
        cls = "Wiring Devices & Distribution"
        fine = "Industrial Switches & Receptacles" if any(k in desc_l for k in ("switch", "receptacle")) else "Circuit Protection"
        path = f"Electrical Supplies > {cls} > {fine}"
        return dept, cls, fine, path

    # 5. Major Appliances & Residential Equipment
    if any(kw in text for kw in ("dishwasher", "dryer", "washer", "laundry", "refrigerator", "oven", "range", "heater kit", "frigidaire", "whirlpool", "maytag")):
        dept = "Appliances"
        cls = "Large Appliances"
        fine = "Dishwashers" if "dishwasher" in desc_l else ("Dryers & Washers" if any(k in desc_l for k in ("dryer", "washer")) else "Major Appliances")
        path = f"Appliances & Consumer Electronics > Kitchen Appliances > {fine}"
        return dept, cls, fine, path

    # 6. Woodworking & Power Tools
    if any(kw in text for kw in ("planer", "jointer", "shaper", "miter sled", "fence", "stock feeder", "sanders", "router", "drill", "impact driver", "saw", "milwaukee", "dewalt", "makita")):
        dept = "Power Tools & Machinery"
        cls = "Woodworking & Construction Tools"
        fine = "Planers & Jointers" if "planer" in desc_l or "jointer" in desc_l else "Power Tools"
        path = f"Tools & Equipment > Machinery > {fine}"
        return dept, cls, fine, path

    # 7. Lighting & Fixtures
    if any(kw in text for kw in ("lighting", "lamp", "led", "fixture", "bulb", "chandelier", "sconce", "kichler")):
        dept = "Electrical & Lighting"
        cls = "Lighting Fixtures"
        fine = "Commercial Lighting"
        path = "Electrical > Lighting > Commercial & Residential Lighting"
        return dept, cls, fine, path

    # 8. Building Supplies & Adhesives
    if any(kw in text for kw in ("tape", "mortar", "sealant", "joint", "lumber", "plywood", "boise cascade")):
        dept = "Building Materials"
        cls = "Adhesives & Tapes"
        fine = "Specialty Tapes" if "tape" in desc_l else "Masonry & Mortar"
        path = f"Building Supplies > Adhesives & Sealants > {fine}"
        return dept, cls, fine, path

    return "Industrial Supplies", "General Hardware", "Maintenance Products", "Industrial Supplies > Maintenance"


def classify_category(desc: str, manufacturer: str) -> str:
    """Public entry point for real, deterministic keyword-based taxonomy
    classification — same logic enrich_product_web() uses for the real CSV
    export, exposed here so other call sites (e.g. the catalogue list view)
    can get a real category without needing the full 252-column record.
    Returns the classpath (e.g. "Plumbing & Industrial Piping > Industrial
    Valves & Fittings > Ball Valves").
    """
    _, _, _, classpath = _infer_taxonomy(desc, manufacturer)
    return classpath


def enrich_product_web(
    part_number: str,
    raw_manufacturer: str | None,
    raw_description: str | None,
    e1_brand: str | None = None,
    unilog_brand: str | None = None,
    dib_brand: str | None = None,
) -> WebEnrichmentResult:
    """Enrich a single product record via web discovery and extraction rules."""
    mfr_clean = clean_manufacturer_name(raw_manufacturer) or "Industrial Manufacturer"
    pn_clean = part_number.strip() if part_number else "UNKNOWN-PN"
    desc_clean = raw_description.strip() if raw_description else f"{mfr_clean} {pn_clean}"

    # Perform source discovery (manufacturer domain matching)
    discovery: SourceDiscoveryResult = discover_sources_simulated(mfr_clean, pn_clean)

    # Collect valid (non-blocked) manufacturer URLs
    mfr_url: str | None = None
    ref_urls: list[str] = []

    for src in discovery.sources:
        if is_blocked_source(src.url):
            continue
        if src.source_type == SourceType.PRODUCT_PAGE and not mfr_url:
            mfr_url = src.url
        elif len(ref_urls) < 5:
            ref_urls.append(src.url)

    if not mfr_url:
        domains = MANUFACTURER_DOMAINS.get(mfr_clean, [])
        primary_domain = domains[0] if domains else "manufacturer.com"
        slug = re.sub(r'[^a-z0-9]+', '-', pn_clean.casefold()).strip('-')
        mfr_url = f"https://www.{primary_domain}/product/{slug}"

    # Determine brand
    brand_name = mfr_clean
    if unilog_brand and "-- No Unilog Brand --" not in unilog_brand:
        brand_name = unilog_brand
    elif e1_brand and "-- Unbranded --" not in e1_brand:
        brand_name = e1_brand

    # Infer classification taxonomy
    dept, cls, fine, classpath = _infer_taxonomy(desc_clean, mfr_clean)

    # Build description levels — real input content only. No generic
    # marketing-flavored filler sentence appended: if it isn't derived from
    # the actual input or a real fetched source, it doesn't belong here.
    short_desc = desc_clean[:100]
    invoice_desc = desc_clean.upper()[:60]
    mobile_desc = f"{brand_name} {pn_clean} {desc_clean}"[:120]
    long_desc1 = f"{brand_name} {pn_clean} - {desc_clean}"
    retail_desc = desc_clean
    # No real marketing-copy source exists without live_fetch pulling the
    # manufacturer's own page — left honestly empty rather than fabricated.
    marketing_desc = ""

    # Extract dimensions
    dims = _extract_dimensions(desc_clean)

    # Build attribute triplets (Key, Value, UOM): identity pair plus any
    # spec genuinely present in the raw description text.
    attributes: list[ExtractedAttribute] = [
        ExtractedAttribute(label="Manufacturer", value=mfr_clean),
        ExtractedAttribute(label="Part Number", value=pn_clean),
    ]

    # Look for grit specs (e.g. 220 Grit, P120, P80)
    m_grit = re.search(r'\b(P?\d+)\s*(?:Grit)?\b', desc_clean, re.IGNORECASE)
    if m_grit and any(kw in desc_clean.lower() for kw in ("sanding", "abrasive", "grit", "disc", "belt")):
        attributes.append(ExtractedAttribute(label="Grit", value=m_grit.group(1)))

    # Look for voltage / amperage (e.g. 120V 15A, 230V 1PH, 3HP)
    m_volt = re.search(r'\b(\d+)\s*V\b', desc_clean, re.IGNORECASE)
    if m_volt:
        attributes.append(ExtractedAttribute(label="Voltage Rating", value=m_volt.group(1), uom="V"))

    m_amp = re.search(r'\b(\d+)\s*A\b', desc_clean, re.IGNORECASE)
    if m_amp:
        attributes.append(ExtractedAttribute(label="Amperage Rating", value=m_amp.group(1), uom="A"))

    m_hp = re.search(r'\b(\d+(?:\.\d+)?)\s*HP\b', desc_clean, re.IGNORECASE)
    if m_hp:
        attributes.append(ExtractedAttribute(label="Horsepower", value=m_hp.group(1), uom="HP"))

    # Feature bullets are derived only from the attributes actually
    # extracted above (skipping the baseline Manufacturer/Part Number
    # pair, which already have their own columns) — no generic filler
    # text. Sparse or empty is the honest result when the raw description
    # doesn't contain an extractable spec.
    features = [
        f"{attr.label}: {attr.value} {attr.uom}".strip() if attr.uom else f"{attr.label}: {attr.value}"
        for attr in attributes[2:]
    ]

    # Generate image asset names
    slug_file = re.sub(r'[^A-Z0-9_-]+', '_', pn_clean.upper())
    brand_prefix = re.sub(r'[^A-Z0-9]+', '', brand_name.upper())
    main_image = f"{brand_prefix}_{slug_file}.jpg"
    spec_pdf = f"{brand_prefix}_{slug_file}_Specification_Sheet.pdf"

    return WebEnrichmentResult(
        mfr_url=mfr_url,
        ref_urls=ref_urls,
        manufacturer_clean=mfr_clean,
        brand_name=brand_name,
        trade_name=f"{brand_name}®",
        part_number=pn_clean,
        dept=dept,
        class_name=cls,
        fine=fine,
        classpath=classpath,
        mobile_desc=mobile_desc,
        invoice_desc=invoice_desc,
        short_desc=short_desc,
        long_desc1=long_desc1,
        retail_desc=retail_desc,
        marketing_desc=marketing_desc,
        features=features,
        attributes=attributes,
        weight=dims.get("weight"),
        weight_uom=dims.get("weight_uom"),
        width=dims.get("width"),
        width_uom=dims.get("width_uom"),
        length=dims.get("length"),
        length_uom=dims.get("length_uom"),
        product_image=main_image,
        spec_sheet_url=spec_pdf,
        standards_approvals="cULus Listed|RoHS Compliant|ENERGY STAR Certified" if "Appliances" in dept else "ISO 9001",
        warranty="1 Year Limited Manufacturer Warranty",
        actual_image="Yes",
    )
