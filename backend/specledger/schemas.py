"""Versioned catalogue schemas used by deterministic validation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogueSchema:
    schema_id: str
    required_attributes: frozenset[str]
    version: str = "1.0"


SCHEMAS = {
    "generic": CatalogueSchema("industrial.generic", frozenset({"size", "material"})),
    "valve": CatalogueSchema("industrial.valve", frozenset({"size", "pressure_rating", "material"})),
    "pump": CatalogueSchema("industrial.pump", frozenset({"size", "material"})),
    "fitting": CatalogueSchema("industrial.fitting", frozenset({"size", "material", "connection_type"})),
}


def get_schema(category: str | None) -> CatalogueSchema:
    return SCHEMAS.get((category or "generic").strip().casefold(), SCHEMAS["generic"])
