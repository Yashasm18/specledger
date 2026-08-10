"""Unit-of-measure normalization for industrial product attributes.

Every UOM is normalized to a canonical form while preserving the original
supplier-provided value. The system never silently converts between
incompatible dimensions (e.g., treating pressure as length). If the raw
unit is unrecognized, the system preserves it and flags it for review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedUOM:
    """Result of normalizing a raw unit-of-measure string."""
    raw: str
    canonical: str
    dimension: str  # "length", "pressure", "temperature", "weight", "volume", "angle", "none"
    confidence: float

    @property
    def recognized(self) -> bool:
        return self.confidence > 0.0


# ---------------------------------------------------------------------------
# UOM tables — canonical form, dimension, and known aliases.
# Sorted by dimension for readability.
# ---------------------------------------------------------------------------

_UOM_TABLE: list[tuple[str, str, list[str]]] = [
    # Length
    ("in", "length", ["in", "inch", "inches", '"', "in."]),
    ("ft", "length", ["ft", "foot", "feet", "ft."]),
    ("mm", "length", ["mm", "millimeter", "millimeters", "millimetre", "millimetres"]),
    ("cm", "length", ["cm", "centimeter", "centimeters", "centimetre", "centimetres"]),
    ("m", "length", ["m", "meter", "meters", "metre", "metres"]),

    # Diameter designators
    ("DN", "length", ["dn"]),
    ("NPS", "length", ["nps", "nominal pipe size"]),

    # Pressure
    ("psi", "pressure", ["psi", "lbf/in2", "lbf/in²", "lb/in2", "pounds per square inch"]),
    ("bar", "pressure", ["bar", "bars"]),
    ("kPa", "pressure", ["kpa", "kilopascal", "kilopascals"]),
    ("MPa", "pressure", ["mpa", "megapascal", "megapascals"]),
    ("WOG", "pressure", ["wog", "water oil gas"]),
    ("CWP", "pressure", ["cwp", "cold working pressure"]),
    ("SWP", "pressure", ["swp", "steam working pressure"]),
    ("class", "pressure", ["class", "cl", "ansi class"]),

    # Temperature
    ("°F", "temperature", ["f", "°f", "deg f", "degrees f", "fahrenheit", "degrees fahrenheit"]),
    ("°C", "temperature", ["c", "°c", "deg c", "degrees c", "celsius", "degrees celsius", "centigrade"]),
    ("K", "temperature", ["k", "kelvin"]),

    # Weight / Mass
    ("lb", "weight", ["lb", "lbs", "pound", "pounds", "lb."]),
    ("kg", "weight", ["kg", "kilogram", "kilograms", "kgs"]),
    ("g", "weight", ["g", "gram", "grams"]),
    ("oz", "weight", ["oz", "ounce", "ounces"]),

    # Volume / Flow
    ("gal", "volume", ["gal", "gallon", "gallons"]),
    ("L", "volume", ["l", "liter", "liters", "litre", "litres"]),
    ("GPM", "volume", ["gpm", "gallons per minute", "gal/min"]),
    ("LPM", "volume", ["lpm", "liters per minute", "l/min", "litres per minute"]),
    ("CFM", "volume", ["cfm", "cubic feet per minute", "ft3/min", "ft³/min"]),

    # Angle / Thread
    ("NPT", "angle", ["npt", "national pipe thread", "national pipe taper"]),
    ("BSP", "angle", ["bsp", "british standard pipe"]),
    ("BSPT", "angle", ["bspt", "british standard pipe taper"]),
    ("FNPT", "angle", ["fnpt", "female npt"]),
    ("MNPT", "angle", ["mnpt", "male npt"]),
]

# Build lookup index
_UOM_INDEX: dict[str, tuple[str, str]] = {}
for _canonical, _dimension, _aliases in _UOM_TABLE:
    for _alias in _aliases:
        _UOM_INDEX[_alias.casefold().strip()] = (_canonical, _dimension)


def normalize_uom(raw: str) -> NormalizedUOM:
    """Normalize a raw unit-of-measure string to its canonical form.

    Returns a NormalizedUOM with confidence 1.0 for exact matches,
    0.0 for unrecognized units (preserved as-is for human review).
    """
    if not raw or not raw.strip():
        return NormalizedUOM(raw, "", "none", 0.0)

    cleaned = re.sub(r"\s+", " ", raw.strip()).casefold()

    # Direct lookup
    result = _UOM_INDEX.get(cleaned)
    if result:
        return NormalizedUOM(raw, result[0], result[1], 1.0)

    # Try without trailing period or plural 's'
    stripped = cleaned.rstrip(".").rstrip("s")
    result = _UOM_INDEX.get(stripped)
    if result:
        return NormalizedUOM(raw, result[0], result[1], 0.90)

    # Unrecognized — preserve raw, flag for review
    return NormalizedUOM(raw, raw.strip(), "none", 0.0)


# ---------------------------------------------------------------------------
# Material normalization — controlled vocabulary for common materials
# ---------------------------------------------------------------------------

MATERIAL_CANONICAL: dict[str, str] = {
    "brass": "Brass",
    "bronze": "Bronze",
    "cast iron": "Cast Iron",
    "ci": "Cast Iron",
    "carbon steel": "Carbon Steel",
    "cs": "Carbon Steel",
    "stainless steel": "Stainless Steel",
    "stainless": "Stainless Steel",
    "ss": "Stainless Steel",
    "ss304": "Stainless Steel 304",
    "ss316": "Stainless Steel 316",
    "304 stainless": "Stainless Steel 304",
    "304 stainless steel": "Stainless Steel 304",
    "304 ss": "Stainless Steel 304",
    "304ss": "Stainless Steel 304",
    "316 stainless": "Stainless Steel 316",
    "316 stainless steel": "Stainless Steel 316",
    "316 ss": "Stainless Steel 316",
    "316ss": "Stainless Steel 316",
    "ductile iron": "Ductile Iron",
    "di": "Ductile Iron",
    "pvc": "PVC",
    "cpvc": "CPVC",
    "ptfe": "PTFE",
    "teflon": "PTFE",
    "copper": "Copper",
    "aluminum": "Aluminum",
    "aluminium": "Aluminum",
    "alloy steel": "Alloy Steel",
    "chrome moly": "Chrome Moly Steel",
    "inconel": "Inconel",
    "monel": "Monel",
    "hastelloy": "Hastelloy",
    "titanium": "Titanium",
    "cast steel": "Cast Steel",
    "forged steel": "Forged Steel",
    "wc": "WC (Tungsten Carbide)",
    "nylon": "Nylon",
    "polypropylene": "Polypropylene",
    "pp": "Polypropylene",
}


@dataclass(frozen=True)
class NormalizedMaterial:
    raw: str
    canonical: str
    confidence: float


def normalize_material(raw: str) -> NormalizedMaterial:
    """Normalize a material name to its canonical form."""
    if not raw or not raw.strip():
        return NormalizedMaterial(raw, "", 0.0)

    cleaned = re.sub(r"\s+", " ", raw.strip()).casefold()
    canonical = MATERIAL_CANONICAL.get(cleaned)
    if canonical:
        return NormalizedMaterial(raw, canonical, 1.0)

    # Try without hyphens/extra punctuation
    simplified = re.sub(r"[^a-z0-9 ]+", " ", cleaned).strip()
    simplified = re.sub(r"\s+", " ", simplified)
    canonical = MATERIAL_CANONICAL.get(simplified)
    if canonical:
        return NormalizedMaterial(raw, canonical, 0.90)

    # Substring match (e.g., "303 stainless steel alloy" contains "stainless steel")
    for key, value in MATERIAL_CANONICAL.items():
        if key in simplified or simplified in key:
            return NormalizedMaterial(raw, value, 0.80)

    return NormalizedMaterial(raw, raw.strip(), 0.0)
