"""Deterministic validation engine for enriched catalogue rows.

Runs a configurable set of rules against enriched data and produces
structured validation issues. Every issue has a severity, a field
reference, a human-readable message, and an optional auto-fix
suggestion. This engine decides whether a row can be auto-approved
or must be sent to human review.

Rule categories:
  1. Required-field checks: fields that must be present per category schema
  2. LOV membership: manufacturer/brand/category must be recognized
  3. Cross-field consistency: material ↔ pressure, size ↔ UOM, etc.
  4. Completeness scoring: percentage of schema fields populated
  5. Anomaly detection: duplicate part numbers, contradictory values
  6. Character-limit enforcement: field length limits for commerce output
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .enrichment import EnrichedBatch, EnrichedRow


# ---------------------------------------------------------------------------
# Validation issue model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationIssue:
    """A single validation finding on an enriched row or field."""
    code: str
    severity: str  # "error", "warning", "info"
    field_name: str | None
    message: str
    suggestion: str | None = None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "field_name": self.field_name,
            "message": self.message,
            "suggestion": self.suggestion,
        }


@dataclass(frozen=True)
class RowValidationResult:
    """Validation result for a single enriched row."""
    row_number: int
    issues: tuple[ValidationIssue, ...]
    completeness: float  # 0.0–1.0
    can_auto_approve: bool

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def to_dict(self) -> dict:
        return {
            "row_number": self.row_number,
            "issues": [i.to_dict() for i in self.issues],
            "completeness": round(self.completeness, 4),
            "can_auto_approve": self.can_auto_approve,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
        }


@dataclass(frozen=True)
class BatchValidationResult:
    """Validation result for an entire enriched batch."""
    row_results: tuple[RowValidationResult, ...]
    total_rows: int
    auto_approve_count: int
    review_required_count: int
    total_issues: int

    @property
    def auto_approve_rate(self) -> float:
        return self.auto_approve_count / self.total_rows if self.total_rows else 0.0

    def to_dict(self) -> dict:
        return {
            "total_rows": self.total_rows,
            "auto_approve_count": self.auto_approve_count,
            "review_required_count": self.review_required_count,
            "auto_approve_rate": round(self.auto_approve_rate, 4),
            "total_issues": self.total_issues,
            "row_results": [r.to_dict() for r in self.row_results],
        }


# ---------------------------------------------------------------------------
# Category-specific field requirements
# ---------------------------------------------------------------------------

# Required fields per category (canonical category name → required column keys)
CATEGORY_REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "Ball Valve": frozenset({"manufacturer", "part_number", "material", "size", "pressure"}),
    "Gate Valve": frozenset({"manufacturer", "part_number", "material", "size", "pressure"}),
    "Globe Valve": frozenset({"manufacturer", "part_number", "material", "size", "pressure"}),
    "Check Valve": frozenset({"manufacturer", "part_number", "material", "size", "pressure"}),
    "Butterfly Valve": frozenset({"manufacturer", "part_number", "material", "size"}),
    "Needle Valve": frozenset({"manufacturer", "part_number", "material", "size"}),
    "Pressure Relief Valve": frozenset({"manufacturer", "part_number", "pressure"}),
    "Solenoid Valve": frozenset({"manufacturer", "part_number"}),
    "Diaphragm Valve": frozenset({"manufacturer", "part_number", "material", "size"}),
    "Centrifugal Pump": frozenset({"manufacturer", "part_number", "material"}),
    "Pipe Fitting": frozenset({"manufacturer", "part_number", "material", "size"}),
    "Elbow Fitting": frozenset({"manufacturer", "part_number", "material", "size"}),
    "Tee Fitting": frozenset({"manufacturer", "part_number", "material", "size"}),
    "Coupling": frozenset({"manufacturer", "part_number", "material", "size"}),
    "Union": frozenset({"manufacturer", "part_number", "material", "size"}),
    "Reducer": frozenset({"manufacturer", "part_number", "material", "size"}),
    "Flange": frozenset({"manufacturer", "part_number", "material", "size"}),
}

# Default required fields when category is unknown
DEFAULT_REQUIRED_FIELDS = frozenset({"manufacturer", "part_number"})

# Character limits for commerce output fields
FIELD_CHAR_LIMITS: dict[str, int] = {
    "manufacturer": 200,
    "brand": 200,
    "category": 100,
    "part_number": 100,
    "description": 2000,
    "material": 200,
    "size": 50,
    "pressure": 50,
    "connection_type": 100,
    "temperature_range": 100,
}

# Materials that are incompatible with high pressure (>600 psi)
HIGH_PRESSURE_INCOMPATIBLE_MATERIALS = frozenset({
    "PVC", "CPVC", "Polypropylene", "Nylon",
})

# Auto-approval confidence threshold
AUTO_APPROVE_CONFIDENCE = 0.80


# ---------------------------------------------------------------------------
# Individual validation rules
# ---------------------------------------------------------------------------

def _check_required_fields(row: EnrichedRow, required: frozenset[str]) -> list[ValidationIssue]:
    """Check that required fields are present and not missing."""
    issues: list[ValidationIssue] = []
    field_map = row.role_map
    for req_field in sorted(required):
        field = field_map.get(req_field)
        if field is None:
            issues.append(ValidationIssue(
                "MISSING_REQUIRED_COLUMN", "error", req_field,
                f"Required field '{req_field}' is not present in the source data",
                f"Add '{req_field}' column to the input file",
            ))
        elif field.status == "missing" or field.canonical_value is None:
            issues.append(ValidationIssue(
                "MISSING_REQUIRED_VALUE", "error", req_field,
                f"Required field '{req_field}' has no value",
                "Provide a value or mark as intentionally blank",
            ))
    return issues


def _check_lov_membership(row: EnrichedRow) -> list[ValidationIssue]:
    """Check that LOV-constrained fields matched a reference entry."""
    issues: list[ValidationIssue] = []
    lov_roles = {"manufacturer", "brand", "category", "material", "uom"}
    for field in row.fields:
        if field.role in lov_roles and field.status == "review_required" and field.raw_value:
            issues.append(ValidationIssue(
                "LOV_UNMATCHED", "warning", field.column,
                f"Value '{field.raw_value}' for '{field.column}' did not match any controlled vocabulary entry",
                "Verify spelling or add to reference data",
            ))
    return issues


def _check_low_confidence(row: EnrichedRow) -> list[ValidationIssue]:
    """Flag fields with confidence below the review threshold."""
    issues: list[ValidationIssue] = []
    for field in row.fields:
        if field.raw_value and 0.0 < field.confidence < AUTO_APPROVE_CONFIDENCE:
            issues.append(ValidationIssue(
                "LOW_CONFIDENCE", "warning", field.column,
                f"Field '{field.column}' has confidence {field.confidence:.2f} (threshold: {AUTO_APPROVE_CONFIDENCE})",
            ))
    return issues


def _check_character_limits(row: EnrichedRow) -> list[ValidationIssue]:
    """Check that canonical values don't exceed commerce character limits."""
    issues: list[ValidationIssue] = []
    for field in row.fields:
        limit = FIELD_CHAR_LIMITS.get(field.role)
        if limit and field.canonical_value and len(field.canonical_value) > limit:
            issues.append(ValidationIssue(
                "CHAR_LIMIT_EXCEEDED", "error", field.column,
                f"Field '{field.column}' value has {len(field.canonical_value)} chars (limit: {limit})",
                f"Truncate to {limit} characters",
            ))
    return issues


def _check_cross_field_consistency(row: EnrichedRow) -> list[ValidationIssue]:
    """Check for material ↔ pressure compatibility and other cross-field rules."""
    issues: list[ValidationIssue] = []
    field_map = row.role_map

    # Material vs. pressure compatibility
    material_field = field_map.get("material")
    pressure_field = field_map.get("pressure")
    if (material_field and pressure_field
            and material_field.canonical_value and pressure_field.canonical_value):
        try:
            pressure_value = float(pressure_field.canonical_value.split()[0])
            if (material_field.canonical_value in HIGH_PRESSURE_INCOMPATIBLE_MATERIALS
                    and pressure_value > 600):
                issues.append(ValidationIssue(
                    "MATERIAL_PRESSURE_MISMATCH", "warning", "material",
                    f"Material '{material_field.canonical_value}' is typically incompatible with pressure {pressure_value} psi",
                    "Verify material is rated for this pressure",
                ))
        except (ValueError, IndexError):
            pass  # Non-numeric pressure, skip check

    # Size field should have a corresponding UOM
    size_field = field_map.get("size")
    uom_field = field_map.get("uom") or field_map.get("size_uom")
    if size_field and size_field.canonical_value and not uom_field:
        # Only flag if no UOM column exists at all
        has_any_uom = any(f.role == "uom" for f in row.fields)
        if not has_any_uom:
            issues.append(ValidationIssue(
                "SIZE_WITHOUT_UOM", "info", "size",
                "Size value is present but no unit-of-measure column found",
                "Consider adding a UOM column",
            ))

    return issues


def _check_duplicate_part_numbers(rows: Sequence[EnrichedRow]) -> dict[int, list[ValidationIssue]]:
    """Detect duplicate part numbers within a batch."""
    pn_map: dict[str, list[int]] = {}
    for row in rows:
        pn_field = row.role_map.get("part_number")
        if pn_field and pn_field.canonical_value:
            pn_key = pn_field.canonical_value.strip().casefold()
            pn_map.setdefault(pn_key, []).append(row.row_number)

    issues_by_row: dict[int, list[ValidationIssue]] = {}
    for pn_key, row_numbers in pn_map.items():
        if len(row_numbers) > 1:
            for row_num in row_numbers:
                other_rows = [r for r in row_numbers if r != row_num]
                issues_by_row.setdefault(row_num, []).append(ValidationIssue(
                    "DUPLICATE_PART_NUMBER", "warning", "part_number",
                    f"Part number appears in {len(row_numbers)} rows: {', '.join(str(r) for r in other_rows)}",
                    "Verify these are not duplicate entries",
                ))
    return issues_by_row


# ---------------------------------------------------------------------------
# Completeness scoring
# ---------------------------------------------------------------------------

def _calculate_completeness(row: EnrichedRow, required: frozenset[str]) -> float:
    """Calculate what fraction of required fields have non-missing values."""
    if not required:
        # Fall back to checking all fields
        total = len(row.fields)
        if total == 0:
            return 0.0
        populated = sum(1 for f in row.fields if f.canonical_value is not None)
        return populated / total

    field_map = row.role_map
    populated = sum(1 for req in required if req in field_map and field_map[req].canonical_value is not None)
    return populated / len(required)


# ---------------------------------------------------------------------------
# Auto-approval decision
# ---------------------------------------------------------------------------

def _can_auto_approve(row: EnrichedRow, issues: Sequence[ValidationIssue]) -> bool:
    """Determine if a row can be auto-approved without human review.

    Rules:
    - No errors
    - No fields with status 'review_required' or 'missing' (when required)
    - All field confidences >= AUTO_APPROVE_CONFIDENCE
    - No LOV_UNMATCHED warnings
    """
    if any(i.severity == "error" for i in issues):
        return False
    if any(i.code == "LOV_UNMATCHED" for i in issues):
        return False
    if row.overall_confidence < AUTO_APPROVE_CONFIDENCE:
        return False
    if any(f.status == "review_required" for f in row.fields if f.raw_value):
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_required_fields(category: str | None) -> frozenset[str]:
    """Get the required fields for a category. Falls back to defaults."""
    if category:
        return CATEGORY_REQUIRED_FIELDS.get(category, DEFAULT_REQUIRED_FIELDS)
    return DEFAULT_REQUIRED_FIELDS


def validate_row(row: EnrichedRow, category: str | None = None) -> RowValidationResult:
    """Run all validation rules on a single enriched row."""
    required = get_required_fields(category)
    issues: list[ValidationIssue] = []

    issues.extend(_check_required_fields(row, required))
    issues.extend(_check_lov_membership(row))
    issues.extend(_check_low_confidence(row))
    issues.extend(_check_character_limits(row))
    issues.extend(_check_cross_field_consistency(row))

    completeness = _calculate_completeness(row, required)
    can_approve = _can_auto_approve(row, issues)

    return RowValidationResult(
        row_number=row.row_number,
        issues=tuple(issues),
        completeness=completeness,
        can_auto_approve=can_approve,
    )


def validate_batch(batch: EnrichedBatch) -> BatchValidationResult:
    """Run all validation rules on an enriched batch, including batch-level checks."""
    # Detect per-row category from the enriched data
    row_results: list[RowValidationResult] = []
    for enriched_row in batch.rows:
        cat_field = enriched_row.role_map.get("category")
        category = cat_field.canonical_value if cat_field else None
        row_results.append(validate_row(enriched_row, category))

    # Add batch-level duplicate detection
    dup_issues = _check_duplicate_part_numbers(batch.rows)
    final_results: list[RowValidationResult] = []
    for result in row_results:
        extra = dup_issues.get(result.row_number, [])
        if extra:
            all_issues = list(result.issues) + extra
            can_approve = result.can_auto_approve and not any(i.severity == "error" for i in extra)
            final_results.append(RowValidationResult(
                result.row_number, tuple(all_issues), result.completeness, can_approve,
            ))
        else:
            final_results.append(result)

    auto_count = sum(1 for r in final_results if r.can_auto_approve)
    issue_count = sum(len(r.issues) for r in final_results)

    return BatchValidationResult(
        row_results=tuple(final_results),
        total_rows=len(final_results),
        auto_approve_count=auto_count,
        review_required_count=len(final_results) - auto_count,
        total_issues=issue_count,
    )
