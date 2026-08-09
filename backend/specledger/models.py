"""Domain models for evidence-backed product records.

The first milestone deliberately uses the Python standard library. This keeps
the core logic runnable before framework dependencies are introduced.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ValueStatus(str, Enum):
    VERIFIED = "verified"
    INFERRED = "inferred"
    CONFLICT = "conflict"
    MISSING = "missing"
    REVIEW_REQUIRED = "review_required"


@dataclass(frozen=True)
class Evidence:
    source_name: str
    source_type: str
    page: int | None = None
    locator: str | None = None
    excerpt: str | None = None
    captured_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.source_name.strip():
            raise ValueError("Evidence source_name cannot be empty")
        if not self.source_type.strip():
            raise ValueError("Evidence source_type cannot be empty")
        if self.page is not None and self.page < 1:
            raise ValueError("Evidence page must be positive")


@dataclass(frozen=True)
class AttributeValue:
    name: str
    value: Any
    unit: str | None
    evidence: tuple[Evidence, ...]
    status: ValueStatus = ValueStatus.VERIFIED
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Attribute name cannot be empty")
        if not self.evidence:
            raise ValueError(f"Attribute '{self.name}' requires source evidence")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("Confidence must be between 0 and 1")


@dataclass(frozen=True)
class ProductVersion:
    version_id: str
    product_id: str
    attributes: tuple[AttributeValue, ...]
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.version_id.strip() or not self.product_id.strip():
            raise ValueError("Product and version identifiers cannot be empty")
        names = [attribute.name for attribute in self.attributes]
        if len(names) != len(set(names)):
            raise ValueError("A product version cannot contain duplicate attributes")

    def attribute_map(self) -> dict[str, AttributeValue]:
        return {attribute.name: attribute for attribute in self.attributes}


@dataclass(frozen=True)
class Product:
    product_id: str
    sku: str
    name: str
    category: str
    versions: tuple[ProductVersion, ...]

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.product_id, self.sku, self.name, self.category)):
            raise ValueError("Product identifiers and classification fields cannot be empty")
        if not self.versions:
            raise ValueError("A product must have at least one version")
        if any(version.product_id != self.product_id for version in self.versions):
            raise ValueError("Every version must belong to the product")

    def latest_version(self) -> ProductVersion:
        return self.versions[-1]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

