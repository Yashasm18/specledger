"""Source discovery service for manufacturer product intelligence.

Given a manufacturer name and part number, discovers authoritative
product pages, datasheets, and technical documentation from the
manufacturer's own website. This module enforces the UniHack
requirement that enrichment data must come from manufacturer sources,
not from shopping sites or marketplaces.

Architecture:
  1. Manufacturer URL registry — maps canonical names to known domains
  2. Source search strategy — constructs lookup queries
  3. Blocked-source filter — rejects Amazon, eBay, marketplaces
  4. Evidence snapshot — stores page metadata and content hash
  5. Source type classifier — product page, PDF, manual, video, etc.

For the hackathon prototype, actual HTTP requests are optional.
The system can operate in 'simulated' mode with synthetic evidence
to demonstrate the workflow without network dependency.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence
from urllib.parse import urlparse


class SourceType(Enum):
    PRODUCT_PAGE = "product_page"
    PDF_DATASHEET = "pdf_datasheet"
    TECHNICAL_MANUAL = "technical_manual"
    CATALOGUE_PAGE = "catalogue_page"
    VIDEO = "video"
    SPECIFICATION_SHEET = "specification_sheet"
    UNKNOWN = "unknown"


class SourceStatus(Enum):
    DISCOVERED = "discovered"
    FETCHED = "fetched"
    VERIFIED = "verified"
    FAILED = "failed"
    BLOCKED = "blocked"


# ---------------------------------------------------------------------------
# Blocked source domains — marketplaces and shopping sites
# ---------------------------------------------------------------------------

BLOCKED_DOMAINS = frozenset({
    "amazon.com", "amazon.co.uk", "amazon.ca", "amazon.de",
    "ebay.com", "ebay.co.uk",
    "walmart.com", "target.com",
    "homedepot.com", "lowes.com",
    "alibaba.com", "aliexpress.com",
    "wish.com", "etsy.com",
    "overstock.com", "wayfair.com",
    "grainger.com",  # distributor, not manufacturer
    "mcmaster.com", "mcmaster-carr.com",
    "zoro.com", "globalindustrial.com",
})

# Pattern for generic shopping indicators in URLs
SHOPPING_URL_PATTERNS = re.compile(
    r"(add.to.cart|buy.now|checkout|shopping|marketplace|/shop/|/store/|price\-compare)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Manufacturer URL registry
# ---------------------------------------------------------------------------

MANUFACTURER_DOMAINS: dict[str, list[str]] = {
    # Industrial Valves & Fluid Handling
    "Parker Hannifin": ["parker.com"],
    "Emerson Electric": ["emerson.com"],
    "Honeywell": ["honeywell.com"],
    "Flowserve": ["flowserve.com"],
    "Crane Co.": ["craneco.com", "cranevalve.com"],
    "Watts Water Technologies": ["watts.com"],
    "Apollo Valves": ["apollovalves.com", "apolloflowcontrols.com"],
    "Nibco": ["nibco.com"],
    "Milwaukee Valve": ["milwaukeevalve.com"],
    "Kitz Corporation": ["kitz.com", "kitz.co.jp"],
    "Velan": ["velan.com"],
    "Cameron (Schlumberger)": ["slb.com", "c-a-m.com"],
    "Pentair": ["pentair.com"],
    "ITT Inc.": ["itt.com"],
    "Bray International": ["bfrvalves.com"],
    "Swagelok": ["swagelok.com"],
    "Victaulic": ["victaulic.com"],
    "Graco": ["graco.com"],
    "Grundfos": ["grundfos.com"],
    "Xylem": ["xylem.com"],

    # Tools, Abrasives & Machinery (Unilog Input Dataset)
    "Freud": ["freudtools.com", "diablotools.com"],
    "Freud Inc": ["freudtools.com", "diablotools.com"],
    "3M": ["3m.com"],
    "3 M Co": ["3m.com"],
    "Jam Industrial Supply LLC": ["3m.com", "jamindustrialsupply.com"],
    "Mirka Abrasives Inc": ["mirka.com"],
    "Milwaukee Accessory": ["milwaukeetool.com"],
    "Milwaukee": ["milwaukeetool.com"],
    "Black & Decker/dewlt": ["dewalt.com", "blackanddecker.com"],
    "Dewalt": ["dewalt.com"],
    "Makita Usa Inc": ["makitatools.com"],
    "Makita": ["makitatools.com"],
    "Festool USA": ["festoolusa.com"],
    "Festool": ["festoolusa.com"],
    "Kreg Tool Company": ["kregtool.com"],
    "Saw Stop LLC": ["sawstop.com"],
    "Oliver Machinery Company": ["olivermachinery.net"],
    "Woodpeckers Inc": ["woodpeck.com"],
    "Bow Products": ["bowproducts.com"],
    "Wera Tools NA Inc": ["wera.de", "weratools.com"],
    "King Canada Inc": ["kingcanada.com"],
    "Woodstock Intl": ["grizzly.com", "woodstockint.com"],

    # Lighting & Electrical
    "Phillips Lighting": ["lighting.philips.com", "signify.com"],
    "Satco Prod Inc": ["satco.com"],
    "Kichler Lighting": ["kichler.com"],
    "Leviton Mfg Co": ["leviton.com"],
    "Southwire/g Turner": ["southwire.com"],
    "Hunter Fan Co": ["hunterfan.com"],

    # Building Materials
    "Boise Cascade Building Materials": ["bc.com"],
    "Emseal Joint Systems Ltd": ["emseal.com"],
    "Rees Cast Stone Company": ["reescaststone.com"],

    # Consumer Appliances & Electronics (Unilog Sample Output Dataset)
    "Appliance Dealers Cooperative": ["frigidaire.com", "whirlpool.com", "geappliances.com"],
    "Frigidaire": ["frigidaire.com"],
    "Whirlpool Corporation": ["whirlpool.com"],
    "Whirlpool": ["whirlpool.com"],
    "GE": ["geappliances.com"],
    "GE Appliances": ["geappliances.com"],
    "LG": ["lg.com"],
    "KitchenAid": ["kitchenaid.com"],
    "Speed Queen": ["speedqueen.com"],
    "Rheem Manufacturing": ["rheem.com"],
    "V & V Appliance Parts Inc": ["vvappliance.com"],
}



@dataclass(frozen=True)
class DiscoveredSource:
    """A single discovered source for a product."""
    url: str
    source_type: SourceType
    status: SourceStatus
    manufacturer: str
    part_number: str
    domain: str
    title: str | None = None
    content_hash: str | None = None
    discovered_at: float = 0.0
    fetch_latency_ms: float | None = None
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "source_type": self.source_type.value,
            "status": self.status.value,
            "manufacturer": self.manufacturer,
            "part_number": self.part_number,
            "domain": self.domain,
            "title": self.title,
            "content_hash": self.content_hash,
            "discovered_at": self.discovered_at,
            "fetch_latency_ms": self.fetch_latency_ms,
            "confidence": self.confidence,
        }


@dataclass
class SourceDiscoveryResult:
    """Result of source discovery for one product."""
    manufacturer: str
    part_number: str
    sources: list[DiscoveredSource] = field(default_factory=list)
    blocked_urls: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def has_product_page(self) -> bool:
        return any(s.source_type == SourceType.PRODUCT_PAGE for s in self.sources)

    @property
    def has_datasheet(self) -> bool:
        return any(s.source_type in {SourceType.PDF_DATASHEET, SourceType.SPECIFICATION_SHEET}
                   for s in self.sources)

    def to_dict(self) -> dict:
        return {
            "manufacturer": self.manufacturer,
            "part_number": self.part_number,
            "source_count": self.source_count,
            "has_product_page": self.has_product_page,
            "has_datasheet": self.has_datasheet,
            "sources": [s.to_dict() for s in self.sources],
            "blocked_urls": self.blocked_urls,
            "search_queries": self.search_queries,
        }


# ---------------------------------------------------------------------------
# URL validation and classification
# ---------------------------------------------------------------------------

def is_blocked_source(url: str) -> bool:
    """Check if a URL belongs to a blocked marketplace/shopping domain."""
    try:
        parsed = urlparse(url)
        domain = parsed.hostname or ""
        # Strip www. prefix for matching
        domain = domain.lower().removeprefix("www.")
        if domain in BLOCKED_DOMAINS:
            return True
        # Check for shopping patterns in the URL path
        if SHOPPING_URL_PATTERNS.search(url):
            return True
    except Exception:
        pass
    return False


def extract_domain(url: str) -> str:
    """Extract the base domain from a URL."""
    try:
        parsed = urlparse(url)
        return (parsed.hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def is_manufacturer_domain(url: str, manufacturer: str) -> bool:
    """Check if a URL belongs to the manufacturer's known domains."""
    domain = extract_domain(url)
    known_domains = MANUFACTURER_DOMAINS.get(manufacturer, [])
    return any(domain.endswith(d) for d in known_domains)


def classify_source_type(url: str) -> SourceType:
    """Classify a URL into a source type based on path and extension."""
    path = urlparse(url).path.lower()
    if path.endswith(".pdf"):
        if any(kw in path for kw in ("datasheet", "data-sheet", "spec", "specification")):
            return SourceType.SPECIFICATION_SHEET
        if any(kw in path for kw in ("manual", "guide", "instruction")):
            return SourceType.TECHNICAL_MANUAL
        return SourceType.PDF_DATASHEET
    if any(ext in path for ext in (".mp4", ".webm", ".avi")) or "video" in path or "youtube" in url.lower():
        return SourceType.VIDEO
    if any(kw in path for kw in ("catalogue", "catalog", "brochure")):
        return SourceType.CATALOGUE_PAGE
    if any(kw in path for kw in ("product", "part", "item", "detail")):
        return SourceType.PRODUCT_PAGE
    return SourceType.PRODUCT_PAGE  # Default for manufacturer pages


def build_search_queries(manufacturer: str, part_number: str) -> list[str]:
    """Build search queries to find manufacturer product pages."""
    clean_mfr = manufacturer.strip()
    clean_pn = part_number.strip()
    queries = [
        f"{clean_mfr} {clean_pn} product page",
        f"{clean_mfr} {clean_pn} datasheet",
        f"{clean_mfr} {clean_pn} specification",
        f"site:{MANUFACTURER_DOMAINS.get(clean_mfr, [''])[0]} {clean_pn}",
    ]
    return [q for q in queries if q.strip()]


def build_direct_urls(manufacturer: str, part_number: str) -> list[str]:
    """Build candidate direct URLs from known manufacturer domain patterns."""
    domains = MANUFACTURER_DOMAINS.get(manufacturer, [])
    if not domains:
        return []

    clean_pn = part_number.strip().lower().replace(" ", "-")
    urls: list[str] = []
    for domain in domains:
        urls.extend([
            f"https://www.{domain}/product/{clean_pn}",
            f"https://www.{domain}/products/{clean_pn}",
            f"https://www.{domain}/us/en/product/{clean_pn}",
            f"https://www.{domain}/search?q={part_number.strip()}",
        ])
    return urls


# ---------------------------------------------------------------------------
# Simulated source discovery (for prototype/testing)
# ---------------------------------------------------------------------------

def discover_sources_simulated(
    manufacturer: str,
    part_number: str,
) -> SourceDiscoveryResult:
    """Simulate source discovery with realistic synthetic evidence.

    This generates plausible source URLs based on the manufacturer
    domain registry. In production, this would make actual HTTP
    requests to discover and validate sources.
    """
    result = SourceDiscoveryResult(
        manufacturer=manufacturer,
        part_number=part_number,
    )

    domains = MANUFACTURER_DOMAINS.get(manufacturer, [])
    if not domains:
        result.search_queries = build_search_queries(manufacturer, part_number)
        return result

    now = time.time()
    primary_domain = domains[0]
    clean_pn = part_number.strip().lower().replace(" ", "-")

    # Simulate discovering a product page
    product_url = f"https://www.{primary_domain}/product/{clean_pn}"
    content = f"Product page for {manufacturer} {part_number}"
    result.sources.append(DiscoveredSource(
        url=product_url,
        source_type=SourceType.PRODUCT_PAGE,
        status=SourceStatus.DISCOVERED,
        manufacturer=manufacturer,
        part_number=part_number,
        domain=primary_domain,
        title=f"{manufacturer} - {part_number}",
        content_hash=hashlib.sha256(content.encode()).hexdigest()[:16],
        discovered_at=now,
        fetch_latency_ms=150.0,
        confidence=0.85,
    ))

    # Simulate discovering a PDF datasheet
    pdf_url = f"https://www.{primary_domain}/documents/{clean_pn}-datasheet.pdf"
    result.sources.append(DiscoveredSource(
        url=pdf_url,
        source_type=SourceType.PDF_DATASHEET,
        status=SourceStatus.DISCOVERED,
        manufacturer=manufacturer,
        part_number=part_number,
        domain=primary_domain,
        title=f"{part_number} Technical Datasheet",
        content_hash=hashlib.sha256(pdf_url.encode()).hexdigest()[:16],
        discovered_at=now,
        fetch_latency_ms=200.0,
        confidence=0.80,
    ))

    result.search_queries = build_search_queries(manufacturer, part_number)

    return result


def discover_sources_batch(
    rows: Sequence[tuple[str, str]],
) -> list[SourceDiscoveryResult]:
    """Discover sources for a batch of (manufacturer, part_number) pairs."""
    results: list[SourceDiscoveryResult] = []
    seen: dict[tuple[str, str], SourceDiscoveryResult] = {}
    for manufacturer, part_number in rows:
        key = (manufacturer.strip().casefold(), part_number.strip().casefold())
        if key in seen:
            results.append(seen[key])
        else:
            result = discover_sources_simulated(manufacturer, part_number)
            seen[key] = result
            results.append(result)
    return results
