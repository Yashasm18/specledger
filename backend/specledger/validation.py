"""Deterministic validation rules for the first product-data milestone."""

from __future__ import annotations

from dataclasses import dataclass

from .models import ProductVersion


REQUIRED_VALVE_ATTRIBUTES = {
    "size",
    "pressure_rating",
    "temperature_range",
    "material",
    "connection_type",
}


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    attribute: str | None
    message: str
    severity: str


def validate_version(version: ProductVersion, required_attributes: set[str] | None = None) -> list[ValidationIssue]:
    required = required_attributes or set()
    attributes = version.attribute_map()
    issues: list[ValidationIssue] = []

    for attribute_name in sorted(required - attributes.keys()):
        issues.append(ValidationIssue("MISSING_REQUIRED", attribute_name, f"Required attribute '{attribute_name}' is missing", "error"))

    for attribute in version.attributes:
        if attribute.value is None or (isinstance(attribute.value, str) and not attribute.value.strip()):
            issues.append(ValidationIssue("EMPTY_VALUE", attribute.name, "Attribute has no usable value", "error"))
        if attribute.status.value == "inferred":
            issues.append(ValidationIssue("INFERRED_VALUE", attribute.name, "Value requires human review because it was inferred", "warning"))
        if attribute.status.value == "conflict":
            issues.append(ValidationIssue("CONFLICTING_VALUE", attribute.name, "Value conflicts with another source", "error"))
        if attribute.confidence is not None and attribute.confidence < 0.7:
            issues.append(ValidationIssue("LOW_CONFIDENCE", attribute.name, "Confidence is below the review threshold", "warning"))

    return issues

