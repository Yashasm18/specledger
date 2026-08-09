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

    def to_dict(self) -> dict:
        return asdict(self)


def validate_facts(facts: list[ExtractedFact]) -> list[dict]:
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
                value = match.group(1).strip()
                evidence = text[max(0, match.start() - 30):min(len(text), match.end() + 30)].strip()
                facts.append(ExtractedFact(name, value, page["page"], evidence))
    return facts
