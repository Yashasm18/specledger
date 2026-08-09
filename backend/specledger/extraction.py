"""Deterministic first-pass industrial attribute extraction.

This is intentionally conservative. It returns only facts that have visible
text evidence; uncertain enrichment belongs to a later AI stage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .worker import ExtractedDocument


@dataclass(frozen=True)
class ExtractedFact:
    name: str
    value: str | float
    unit: str | None
    page: int
    evidence: str


PATTERNS = (
    ("pressure_rating", re.compile(r"pressure\s*(?:rating)?\s*[:=-]?\s*(\d+(?:\.\d+)?)\s*(WOG|PSI|bar)", re.I)),
    ("size", re.compile(r"(?:size|nominal\s+size)\s*[:=-]?\s*(\d+(?:\.\d+)?)\s*(in|inch|mm|DN\s*\d+)", re.I)),
    ("material", re.compile(r"material\s*[:=-]?\s*([A-Za-z][A-Za-z -]{1,40})", re.I)),
)


def extract_facts(document: ExtractedDocument) -> tuple[ExtractedFact, ...]:
    facts: list[ExtractedFact] = []
    for page in document.pages:
        for name, pattern in PATTERNS:
            match = pattern.search(page.text)
            if not match:
                continue
            raw_value = match.group(1).strip()
            value: str | float = float(raw_value) if raw_value.replace(".", "", 1).isdigit() else raw_value
            unit = match.group(2).strip() if match.lastindex and match.lastindex >= 2 else None
            facts.append(ExtractedFact(name, value, unit, page.page, match.group(0)))
    return tuple(facts)
