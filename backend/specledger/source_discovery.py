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
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence
from urllib.parse import urljoin, urlparse

logger = logging.getLogger("specledger")


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
    # General marketplaces
    "amazon.com", "amazon.co.uk", "amazon.ca", "amazon.de",
    "amazon.fr", "amazon.in", "amazon.co.jp",
    "ebay.com", "ebay.co.uk", "ebay.de", "ebay.ca", "ebay.com.au",
    "walmart.com", "target.com", "bestbuy.com",
    "alibaba.com", "aliexpress.com", "dhgate.com", "made-in-china.com",
    "temu.com", "shein.com", "wish.com", "etsy.com",
    "overstock.com", "wayfair.com", "rakuten.com",
    "shopee.com", "lazada.com", "mercadolibre.com",
    # Big-box retail
    "homedepot.com", "lowes.com", "menards.com",
    # Industrial distributors — resellers, not the manufacturer of record
    "grainger.com",
    "mcmaster.com", "mcmaster-carr.com",
    "zoro.com", "globalindustrial.com",
    "fastenal.com", "mscdirect.com", "ferguson.com",
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

    # HVAC & Commercial Heating & Refrigeration
    "Rheem Manufacturing": ["rheem.com"],
    "Rheem": ["rheem.com"],
    "Carrier Corporation": ["carrier.com"],
    "Carrier": ["carrier.com"],
    "Trane Technologies": ["trane.com"],
    "Trane": ["trane.com"],
    "Lennox International": ["lennox.com"],
    "Lennox": ["lennox.com"],
    "Copeland": ["copeland.com"],
    "Daikin Applied": ["daikin.com", "daikinapplied.com"],
    "Bradford White": ["bradfordwhite.com"],
    "Goodman Manufacturing": ["goodmanmfg.com"],

    # Plumbing, Fixtures & Piping
    "Kohler Co.": ["kohler.com"],
    "Kohler": ["kohler.com"],
    "Moen Incorporated": ["moen.com"],
    "Moen": ["moen.com"],
    "Delta Faucet Company": ["deltafaucet.com"],
    "Delta Faucet": ["deltafaucet.com"],
    "Charlotte Pipe and Foundry": ["charlottepipe.com"],
    "Sloan Valve Company": ["sloan.com"],
    "Oatey": ["oatey.com"],

    # Electrical, Power Distribution & Automation
    "Schneider Electric": ["se.com", "schneider-electric.com"],
    "Square D": ["se.com"],
    "Eaton Corporation": ["eaton.com"],
    "Eaton": ["eaton.com"],
    "ABB Ltd": ["abb.com"],
    "ABB": ["abb.com"],
    "Siemens Industry": ["siemens.com"],
    "Siemens": ["siemens.com"],
    "Hubbell Incorporated": ["hubbell.com"],
    "Hubbell": ["hubbell.com"],

    # Consumer Appliances & Electronics (Unilog Sample Output Dataset)
    "Appliance Dealers Cooperative": ["frigidaire.com", "whirlpool.com", "geappliances.com"],
    "Frigidaire": ["frigidaire.com"],
    "Whirlpool Corporation": ["whirlpool.com"],
    "Whirlpool": ["whirlpool.com"],
    # Fasteners, Anchors & Structural Hardware
    "Simpson Strong-Tie": ["strongtie.com"],
    "Hilti": ["hilti.com", "hilti.group"],
    "Unbrako": ["unbrako.com"],
    "Holo-Krome": ["holo-krome.com"],

    # Bearings & Power Transmission
    "SKF": ["skf.com"],
    "Timken": ["timken.com"],
    "NSK": ["nsk.com", "nskamericas.com"],
    "Gates": ["gates.com"],
    "Regal Rexnord": ["regalrexnord.com"],

    # Sensors, Vision & Industrial Instrumentation
    "Keyence": ["keyence.com"],
    "Banner Engineering": ["bannerengineering.com"],
    "Sick": ["sick.com"],
    "IFM Efector": ["ifm.com"],
    "Turck": ["turck.us", "turck.com"],

    # Welding, Cutting & Workplace Safety
    "Lincoln Electric": ["lincolnelectric.com"],
    "Miller Electric": ["millerwelds.com"],
    "Hypertherm": ["hypertherm.com"],
    "MSA Safety": ["msasafety.com"],
    "Ansell": ["ansell.com"],
}

# Reverse lookup: registered domain -> canonical manufacturer name, built
# once at import time. Used to recognize a manufacturer from a search result
# link even when the raw input's manufacturer/distributor field gave no
# usable domain.
_DOMAIN_TO_MANUFACTURER: dict[str, str] = {
    domain: name for name, domains in MANUFACTURER_DOMAINS.items() for domain in domains
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
    # Real label/value pairs parsed from the fetched datasheet's own text —
    # only populated when a genuine PDF was fetched and parsed (see
    # extract_pdf_attributes). Never fabricated: absent means nothing was
    # confidently extracted, not that extraction was skipped.
    extracted_attributes: tuple[tuple[str, str], ...] = ()
    # The visible page text surrounding the part number, captured when the
    # source was verified. This is the receipt: it lets a reader confirm the
    # match on the real page instead of trusting a boolean.
    match_snippet: str | None = None

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
            "match_snippet": self.match_snippet,
            "confidence": self.confidence,
            "extracted_attributes": [
                {"label": label, "value": value} for label, value in self.extracted_attributes
            ],
        }


@dataclass
class SourceDiscoveryResult:
    """Result of source discovery for one product."""
    manufacturer: str
    part_number: str
    sources: list[DiscoveredSource] = field(default_factory=list)
    blocked_urls: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    discovery_mode: str = "simulated"
    # Set when the raw manufacturer/distributor field didn't map to a known
    # domain, but a real web search identified the actual manufacturer via a
    # search-result link matching a known manufacturer domain. This is the
    # real manufacturer name — different from `manufacturer` above, which is
    # whatever the raw input said (often a distributor, not a manufacturer).
    resolved_manufacturer: str | None = None

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
            "discovery_mode": self.discovery_mode,
            "resolved_manufacturer": self.resolved_manufacturer,
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
    """Generate unverified source candidates for prototype/testing.

    These URLs are candidates only. They are never fetched and must not be
    represented as verified evidence or used to support automatic publication.
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


# ---------------------------------------------------------------------------
# Live source discovery — real HTTP fetches against manufacturer domains
# ---------------------------------------------------------------------------

_LIVE_FETCH_USER_AGENT = (
    "Mozilla/5.0 (compatible; SpecLedgerBot/1.0; "
    "+https://github.com/Yashasm18/specledger) enrichment research bot"
)
_PDF_LINK_RE = re.compile(
    r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def extract_match_snippet(page_html: str, pn_variants: set[str], window: int = 90) -> str | None:
    """Return the human-readable text surrounding the part number on a page.

    Confirming a part number appears on a manufacturer's page is what makes a
    source VERIFIED, but the boolean alone asks the reader to take our word
    for it. Returning the sentence it was found in makes the claim checkable:
    open the URL, search the page, see the same text.

    Matches against visible text, not raw HTML, so a hit inside a script blob
    or meta tag doesn't produce a snippet nobody can find on the page.
    """
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page_html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\s+", " ", _strip_tags(text)).strip()
    lowered = text.lower()

    for variant in sorted(pn_variants, key=len, reverse=True):
        index = lowered.find(variant)
        if index == -1:
            continue
        start = max(0, index - window)
        end = min(len(text), index + len(variant) + window)
        snippet = text[start:end].strip()
        if not snippet:
            continue
        return f"{'…' if start > 0 else ''}{snippet}{'…' if end < len(text) else ''}"
    return None


def _find_datasheet_link(page_html: str, page_url: str) -> str | None:
    """Look for a linked PDF whose href or link text suggests a datasheet/spec."""
    for href, link_text in _PDF_LINK_RE.findall(page_html):
        haystack = f"{href} {_strip_tags(link_text)}".lower()
        if any(kw in haystack for kw in ("datasheet", "data-sheet", "spec", "specification")):
            return urljoin(page_url, href)
    return None


# Matches "Label: Value" lines typical of datasheet spec tables once PyMuPDF
# flattens the PDF to plain text — e.g. "Voltage Rating: 120 V". Deliberately
# narrow: the label must look like a short Title-Case spec term (1-4 words,
# each starting uppercase), not a fragment of a sentence. Marketing/manual
# prose routinely contains colons and hyphens too ("During assembly of the
# advanced-geometry design..."), so a loose pattern turns brochure PDFs into
# noise; this only fires on genuine label/value rows and yields zero
# attributes for prose-only or photo-heavy PDFs, which is the honest result.
_PDF_ATTRIBUTE_LINE_RE = re.compile(
    r"^([A-Z][A-Za-z0-9/()]*(?:[ \-][A-Z][A-Za-z0-9/()]*){0,3}):\s+(.{1,60})$"
)
_PDF_NOISE_LABELS = frozenset({
    "page", "copyright", "phone", "fax", "email", "website", "note", "notes",
})


def extract_pdf_attributes(pdf_bytes: bytes, max_attributes: int = 20) -> tuple[tuple[str, str], ...]:
    """Best-effort real attribute extraction from a fetched PDF's own text.

    Uses PyMuPDF to flatten the PDF to plain text, then a conservative
    "Label: Value" line regex to pull out spec-sheet-style rows. This is
    genuine extraction from the PDF's real content — not a lookup table or
    template — but PDF text layout is inherently unreliable (multi-column
    tables often interleave), so this only catches datasheets with a
    simple label/value line format. Returns an empty tuple rather than
    fabricating anything when nothing matches.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ()

    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "\n".join(page.get_text("text") for page in document)
        document.close()
    except Exception:
        return ()

    attributes: list[tuple[str, str]] = []
    seen_labels: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) > 120:
            continue
        match = _PDF_ATTRIBUTE_LINE_RE.match(line)
        if not match:
            continue
        label = match.group(1).strip()
        value = match.group(2).strip()
        label_key = label.lower()
        if not label or not value or label_key in _PDF_NOISE_LABELS or label_key in seen_labels:
            continue
        if "http" in value.lower() or len(value.split()) > 8:
            continue
        if value.endswith((".", ",", ";")) or value[0].islower():
            continue
        seen_labels.add(label_key)
        attributes.append((label, value))
        if len(attributes) >= max_attributes:
            break
    return tuple(attributes)


_SERPER_SEARCH_URL = "https://google.serper.dev/search"


def search_manufacturer(part_number: str, description: str = "", timeout: float = 8.0) -> tuple[str, str] | None:
    """Identify the real manufacturer for a part via a real web search, for
    the common case where the raw input's manufacturer field is actually a
    distributor (e.g. "Appliance Dealers Cooperative") rather than the true
    manufacturer, so direct-domain URL guessing has nothing to guess against.

    Requires SERPER_API_KEY (https://serper.dev). Only returns a result when
    an organic search hit links to a domain already in MANUFACTURER_DOMAINS —
    this never invents a manufacturer name from search snippet text, it only
    recognizes domains we already treat as authoritative. Returns None (not
    a guess) when no such match is found or the API key isn't configured.
    """
    import os
    import requests

    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return None

    query = f"{part_number} {description}".strip()
    try:
        resp = requests.post(
            _SERPER_SEARCH_URL,
            json={"q": query, "num": 10},
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.info("Manufacturer search failed for %r: %s", query, exc)
        return None

    if resp.status_code != 200:
        return None

    for item in resp.json().get("organic", []):
        url = item.get("link", "")
        if not url or is_blocked_source(url):
            continue
        domain = extract_domain(url)
        manufacturer_name = _DOMAIN_TO_MANUFACTURER.get(domain)
        if manufacturer_name is None:
            # Also match subdomains of a known domain (e.g. shop.acme.com).
            for known_domain, name in _DOMAIN_TO_MANUFACTURER.items():
                if domain.endswith("." + known_domain):
                    manufacturer_name = name
                    break
        if manufacturer_name:
            return manufacturer_name, url
    return None


def prioritise_candidates(candidates: list[str]) -> list[str]:
    """Order candidate URLs so the ones that can actually verify come first.

    A search-endpoint URL can never yield a VERIFIED source: the fetch logic
    deliberately rejects pages that merely echo the query back, since that
    proves the search box works rather than that the product exists. Trying
    them ahead of product-page patterns spends the time budget on candidates
    that are guaranteed to fail, which is how a part with a real product page
    on the second registered domain ends up unverified.
    """
    def is_search(url: str) -> bool:
        lowered = url.lower()
        return "/search" in lowered or "q=" in lowered or "query=" in lowered

    return [u for u in candidates if not is_search(u)] + [u for u in candidates if is_search(u)]


def _fetch_and_verify(
    candidates: list[str],
    manufacturer: str,
    part_number: str,
    pn_variants: set[str],
    headers: dict[str, str],
    timeout: float,
    result: SourceDiscoveryResult,
    deadline: float | None = None,
) -> bool:
    """Fetch each candidate URL, append real DiscoveredSource records to
    `result`, and return True as soon as one is genuinely VERIFIED (part
    number found on a real, non-search page).

    `deadline` is an absolute time.monotonic() budget. Without one, a
    manufacturer with two registered domains produces eight candidates, and
    eight unresponsive hosts at the full timeout each is over a minute of
    waiting — unusable for anything interactive. Stopping at the budget
    reports what was actually found by then rather than blocking the caller.
    """
    import requests

    for url in candidates:
        if deadline is not None and time.monotonic() >= deadline:
            logger.info("Live fetch budget exhausted before trying %s", url)
            break
        if is_blocked_source(url):
            result.blocked_urls.append(url)
            continue
        try:
            start = time.time()
            resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            latency_ms = (time.time() - start) * 1000
        except requests.RequestException as exc:
            logger.info("Live fetch failed for %s: %s", url, exc)
            continue

        if resp.status_code != 200:
            continue
        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type:
            continue

        page_html = resp.text[:300_000]
        page_lower = page_html.lower()
        pn_in_page = any(v in page_lower for v in pn_variants)

        # Search/query result pages routinely echo the query string back into
        # the page (e.g. a "searchResults":[] state blob still containing the
        # term you searched for) — that is not evidence the product exists,
        # just proof the search box worked. Only a direct product-page fetch
        # that mentions the part number counts as verified.
        final_path = urlparse(resp.url).path.lower()
        is_search_endpoint = "search" in final_path or "q=" in resp.url.lower() or "query=" in resp.url.lower()
        found_pn = pn_in_page and not is_search_endpoint

        title_match = _TITLE_RE.search(page_html)
        title = _strip_tags(title_match.group(1)).strip()[:200] if title_match else None

        if found_pn:
            status, confidence = SourceStatus.VERIFIED, 0.9
        elif pn_in_page:
            # Found on a search/query page only — real page, unconfirmed match.
            status, confidence = SourceStatus.FETCHED, 0.2
        else:
            status, confidence = SourceStatus.FETCHED, 0.1

        result.sources.append(DiscoveredSource(
            url=resp.url,
            source_type=classify_source_type(resp.url),
            status=status,
            manufacturer=manufacturer,
            part_number=part_number,
            domain=extract_domain(resp.url),
            title=title,
            content_hash=hashlib.sha256(page_html.encode("utf-8", errors="ignore")).hexdigest()[:16],
            discovered_at=time.time(),
            fetch_latency_ms=round(latency_ms, 1),
            confidence=confidence,
            match_snippet=extract_match_snippet(page_html, pn_variants) if pn_in_page else None,
        ))

        if found_pn:
            datasheet_url = _find_datasheet_link(page_html, resp.url)
            if datasheet_url and not is_blocked_source(datasheet_url):
                try:
                    pdf_start = time.time()
                    pdf_resp = requests.get(datasheet_url, headers=headers, timeout=timeout)
                    pdf_latency_ms = (time.time() - pdf_start) * 1000
                    if pdf_resp.status_code == 200 and "pdf" in pdf_resp.headers.get("content-type", "").lower():
                        extracted = extract_pdf_attributes(pdf_resp.content)
                        result.sources.append(DiscoveredSource(
                            url=pdf_resp.url,
                            source_type=SourceType.SPECIFICATION_SHEET,
                            status=SourceStatus.FETCHED,
                            manufacturer=manufacturer,
                            part_number=part_number,
                            domain=extract_domain(pdf_resp.url),
                            title=f"{manufacturer} {part_number} datasheet",
                            content_hash=hashlib.sha256(pdf_resp.content).hexdigest()[:16],
                            discovered_at=time.time(),
                            fetch_latency_ms=round(pdf_latency_ms, 1),
                            confidence=0.85 if extracted else 0.75,
                            extracted_attributes=extracted,
                        ))
                except requests.RequestException as exc:
                    logger.info("Datasheet fetch failed for %s: %s", datasheet_url, exc)
            return True  # A verified product page is enough; stop scanning more candidates.

    return False


def discover_sources_live(
    manufacturer: str,
    part_number: str,
    description: str = "",
    timeout: float = 6.0,
    budget_seconds: float | None = None,
) -> SourceDiscoveryResult:
    """Discover sources via real HTTP requests to the manufacturer's own domain(s).

    Unlike discover_sources_simulated, this never fabricates evidence: a
    product page is only marked VERIFIED if the part number actually appears
    in the fetched page content, and rows where nothing real is found come
    back with an empty source list rather than a plausible-looking guess.
    """
    result = SourceDiscoveryResult(manufacturer=manufacturer, part_number=part_number, discovery_mode="live")
    result.search_queries = build_search_queries(manufacturer, part_number)
    deadline = time.monotonic() + budget_seconds if budget_seconds else None

    headers = {"User-Agent": _LIVE_FETCH_USER_AGENT}
    clean_pn = part_number.strip()
    pn_variants = {v for v in {
        clean_pn.lower(),
        clean_pn.lower().replace(" ", ""),
        clean_pn.lower().replace(" ", "-"),
        clean_pn.lower().replace("-", ""),
    } if v}

    domains = MANUFACTURER_DOMAINS.get(manufacturer, [])
    if domains:
        candidates = prioritise_candidates(build_direct_urls(manufacturer, part_number))
        verified = _fetch_and_verify(
            candidates, manufacturer, part_number, pn_variants, headers, timeout, result, deadline,
        )
        if verified:
            return result

    if deadline is not None and time.monotonic() >= deadline:
        return result

    # Either the raw manufacturer/distributor field had no known domain, or
    # guessing standard URL patterns against it didn't turn up a verified
    # match (e.g. "Appliance Dealers Cooperative" maps to 3 real brand
    # domains, but none of them use the generic /product/{sku} URL shape).
    # Fall back to a real web search to identify — and directly link to —
    # the actual manufacturer page, if SERPER_API_KEY is configured.
    found = search_manufacturer(part_number, description, timeout)
    if found is None:
        return result
    resolved_name, search_hit_url = found
    result.resolved_manufacturer = resolved_name
    search_candidates = [search_hit_url] + prioritise_candidates(build_direct_urls(resolved_name, part_number))
    _fetch_and_verify(
        search_candidates, manufacturer, part_number, pn_variants, headers, timeout, result, deadline,
    )
    return result


def discover_sources_live_batch(
    rows: Sequence[tuple[str, str, str]],
    max_workers: int = 8,
    timeout: float = 6.0,
) -> dict[tuple[str, str], SourceDiscoveryResult]:
    """Concurrently run discover_sources_live for the unique
    (manufacturer, part_number, description) triples in `rows`. Real network
    calls, so this runs a thread pool rather than processing rows one at a
    time. Keyed by (manufacturer, part_number) since that's what callers
    look results up by; description is only used to build the search query."""
    unique_triples = list({(m.strip(), p.strip(), d.strip()) for m, p, d in rows if m.strip() and p.strip()})
    results: dict[tuple[str, str], SourceDiscoveryResult] = {}
    if not unique_triples:
        return results

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(discover_sources_live, mfr, pn, desc, timeout): (mfr, pn)
            for mfr, pn, desc in unique_triples
        }
        for future in as_completed(future_map):
            key = future_map[future]
            try:
                results[key] = future.result()
            except Exception as exc:
                logger.exception("Live source discovery failed for %s", key)
                results[key] = SourceDiscoveryResult(manufacturer=key[0], part_number=key[1], discovery_mode="live")

    return results
