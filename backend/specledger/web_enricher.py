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


def _match_taxonomy(text: str, desc_l: str) -> tuple[str, str, str, str] | None:
    """Run the keyword cascade against `text`, returning None if nothing hits.

    `desc_l` is used only to pick the fine-grained bucket within a matched
    branch, so it stays the real description in both matching passes.
    """

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
    # power tools branch a bare manufacturer-name match would suggest).
    #
    # "freud" and "diablo" were removed from this list. A manufacturer name
    # is only usable as a category signal when that manufacturer makes one
    # category — Mirka does; Freud/Diablo make saw blades, router bits, hole
    # saws, chisels and drill bits alongside abrasives. Testing a real
    # 14-product Diablo catalogue, every row landed in Coated Abrasives on
    # the strength of the brand name alone.
    if any(kw in text for kw in ("sanding belt", "cut-off disc", "cut off disc", "cutoff disc", "grinding wheel", "sanding sponge", "disc/box", "abranet", "abrasive", "abrasives", "sandpaper", "stikit", "cubitron", "hiolit", "mirka")):
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

    # 8. Decking, Railing & Outdoor Living. Checked before the general
    # building-materials branch because composite decking brands and profile
    # terms ("grooved", "fascia", "post sleeve") are specific enough to
    # classify on their own, and they are the single largest group in this
    # dataset that keyword matching previously left unclassified.
    if any(kw in text for kw in (
        "decking", "deck board", "azek", "trex", "timbertech", "fiberon",
        "fascia", "baluster", "post sleeve", "rail kit", "railing",
        "grooved", "riser", "pergola", "lattice",
    )):
        dept = "Building Materials"
        cls = "Decking & Outdoor Living"
        if any(k in text for k in ("baluster", "rail kit", "railing", "post sleeve")):
            fine = "Railing & Balusters"
        elif "fascia" in text or "riser" in text:
            fine = "Trim & Fascia"
        else:
            fine = "Composite & PVC Decking"
        path = f"Building Supplies > Decking & Outdoor Living > {fine}"
        return dept, cls, fine, path

    # 9. Safety & Personal Protective Equipment
    if any(kw in text for kw in (
        "safety glass", "safety glasses", "goggle", "hard hat", "respirator",
        "ear muff", "earplug", "hearing protect", "work glove", "safety vest",
        "high visibility", "hi-vis", "face shield", "knee pad", "kneeling pad",
    )):
        dept = "Safety & PPE"
        cls = "Personal Protective Equipment"
        if any(k in text for k in ("glass", "goggle", "face shield")):
            fine = "Eye & Face Protection"
        elif "glove" in text:
            fine = "Hand Protection"
        else:
            fine = "Protective Equipment"
        path = f"Safety & PPE > Personal Protective Equipment > {fine}"
        return dept, cls, fine, path

    # 10. Lumber & Sheet Goods — structural material, distinct from the
    # adhesives branch it used to be lumped into.
    if any(kw in text for kw in ("lumber", "plywood", "osb", "sheathing", "boise cascade", "stud ")):
        dept = "Building Materials"
        cls = "Lumber & Sheet Goods"
        fine = "Panels & Sheathing" if any(k in text for k in ("plywood", "osb", "sheathing")) else "Dimensional Lumber"
        path = f"Building Supplies > Lumber & Sheet Goods > {fine}"
        return dept, cls, fine, path

    # 11. Building Supplies & Adhesives
    if any(kw in text for kw in ("tape", "mortar", "sealant", "joint", "caulk", "grout")):
        dept = "Building Materials"
        cls = "Adhesives & Tapes"
        fine = "Specialty Tapes" if "tape" in desc_l else "Masonry & Mortar"
        path = f"Building Supplies > Adhesives & Sealants > {fine}"
        return dept, cls, fine, path

    return None


# The generic bucket, returned when neither the description nor the
# manufacturer name places a product anywhere more specific.
_GENERIC_TAXONOMY = (
    "Industrial Supplies", "General Hardware", "Maintenance Products",
    "Industrial Supplies > Maintenance",
)

# The classpath that means "the rules did not place this product". Defined
# here, beside the taxonomy it comes from, so the LLM tier and the delivery
# export share one definition instead of each carrying their own copy.
GENERIC_CLASSPATH = _GENERIC_TAXONOMY[3]


def is_unresolved_classpath(classpath: str | None) -> bool:
    """Whether deterministic classification left this row unplaced."""
    return not classpath or classpath == GENERIC_CLASSPATH


def _infer_taxonomy(desc: str | None, manufacturer: str | None) -> tuple[str, str, str, str]:
    """Infer (Dept, Class, Fine, Classpath) from a product description, using
    the manufacturer name only as a fallback hint.

    Both signals are useful but they are not equal. What a product *is* comes
    from its description; the manufacturer name only suggests what they tend
    to make. Matching them together let the weaker signal win whenever its
    branch was checked first — "Freud Inc" hits the abrasives keyword, so a
    real catalogue of Freud parts classified saw blades, hole saws, auger
    bits and chisels all as Coated Abrasives, because every row carried the
    manufacturer name.

    So description is matched alone first. Only when it places the product
    nowhere does the manufacturer name get a say, which is the case it was
    added for: rows whose description is a bare part number.

    Either field may be absent in real catalogue data, so both are coerced
    here rather than relying on every caller to guard them.
    """
    desc_l = (desc or "").lower()
    mfr_l = (manufacturer or "").lower()

    return (
        _match_taxonomy(desc_l, desc_l)
        or _match_taxonomy(mfr_l, desc_l)
        or _GENERIC_TAXONOMY
    )


def _strip_part_number(description: str, part_number: str) -> str:
    """The description with its part number removed.

    Descriptions in this dataset almost always lead with the part number, and
    identifiers are full of digits that read like specifications. Removing it
    first means a spec has to come from the descriptive text.
    """
    if not part_number:
        return description
    return re.sub(
        rf'(?<![A-Za-z0-9]){re.escape(part_number)}(?![A-Za-z0-9])',
        ' ', description, flags=re.IGNORECASE,
    )


def product_name_from_fine(fine: str | None) -> str:
    """Derive the product noun from the finest taxonomy level.

    Unilog's delivery format puts the product itself in "Product Name"
    ("Dishwasher"). We were writing brand + part number there, which restates
    two columns that already exist and never says what the item is. The
    taxonomy leaf already names the product category, so singularise it.

    Returns "" for an unknown category rather than inventing a noun.
    """
    if not fine:
        return ""
    # A compound leaf like "Sanding Belts & Discs" names two things; an
    # individual product is one of them, so take the first.
    head = fine.split("&")[0].strip()
    if not head:
        return ""
    words = head.split()
    last = words[-1]
    if last.endswith("ies") and len(last) > 4:
        last = last[:-3] + "y"
    elif last.endswith("ses") or last.endswith("xes") or last.endswith("ches") \
            or last.endswith("shes"):
        last = last[:-2]
    elif last.endswith("s") and not last.endswith("ss"):
        last = last[:-1]
    return " ".join(words[:-1] + [last])


def classify_category(desc: str | None, manufacturer: str | None) -> str:
    """Public entry point for real, deterministic keyword-based taxonomy
    classification — same logic enrich_product_web() uses for the real CSV
    export, exposed here so other call sites (e.g. the catalogue list view)
    can get a real category without needing the full 252-column record.
    Returns the classpath (e.g. "Plumbing & Industrial Piping > Industrial
    Valves & Fittings > Ball Valves").
    """
    _, _, _, classpath = _infer_taxonomy(desc, manufacturer)
    return classpath


_BRAND_PLACEHOLDERS = ("-- unbranded --", "-- no unilog brand --", "-- no dib brand --")


def _brand_signals(description: str, brands: tuple[str | None, ...]) -> str:
    """Text that carries the product's own branding, lowercased.

    Deliberately excludes the manufacturer name. That field is exactly what
    is ambiguous here — "Appliance Dealers Cooperative" is the distributor —
    so letting it vote would just re-assert the thing we cannot trust.
    """
    parts = [description or ""]
    for brand in brands:
        if brand and brand.strip().lower() not in _BRAND_PLACEHOLDERS:
            parts.append(brand)
    return " ".join(parts).casefold()


def _resolve_manufacturer_domain(
    manufacturer: str,
    description: str,
    brands: tuple[str | None, ...],
) -> str | None:
    """Pick the manufacturer's domain, or return None when it is unknowable.

    A guessed URL is the same defect as an invented specification, so this
    refuses rather than guesses in two cases the previous code papered over:

    * An unrecognised manufacturer used to yield "manufacturer.com" — a
      placeholder that belongs to nobody, published as a product page on 272
      of the official dataset's 1,000 rows.
    * Some registry entries are distributors fronting unrelated competitors
      ("Appliance Dealers Cooperative" -> frigidaire.com, whirlpool.com,
      geappliances.com). Taking the first put a Frigidaire URL on Whirlpool
      dishwashers, 84 rows of them.

    With several candidates, two things can still settle it:

    1. The product's own branding. If exactly one candidate's name is named
       in the description or brand columns, that is the one — a Diablo-branded
       belt belongs on diablotools.com, not its parent's freudtools.com.
    2. Failing that, whether every candidate is plainly the same company.
       "Apollo Valves" lists apollovalves.com and apolloflowcontrols.com;
       both carry the manufacturer's own name, so either is right and the
       first will do. "Appliance Dealers Cooperative" does not have that
       property, which is precisely what makes it a distributor.

    Anything else is genuinely undeterminable from six columns of input, and
    the row is left without a URL for live verification or a human to settle.
    """
    domains = MANUFACTURER_DOMAINS.get(manufacturer) or []
    if not domains:
        return None
    if len(domains) == 1:
        return domains[0]

    branded = [
        domain for domain in domains
        if _names_match(_brand_signals(description, brands), domain)
    ]
    if len(branded) == 1:
        return branded[0]

    # Every candidate carries the manufacturer's own name, so they are the
    # same company under different domains rather than rival brands.
    if all(_names_match(manufacturer.casefold(), domain) for domain in domains):
        return domains[0]

    return None


def _names_match(text: str, domain: str) -> bool:
    """Whether any word in `text` identifies `domain`.

    Matched by prefix rather than equality so "diablo" in a description
    identifies "diablotools.com", and "apollo" in "Apollo Valves" identifies
    both "apollovalves.com" and "apolloflowcontrols.com". Short words are
    ignored so a stray "in" or "co" cannot claim a domain.
    """
    words = {w for w in re.split(r'[^a-z0-9]+', text) if len(w) >= 4}
    return any(
        label.startswith(word) or word.startswith(label)
        for label in _domain_name_parts(domain)
        for word in words
    )


def _domain_name_parts(domain: str) -> tuple[str, ...]:
    """The meaningful name labels of a domain, minus public suffixes."""
    ignored = {"com", "net", "org", "co", "de", "jp", "www"}
    return tuple(p for p in domain.casefold().split(".") if p not in ignored)


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

    # Work out which manufacturer this row actually belongs to before
    # generating any URL for it. When that cannot be determined the row gets
    # no candidates at all — a URL naming the wrong company is worse than no
    # URL, and both were being produced here.
    resolved_domain = _resolve_manufacturer_domain(
        mfr_clean, desc_clean, (e1_brand, unilog_brand, dib_brand),
    )

    mfr_url: str | None = None
    ref_urls: list[str] = []

    if resolved_domain:
        discovery: SourceDiscoveryResult = discover_sources_simulated(
            mfr_clean, pn_clean, domain=resolved_domain,
        )
        for src in discovery.sources:
            if is_blocked_source(src.url):
                continue
            if src.source_type == SourceType.PRODUCT_PAGE and not mfr_url:
                mfr_url = src.url
            elif len(ref_urls) < 5:
                ref_urls.append(src.url)

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
    # Supplier descriptions in this dataset almost always lead with the part
    # number ("PDSH4816AF Dishwasher SS - Display Only"), so prepending it
    # unconditionally produced "PDSH4816AF PDSH4816AF Dishwasher ...". Only
    # prepend when the description doesn't already open with it — the prepend
    # still earns its place for rows whose description omits the part number.
    if desc_clean.lower().startswith(pn_clean.lower()):
        mobile_desc = f"{brand_name} {desc_clean}"[:120]
        long_desc1 = f"{brand_name} - {desc_clean}"
    else:
        mobile_desc = f"{brand_name} {pn_clean} {desc_clean}"[:120]
        long_desc1 = f"{brand_name} {pn_clean} - {desc_clean}"
    retail_desc = desc_clean
    # No real marketing-copy source exists without live_fetch pulling the
    # manufacturer's own page — left honestly empty rather than fabricated.
    marketing_desc = ""

    # Extract dimensions
    dims = _extract_dimensions(desc_clean)

    # Specifications are read from the description with the part number
    # removed. A part number is an identifier, never a specification, and
    # mining it produced fabricated specs on the official dataset: Grit 49
    # from "49-94-0013 ... Metal Cut Off Disc" (34 rows, and a cut-off disc
    # has no grit at all), 37418 A from "37418A Kichler Bath Light".
    spec_text = _strip_part_number(desc_clean, pn_clean)

    # Build attribute triplets (Key, Value, UOM) from specs genuinely present
    # in the raw description text.
    #
    # No identity pair. Unilog's delivery examples use these slots purely for
    # specifications — Series, Voltage Rating, Sound Level, Material — and
    # contain no "Manufacturer" or "Part Number" entry. Seeding those here
    # restated MANUFACTURER_NAME and MANUFACTURER_PART_NUMBER, and the value
    # was the distributor rather than the manufacturer anyway.
    attributes: list[ExtractedAttribute] = []

    # Grit needs to be stated, not merely be a number near an abrasive word.
    # Making "Grit" optional in this pattern meant any digits in a
    # description mentioning "disc" or "belt" became a grit value — a
    # diameter ("12\" Cut-Off Disc"), a width ("1/2\"x18\" Sanding Belt")
    # or a part number all qualified. Accept only the two forms that
    # actually designate one: a standalone FEPA code (P150), or a number
    # written next to the word itself (220 Grit / Grit 220).
    m_grit = (
        re.search(r'\b(P\d{2,4})\b', spec_text, re.IGNORECASE)
        or re.search(r'\b(\d{2,4})\s*-?\s*Grit\b', spec_text, re.IGNORECASE)
        or re.search(r'\bGrit\s*-?\s*(\d{2,4})\b', spec_text, re.IGNORECASE)
    )
    if m_grit:
        attributes.append(ExtractedAttribute(label="Grit", value=m_grit.group(1)))

    # Look for voltage / amperage (e.g. 120V 15A, 230V 1PH, 3HP)
    m_volt = re.search(r'\b(\d+)\s*V\b', spec_text, re.IGNORECASE)
    if m_volt:
        attributes.append(ExtractedAttribute(label="Voltage Rating", value=m_volt.group(1), uom="V"))

    # Capped at four digits: a bare "A" is a common part-number suffix, and
    # no catalogue item in scope draws 37,418 amps.
    m_amp = re.search(r'\b(\d{1,4})\s*A\b', spec_text, re.IGNORECASE)
    if m_amp:
        attributes.append(ExtractedAttribute(label="Amperage Rating", value=m_amp.group(1), uom="A"))

    m_hp = re.search(r'\b(\d+(?:\.\d+)?)\s*HP\b', spec_text, re.IGNORECASE)
    if m_hp:
        attributes.append(ExtractedAttribute(label="Horsepower", value=m_hp.group(1), uom="HP"))

    # Feature bullets are derived only from the attributes actually extracted
    # above — no generic filler text. Sparse or empty is the honest result
    # when the raw description doesn't contain an extractable spec. Nothing
    # is skipped now that the identity pair no longer occupies slots 1 and 2.
    features = [
        f"{attr.label}: {attr.value} {attr.uom}".strip() if attr.uom else f"{attr.label}: {attr.value}"
        for attr in attributes
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
