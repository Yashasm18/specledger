"""Deterministic, evidence-preserving extraction of common industrial facts."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ExtractedFact:
    name: str
    value: str
    page: int
    evidence: str
    status: str = "inferred"
    confidence: float = 0.85
    normalized_value: str | None = None
    normalized_unit: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_REQUIRED_ATTRIBUTES = frozenset({"size", "pressure_rating", "material"})


def validate_facts(facts: list[ExtractedFact], required: frozenset[str] = DEFAULT_REQUIRED_ATTRIBUTES) -> list[dict]:
    """Return deterministic review issues without silently changing source values."""
    issues: list[dict] = []
    grouped: dict[str, list[ExtractedFact]] = {}
    for fact in facts:
        grouped.setdefault(fact.name, []).append(fact)
        if not fact.value.strip():
            issues.append({"code": "EMPTY_VALUE", "attribute": fact.name, "severity": "error",
                           "message": "Extracted value is empty"})
    for name, values in grouped.items():
        distinct = {value.value.casefold() for value in values}
        if len(distinct) > 1:
                issues.append({"code": "SOURCE_CONFLICT", "attribute": name, "severity": "error",
                           "message": f"Multiple source values found for {name}",
                           "pages": sorted(value.page for value in values)})
    for name in sorted(required - grouped.keys()):
        issues.append({"code": "MISSING_REQUIRED", "attribute": name, "severity": "error",
                       "message": f"Required catalogue attribute '{name}' was not found"})
    return issues


PATTERNS = (
    ("pressure_rating", re.compile(r"(?:pressure\s*(?:rating|class)?|class)\s*[:#-]?\s*([0-9]+(?:\s*[-/]\s*[0-9]+)?\s*(?:psi|bar|wog|class)?\b)", re.I)),
    ("size", re.compile(r"(?:size|diameter|dia\.?|dn)\s*[:#-]?\s*(dn\s*)?([0-9]+(?:\s*[x×/]\s*[0-9]+)?\s*(?:mm|in|inch|inches)?\b)", re.I)),
    ("material", re.compile(r"(?:material|body\s*material|construction)\s*[:#-]?\s*([A-Za-z][A-Za-z0-9 .-]{2,40})", re.I)),
)


def extract_facts(pages: list[dict] | tuple[dict, ...]) -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []
    for page in pages:
        text = page["text"]
        for name, pattern in PATTERNS:
            match = pattern.search(text)
            if match:
                # The size pattern has an optional ``DN`` prefix in group 1
                # and the numeric size in group 2. Preserve the full useful
                # value instead of returning only the prefix.
                value = ((match.group(1) or "") + match.group(2) if name == "size" else match.group(1)).strip()
                evidence = text[max(0, match.start() - 30):min(len(text), match.end() + 30)].strip()
                normalized_value, normalized_unit = normalize_value(name, value)
                facts.append(ExtractedFact(name, value, page["page"], evidence,
                                           normalized_value=normalized_value,
                                           normalized_unit=normalized_unit))
    return facts


def normalize_value(name: str, value: str) -> tuple[str | None, str | None]:
    """Create a comparison-safe value while retaining the supplier's raw value."""
    compact = re.sub(r"\s+", " ", value.strip()).casefold()
    if name == "pressure_rating":
        match = re.fullmatch(r"([0-9]+(?:\s*[-/]\s*[0-9]+)?)\s*(psi|bar|wog|class)?", compact)
        if match:
            return re.sub(r"\s*", "", match.group(1)), match.group(2) or None
    if name == "size":
        match = re.fullmatch(r"(?:dn\s*)?([0-9]+(?:\s*[x×/]\s*[0-9]+)?)\s*(mm|in|inch|inches)?", compact)
        if match:
            unit = match.group(2)
            unit = "in" if unit in {"inch", "inches"} else unit
            return re.sub(r"\s*", "", match.group(1)), unit
    if name == "material":
        return compact, None
    return None, None
