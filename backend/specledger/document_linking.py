"""Connect an uploaded datasheet to the catalogue row it describes.

Extraction produces typed facts with page-level evidence; until now those
facts never reached a product record. The link is the part number. A
datasheet that names one is talking about a specific row; a datasheet that
names none is talking about nothing this catalogue holds, and says so.

Two rules keep this honest:

* **Matching is exact.** A fuzzy match that hangs a 2-inch valve's
  specifications on a 1/2-inch valve is worse than no match, because the
  result looks verified. Separator and case differences are tolerated
  because "70-104-01" and "7010401" are the same part written twice; a
  digit difference is a different product and never matches.

* **Nothing is applied.** A linked fact is a *proposal* carrying the page
  and sentence it came from. A human applies or dismisses it. This is the
  same division of labour as the rest of the system: the deterministic
  tier finds the candidate for free, and the scarce resource decides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .extraction import ExtractedFact


# The part number identifies the row; proposing it back onto the row it
# just selected would be circular.
_KEY_FACT = "part_number"

_SEPARATORS = re.compile(r"[^A-Za-z0-9]+")


@dataclass(frozen=True)
class DocumentLink:
    """A datasheet and the catalogue row it describes."""
    batch_id: str
    row_number: int
    part_number: str
    match_type: str  # "exact" | "normalized"


def normalize_part_number(value: str) -> str:
    """A comparison-safe form: case and separators do not distinguish parts."""
    return _SEPARATORS.sub("", str(value or "")).casefold()


def find_matching_rows(
    facts: Sequence[ExtractedFact] | Iterable[ExtractedFact],
    catalogue_rows: Iterable[Mapping],
) -> list[DocumentLink]:
    """Link a document's part numbers to catalogue rows.

    ``catalogue_rows`` is any iterable of mappings carrying ``batch_id``,
    ``row_number`` and ``part_number``. Returns one link per matched row,
    in the order the rows were supplied.
    """
    wanted: dict[str, str] = {}
    for fact in facts:
        if fact.name != _KEY_FACT:
            continue
        raw = str(fact.value or "").strip()
        if raw:
            wanted.setdefault(normalize_part_number(raw), raw)
    if not wanted:
        return []

    links: list[DocumentLink] = []
    seen: set[tuple[str, int]] = set()
    for row in catalogue_rows:
        row_part = str(row.get("part_number") or "").strip()
        if not row_part:
            continue
        key = normalize_part_number(row_part)
        if key not in wanted:
            continue
        identity = (str(row.get("batch_id")), int(row.get("row_number")))
        if identity in seen:
            continue
        seen.add(identity)
        # Same characters, or only case and separators apart.
        exact = row_part.casefold() == wanted[key].casefold()
        links.append(DocumentLink(
            batch_id=identity[0],
            row_number=identity[1],
            part_number=row_part,
            match_type="exact" if exact else "normalized",
        ))
    return links


def proposals_from_facts(facts: Iterable[ExtractedFact]) -> list[dict]:
    """Turn extracted specifications into reviewable proposals.

    Every proposal keeps the page and the sentence it came from, so a
    reviewer can check the claim against the document rather than trusting
    the extractor.
    """
    proposals: list[dict] = []
    for fact in facts:
        if fact.name == _KEY_FACT:
            continue
        proposals.append({
            "name": fact.name,
            "value": fact.value,
            "normalized_value": fact.normalized_value,
            "normalized_unit": fact.normalized_unit,
            "page": fact.page,
            "evidence": fact.evidence,
            "confidence": fact.confidence,
            # Never pre-applied. A human decides.
            "state": "proposed",
        })
    return proposals
