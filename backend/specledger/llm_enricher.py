"""Optional LLM tier for rows the deterministic pipeline could not resolve.

This runs *after* deterministic enrichment, never instead of it, and only on
the residue: rows whose category fell through every keyword branch into the
generic bucket. On the official 1,000-row dataset that is roughly 40% of
rows — real, measurable, and exactly the "difficult interpretation" case
keyword matching is bad at.

Three properties keep this compatible with the rest of the system:

1. **Bounded cost.** Products are batched into a single request (default 25
   per call), so ~400 unresolved rows cost ~16 calls rather than 400. The
   deterministic path still handles everything it can at zero cost; the LLM
   only sees what is left. Token counts come back from the API and are
   reported as measured; the per-token *rate* is configuration, not a
   measurement, and is labelled as such wherever it surfaces.

2. **Never authoritative.** Everything produced here is marked
   ``ai_inferred`` and routed to human review. It cannot auto-approve, and
   it never overwrites a value deterministic rules already resolved.

3. **Never load-bearing.** With no API key the module is inert and the
   pipeline behaves exactly as before. Network errors, timeouts and
   malformed responses degrade to "no suggestion" rather than failing an
   ingest.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

import requests


# The classpath _infer_taxonomy() falls back to when no keyword branch hits.
# Rows carrying this are the only ones eligible for the LLM tier.
GENERIC_CLASSPATH = "Industrial Supplies > Maintenance"

# The controlled vocabulary the model must choose from. Keeping the model
# inside the taxonomy the deterministic path already emits means its output
# drops straight into the existing schema instead of inventing a parallel
# one. "Industrial Supplies > Maintenance" stays available so the model can
# decline rather than being forced into a wrong specific bucket.
ALLOWED_CLASSPATHS: tuple[str, ...] = (
    "HVAC & Commercial Equipment > Water Heaters & HVAC > Commercial Water Heating",
    "HVAC & Commercial Equipment > Water Heaters & HVAC > Heating & Cooling Systems",
    "Plumbing & Industrial Piping > Industrial Valves & Fittings > Ball Valves",
    "Plumbing & Industrial Piping > Industrial Valves & Fittings > Check Valves",
    "Plumbing & Industrial Piping > Industrial Valves & Fittings > Valves & Actuators",
    "Industrial Supplies > Abrasives > Sanding Belts & Discs",
    "Industrial Supplies > Abrasives > Coated Abrasives",
    "Electrical Supplies > Wiring Devices & Distribution > Industrial Switches & Receptacles",
    "Electrical Supplies > Wiring Devices & Distribution > Circuit Protection",
    "Appliances & Consumer Electronics > Kitchen Appliances > Dishwashers",
    "Appliances & Consumer Electronics > Kitchen Appliances > Dryers & Washers",
    "Appliances & Consumer Electronics > Kitchen Appliances > Major Appliances",
    "Tools & Equipment > Machinery > Planers & Jointers",
    "Tools & Equipment > Machinery > Power Tools",
    "Electrical > Lighting > Commercial & Residential Lighting",
    "Building Supplies > Adhesives & Sealants > Specialty Tapes",
    "Building Supplies > Adhesives & Sealants > Masonry & Mortar",
    "Building Supplies > Decking & Outdoor Living > Composite & PVC Decking",
    "Building Supplies > Decking & Outdoor Living > Railing & Balusters",
    "Building Supplies > Decking & Outdoor Living > Trim & Fascia",
    "Building Supplies > Lumber & Sheet Goods > Panels & Sheathing",
    "Building Supplies > Lumber & Sheet Goods > Dimensional Lumber",
    "Safety & PPE > Personal Protective Equipment > Eye & Face Protection",
    "Safety & PPE > Personal Protective Equipment > Hand Protection",
    "Safety & PPE > Personal Protective Equipment > Protective Equipment",
    GENERIC_CLASSPATH,
)

# Bumped whenever the prompt or schema changes, and recorded on every
# suggestion — an AI-derived value is only auditable if you can tell which
# prompt produced it.
PROMPT_VERSION = "cls-v2"

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_BATCH_SIZE = 25
DEFAULT_TIMEOUT_SECONDS = 30

# Per-million-token rates used to derive reported cost. These are
# CONFIGURATION, not measurements — token counts come from the API, the rate
# is whatever the operator sets. Set them to your model's actual published
# prices; the defaults are a placeholder order-of-magnitude for a flash-tier
# model and are surfaced as "configured" rather than "measured" everywhere
# they appear.
DEFAULT_INPUT_RATE_PER_MTOK = 0.10
DEFAULT_OUTPUT_RATE_PER_MTOK = 0.40


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def get_api_key() -> str | None:
    """The configured Gemini key, or None when the tier is disabled."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    return key or None


def is_llm_configured() -> bool:
    """True when an API key is present. Everything else degrades gracefully."""
    return get_api_key() is not None


def needs_llm(classpath: str | None) -> bool:
    """Whether deterministic classification left this row unresolved."""
    return not classpath or classpath == GENERIC_CLASSPATH


@dataclass(frozen=True)
class LLMSuggestion:
    """One row's suggested classification. Advisory, never authoritative."""
    row_number: int
    classpath: str
    confidence: float
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "classpath": self.classpath,
            "confidence": round(self.confidence, 4),
            "reasoning": self.reasoning,
            "status": "ai_inferred",
            "prompt_version": PROMPT_VERSION,
        }


@dataclass(frozen=True)
class LLMUsage:
    """What the tier actually cost. Tokens measured, rate configured."""
    calls_made: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    rows_submitted: int = 0
    rows_resolved: int = 0
    seconds: float = 0.0
    model: str = DEFAULT_MODEL
    errors: tuple[str, ...] = ()

    @property
    def cost_usd(self) -> float:
        in_rate = float(_env("SPECLEDGER_LLM_INPUT_RATE", str(DEFAULT_INPUT_RATE_PER_MTOK)))
        out_rate = float(_env("SPECLEDGER_LLM_OUTPUT_RATE", str(DEFAULT_OUTPUT_RATE_PER_MTOK)))
        return (
            self.prompt_tokens / 1_000_000 * in_rate
            + self.completion_tokens / 1_000_000 * out_rate
        )

    def to_dict(self) -> dict[str, Any]:
        rows = self.rows_submitted or 1
        return {
            "model": self.model,
            "prompt_version": PROMPT_VERSION,
            "calls_made": self.calls_made,
            "rows_submitted": self.rows_submitted,
            "rows_resolved": self.rows_resolved,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "seconds": round(self.seconds, 3),
            "cost_usd": round(self.cost_usd, 6),
            "cost_per_row_usd": round(self.cost_usd / rows, 8),
            "token_counts_measured": True,
            "rate_is_configured_not_measured": True,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class LLMBatchResult:
    """Suggestions plus the usage that produced them."""
    suggestions: dict[int, LLMSuggestion] = field(default_factory=dict)
    usage: LLMUsage = field(default_factory=LLMUsage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggestions": [s.to_dict() for s in self.suggestions.values()],
            "usage": self.usage.to_dict(),
        }


_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "classifications": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "INTEGER"},
                    "classpath": {"type": "STRING", "enum": list(ALLOWED_CLASSPATHS)},
                    "confidence": {"type": "NUMBER"},
                    "reasoning": {"type": "STRING"},
                },
                "required": ["id", "classpath", "confidence"],
            },
        }
    },
    "required": ["classifications"],
}


def _build_prompt(items: Sequence[dict[str, Any]]) -> str:
    listing = "\n".join(
        f'{it["id"]}. part_number="{it.get("part_number", "")}" '
        f'manufacturer="{it.get("manufacturer", "")}" '
        f'description="{it.get("description", "")}"'
        for it in items
    )
    allowed = "\n".join(f"- {c}" for c in ALLOWED_CLASSPATHS)
    return (
        "You are classifying industrial B2B catalogue products into a fixed "
        "taxonomy for a product information management system.\n\n"
        "Choose exactly one classpath per product, from this list only:\n"
        f"{allowed}\n\n"
        "Rules:\n"
        "- Use only the evidence in the product's own text. Do not invent "
        "specifications or infer a brand that is not stated.\n"
        f'- If the text does not clearly support a specific category, return '
        f'"{GENERIC_CLASSPATH}" rather than guessing.\n'
        "- confidence is your own 0.0-1.0 estimate that the classpath is "
        "correct. Be honest and use low values when the text is thin.\n"
        "- reasoning: at most 12 words naming the evidence you used.\n\n"
        f"Products:\n{listing}"
    )


def _call_gemini(
    prompt: str, api_key: str, model: str, timeout: int,
) -> tuple[dict[str, Any] | None, int, int, str | None]:
    """One request. Returns (parsed_json, prompt_tokens, completion_tokens, error)."""
    try:
        response = requests.post(
            _ENDPOINT.format(model=model),
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseSchema": _RESPONSE_SCHEMA,
                    # Deterministic sampling: the same catalogue row should
                    # classify the same way on a re-run, which matters for a
                    # pipeline whose other half is fully reproducible.
                    "temperature": 0,
                },
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return None, 0, 0, f"request failed: {exc}"

    if response.status_code != 200:
        return None, 0, 0, f"HTTP {response.status_code}: {response.text[:200]}"

    try:
        payload = response.json()
        usage = payload.get("usageMetadata", {})
        prompt_tokens = int(usage.get("promptTokenCount", 0))
        completion_tokens = int(usage.get("candidatesTokenCount", 0))
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text), prompt_tokens, completion_tokens, None
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        return None, 0, 0, f"unparseable response: {exc}"


def enrich_unresolved(
    items: Sequence[dict[str, Any]],
    api_key: str | None = None,
    model: str | None = None,
    batch_size: int | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> LLMBatchResult:
    """Classify rows deterministic rules left in the generic bucket.

    `items` are dicts with `id` (the row number), `part_number`,
    `manufacturer` and `description`. Returns suggestions keyed by row
    number; rows the model declines to classify are simply absent.

    Returns an empty result rather than raising when the tier is disabled or
    the API misbehaves — a failing LLM must never fail an ingest.
    """
    key = api_key or get_api_key()
    if not key or not items:
        return LLMBatchResult()

    model_name = model or _env("SPECLEDGER_LLM_MODEL", DEFAULT_MODEL)
    size = batch_size or int(_env("SPECLEDGER_LLM_BATCH_SIZE", str(DEFAULT_BATCH_SIZE)))

    suggestions: dict[int, LLMSuggestion] = {}
    calls = prompt_tokens = completion_tokens = 0
    errors: list[str] = []
    started = time.perf_counter()

    for start in range(0, len(items), size):
        chunk = items[start:start + size]
        parsed, p_tok, c_tok, error = _call_gemini(
            _build_prompt(chunk), key, model_name, timeout,
        )
        calls += 1
        prompt_tokens += p_tok
        completion_tokens += c_tok

        if error:
            errors.append(error)
            continue

        for entry in (parsed or {}).get("classifications", []):
            try:
                row_number = int(entry["id"])
                classpath = str(entry["classpath"])
                confidence = float(entry.get("confidence", 0.0))
            except (KeyError, TypeError, ValueError):
                continue
            # Discard anything outside the controlled vocabulary, and drop
            # the model declining to classify — that is the deterministic
            # result we already have, not new information.
            if classpath not in ALLOWED_CLASSPATHS or classpath == GENERIC_CLASSPATH:
                continue
            suggestions[row_number] = LLMSuggestion(
                row_number=row_number,
                classpath=classpath,
                confidence=max(0.0, min(confidence, 1.0)),
                reasoning=str(entry.get("reasoning", ""))[:120],
            )

    return LLMBatchResult(
        suggestions=suggestions,
        usage=LLMUsage(
            calls_made=calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            rows_submitted=len(items),
            rows_resolved=len(suggestions),
            seconds=time.perf_counter() - started,
            model=model_name,
            errors=tuple(errors),
        ),
    )
