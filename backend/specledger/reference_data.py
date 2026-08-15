"""Canonical reference-data store for industrial product intelligence.

This module provides the foundation for LOV-constrained output. Every
manufacturer, brand, and controlled-vocabulary value must come from an
approved reference table. Unmatched values are preserved as-is and flagged
for human review — the system never invents a canonical name.

Reference data can be loaded from:
  1. Built-in synthetic seed data (safe for demos and tests)
  2. Private CSV/JSON files in ``data/reference/`` (gitignored)
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReferenceEntry:
    """A single canonical reference-data record with known aliases."""
    canonical: str
    aliases: frozenset[str] = frozenset()
    source: str = "seed"

    def all_forms(self) -> frozenset[str]:
        """Return canonical + aliases, all lowercased for matching."""
        return frozenset({self.canonical.casefold()} | {a.casefold() for a in self.aliases})


@dataclass(frozen=True)
class CanonicalMatch:
    """Result of matching a raw value against the reference store."""
    raw_value: str
    canonical: str
    confidence: float
    match_type: str  # "exact", "alias", "normalized", "none"
    entry_source: str = "seed"


def _normalize_for_comparison(value: str) -> str:
    """Create a stable comparison key: lowercase, collapse whitespace/punctuation."""
    return re.sub(r"[^a-z0-9]+", " ", value.strip().casefold()).strip()


# ---------------------------------------------------------------------------
# Built-in seed data — realistic industrial manufacturers, brands, and
# categories. These are public company names used purely for demo/test
# purposes. Private Unilog reference lists load from data/reference/.
# ---------------------------------------------------------------------------

SEED_MANUFACTURERS: list[dict] = [
    {"canonical": "Parker Hannifin", "aliases": ["Parker", "Parker Hannifin Corp", "Parker Hannifin Corporation", "Parker-Hannifin"]},
    {"canonical": "Emerson Electric", "aliases": ["Emerson", "Emerson Electric Co", "Emerson Electric Co."]},
    {"canonical": "Honeywell", "aliases": ["Honeywell International", "Honeywell Inc", "Honeywell International Inc"]},
    {"canonical": "Flowserve", "aliases": ["Flowserve Corporation", "Flowserve Corp"]},
    {"canonical": "Crane Co.", "aliases": ["Crane", "Crane Company", "Crane Co"]},
    {"canonical": "Watts Water Technologies", "aliases": ["Watts", "Watts Water", "Watts Water Tech"]},
    {"canonical": "Apollo Valves", "aliases": ["Apollo", "Apollo Valve", "Conbraco", "Conbraco Industries"]},
    {"canonical": "Nibco", "aliases": ["NIBCO Inc", "NIBCO Inc."]},
    {"canonical": "Milwaukee Valve", "aliases": ["Milwaukee", "Milwaukee Valve Company"]},
    {"canonical": "Kitz Corporation", "aliases": ["Kitz", "KITZ Corp"]},
    {"canonical": "Velan", "aliases": ["Velan Inc", "Velan Inc."]},
    {"canonical": "Cameron (Schlumberger)", "aliases": ["Cameron", "Cameron International", "Cameron Intl"]},
    {"canonical": "Pentair", "aliases": ["Pentair plc", "Pentair Inc"]},
    {"canonical": "ITT Inc.", "aliases": ["ITT", "ITT Corporation", "ITT Corp"]},
    {"canonical": "Bray International", "aliases": ["Bray", "Bray Intl", "Bray Controls"]},
    {"canonical": "Swagelok", "aliases": ["Swagelok Company"]},
    {"canonical": "Victaulic", "aliases": ["Victaulic Company"]},
    {"canonical": "Graco", "aliases": ["Graco Inc", "Graco Inc."]},
    {"canonical": "Grundfos", "aliases": ["Grundfos Pumps", "Grundfos Holding"]},
    {"canonical": "Xylem", "aliases": ["Xylem Inc", "Xylem Water Solutions"]},
    # Electrical, Power Distribution & Automation
    {"canonical": "Schneider Electric", "aliases": ["Square D", "Schneider Electric Corp", "Schneider Electric Corporation", "Schneider", "TeSys"]},
    {"canonical": "Leviton", "aliases": ["Leviton Mfg Co", "Leviton Manufacturing", "Leviton Manufacturing Co."]},
    {"canonical": "Eaton", "aliases": ["Eaton Corporation", "Eaton Corp", "Cutler-Hammer"]},
    {"canonical": "ABB", "aliases": ["ABB Inc", "ABB Ltd", "ABB Group"]},
    {"canonical": "Hubbell", "aliases": ["Hubbell Incorporated", "Hubbell Inc", "Kellems", "Wiring Device-Kellems"]},
    {"canonical": "Siemens", "aliases": ["Siemens Industry", "Siemens AG"]},
    # Abrasives, Cutting & Tools
    {"canonical": "Freud", "aliases": ["Freud Inc", "Freud Tools", "Diablo", "Diablo Tools"]},
    {"canonical": "3M", "aliases": ["3M Company", "3M Co", "3 M Co", "Cubitron", "Scotch-Brite"]},
    {"canonical": "Mirka", "aliases": ["Mirka Abrasives", "Mirka Abrasives Inc", "Mirka USA", "Abranet"]},
    {"canonical": "Milwaukee Tool", "aliases": ["Milwaukee", "Milwaukee Electric Tool", "Milwaukee Accessory"]},
    {"canonical": "DeWalt", "aliases": ["DEWALT", "DeWalt Industrial Tool Co", "Black & Decker/dewlt"]},
    {"canonical": "Makita", "aliases": ["Makita USA", "Makita Usa Inc"]},
    {"canonical": "Festool", "aliases": ["Festool USA", "Festool LLC"]},
]

SEED_BRANDS: list[dict] = [
    {"canonical": "Apollo", "aliases": ["Apollo Valves", "Apollo by Conbraco"], "manufacturer": "Apollo Valves"},
    {"canonical": "Sharpe", "aliases": ["Sharpe Valves"], "manufacturer": "Apollo Valves"},
    {"canonical": "Watts", "aliases": ["Watts Regulator"], "manufacturer": "Watts Water Technologies"},
    {"canonical": "NIBCO", "aliases": ["Nibco"], "manufacturer": "Nibco"},
    {"canonical": "Milwaukee", "aliases": ["Milwaukee Valve"], "manufacturer": "Milwaukee Valve"},
    {"canonical": "Kitz", "aliases": ["KITZ"], "manufacturer": "Kitz Corporation"},
    {"canonical": "Swagelok", "aliases": [], "manufacturer": "Swagelok"},
    {"canonical": "Victaulic", "aliases": [], "manufacturer": "Victaulic"},
    {"canonical": "Fisher", "aliases": ["Fisher Controls", "Fisher Valves"], "manufacturer": "Emerson Electric"},
    {"canonical": "DeltaV", "aliases": [], "manufacturer": "Emerson Electric"},
    {"canonical": "Bettis", "aliases": ["Bettis Actuators"], "manufacturer": "Emerson Electric"},
    {"canonical": "Autoclave Engineers", "aliases": ["AE", "Parker Autoclave"], "manufacturer": "Parker Hannifin"},
    {"canonical": "Grundfos", "aliases": ["Grundfos Pumps"], "manufacturer": "Grundfos"},
    {"canonical": "Goulds", "aliases": ["Goulds Pumps", "Goulds Water Technology"], "manufacturer": "Xylem"},
]

SEED_CATEGORIES: list[dict] = [
    {"canonical": "Ball Valve", "aliases": ["ball valve", "ball valves", "ball-valve"]},
    {"canonical": "Gate Valve", "aliases": ["gate valve", "gate valves"]},
    {"canonical": "Globe Valve", "aliases": ["globe valve", "globe valves"]},
    {"canonical": "Check Valve", "aliases": ["check valve", "check valves", "non-return valve"]},
    {"canonical": "Butterfly Valve", "aliases": ["butterfly valve", "butterfly valves"]},
    {"canonical": "Plug Valve", "aliases": ["plug valve", "plug valves"]},
    {"canonical": "Needle Valve", "aliases": ["needle valve", "needle valves"]},
    {"canonical": "Pressure Relief Valve", "aliases": ["pressure relief", "relief valve", "PRV", "safety valve"]},
    {"canonical": "Solenoid Valve", "aliases": ["solenoid valve", "solenoid"]},
    {"canonical": "Diaphragm Valve", "aliases": ["diaphragm valve", "diaphragm valves"]},
    {"canonical": "Centrifugal Pump", "aliases": ["centrifugal pump", "centrifugal pumps"]},
    {"canonical": "Pipe Fitting", "aliases": ["pipe fitting", "pipe fittings", "fitting", "fittings"]},
    {"canonical": "Elbow Fitting", "aliases": ["elbow", "pipe elbow", "90 degree elbow", "45 degree elbow"]},
    {"canonical": "Tee Fitting", "aliases": ["tee", "pipe tee", "tee fitting"]},
    {"canonical": "Coupling", "aliases": ["coupling", "pipe coupling", "couplings"]},
    {"canonical": "Union", "aliases": ["union", "pipe union", "unions"]},
    {"canonical": "Reducer", "aliases": ["reducer", "pipe reducer", "reducing coupling"]},
    {"canonical": "Flange", "aliases": ["flange", "pipe flange", "flanges"]},
]


class ReferenceStore:
    """In-memory reference-data store with canonical matching.

    Loads from built-in seed data by default. Private CSV/JSON files in
    ``data/reference/`` override or extend seed data when present.
    """

    def __init__(self, reference_dir: str | Path | None = None) -> None:
        self._manufacturers: list[ReferenceEntry] = []
        self._brands: list[ReferenceEntry] = []
        self._categories: list[ReferenceEntry] = []
        self._mfr_index: dict[str, ReferenceEntry] = {}
        self._brand_index: dict[str, ReferenceEntry] = {}
        self._category_index: dict[str, ReferenceEntry] = {}

        # Load built-in seed data
        self._load_seed()

        # Overlay private reference files if present
        if reference_dir is not None:
            self._load_directory(Path(reference_dir))

    # -- public matching API ------------------------------------------------

    def match_manufacturer(self, raw: str) -> CanonicalMatch:
        return self._match(raw, self._mfr_index, self._manufacturers)

    def match_brand(self, raw: str) -> CanonicalMatch:
        return self._match(raw, self._brand_index, self._brands)

    def match_category(self, raw: str) -> CanonicalMatch:
        return self._match(raw, self._category_index, self._categories)

    @property
    def manufacturer_count(self) -> int:
        return len(self._manufacturers)

    @property
    def brand_count(self) -> int:
        return len(self._brands)

    @property
    def category_count(self) -> int:
        return len(self._categories)

    # -- private helpers ----------------------------------------------------

    def _match(self, raw: str, index: dict[str, ReferenceEntry],
               entries: list[ReferenceEntry]) -> CanonicalMatch:
        if not raw or not raw.strip():
            return CanonicalMatch(raw, "", 0.0, "none")

        normalized = _normalize_for_comparison(raw)

        # 1. Exact index hit (canonical or alias, case-insensitive)
        entry = index.get(normalized)
        if entry is not None:
            confidence = 1.0 if normalized == _normalize_for_comparison(entry.canonical) else 0.95
            match_type = "exact" if confidence == 1.0 else "alias"
            return CanonicalMatch(raw, entry.canonical, confidence, match_type, entry.source)

        # 2. Normalized substring/containment match
        for entry in entries:
            canon_norm = _normalize_for_comparison(entry.canonical)
            if canon_norm in normalized or normalized in canon_norm:
                return CanonicalMatch(raw, entry.canonical, 0.80, "normalized", entry.source)

        # 3. No match — preserve raw, flag for review
        return CanonicalMatch(raw, "", 0.0, "none")

    def _build_index(self, entries: list[ReferenceEntry]) -> dict[str, ReferenceEntry]:
        index: dict[str, ReferenceEntry] = {}
        for entry in entries:
            for form in entry.all_forms():
                normalized = _normalize_for_comparison(form)
                if normalized:
                    index[normalized] = entry
        return index

    def _load_seed(self) -> None:
        self._manufacturers = [
            ReferenceEntry(m["canonical"], frozenset(m.get("aliases", [])), "seed")
            for m in SEED_MANUFACTURERS
        ]
        self._brands = [
            ReferenceEntry(b["canonical"], frozenset(b.get("aliases", [])), "seed")
            for b in SEED_BRANDS
        ]
        self._categories = [
            ReferenceEntry(c["canonical"], frozenset(c.get("aliases", [])), "seed")
            for c in SEED_CATEGORIES
        ]
        self._mfr_index = self._build_index(self._manufacturers)
        self._brand_index = self._build_index(self._brands)
        self._category_index = self._build_index(self._categories)

    def _load_directory(self, directory: Path) -> None:
        """Load private CSV/JSON reference files from a directory."""
        if not directory.is_dir():
            return
        for path in sorted(directory.iterdir()):
            if path.suffix.casefold() == ".json":
                self._load_json_file(path)
            elif path.suffix.casefold() == ".csv":
                self._load_csv_file(path)

    def _load_json_file(self, path: Path) -> None:
        """Load a JSON reference file.

        Expected format:
        {
          "type": "manufacturers" | "brands" | "categories",
          "entries": [{"canonical": "...", "aliases": [...]}]
        }
        """
        data = json.loads(path.read_text(encoding="utf-8"))
        ref_type = data.get("type", "")
        source = f"file:{path.name}"
        entries = [
            ReferenceEntry(e["canonical"], frozenset(e.get("aliases", [])), source)
            for e in data.get("entries", [])
        ]
        self._extend(ref_type, entries)

    def _load_csv_file(self, path: Path) -> None:
        """Load a CSV reference file.

        Expected columns: canonical, aliases (pipe-separated), source (optional).
        Filename prefix determines type: manufacturers_*, brands_*, categories_*.
        """
        ref_type = ""
        name_lower = path.stem.casefold()
        if name_lower.startswith("manufacturer"):
            ref_type = "manufacturers"
        elif name_lower.startswith("brand"):
            ref_type = "brands"
        elif name_lower.startswith("categor"):
            ref_type = "categories"
        if not ref_type:
            return

        source = f"file:{path.name}"
        entries: list[ReferenceEntry] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                canonical = (row.get("canonical") or "").strip()
                if not canonical:
                    continue
                aliases_raw = (row.get("aliases") or "").strip()
                aliases = frozenset(a.strip() for a in aliases_raw.split("|") if a.strip()) if aliases_raw else frozenset()
                entries.append(ReferenceEntry(canonical, aliases, source))
        self._extend(ref_type, entries)

    def _extend(self, ref_type: str, entries: list[ReferenceEntry]) -> None:
        if ref_type == "manufacturers":
            self._manufacturers.extend(entries)
            self._mfr_index = self._build_index(self._manufacturers)
        elif ref_type == "brands":
            self._brands.extend(entries)
            self._brand_index = self._build_index(self._brands)
        elif ref_type == "categories":
            self._categories.extend(entries)
            self._category_index = self._build_index(self._categories)
