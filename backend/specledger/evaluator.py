"""Ground-truth evaluation engine for catalogue enrichment accuracy.

Measures field-level accuracy by comparing enriched output against a
known-correct ground-truth dataset. This is the primary quality metric
for the UniHack submission.

Metrics produced:
  - Per-field: exact match rate, normalized match rate
  - Per-row: complete-row accuracy, partial accuracy
  - Aggregate: overall accuracy, missing detection rate, false positive rate
  - Per-role breakdown (manufacturer, brand, material, etc.)
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .catalogue_ingestion import canonical_key
from .enrichment import EnrichedBatch


@dataclass(frozen=True)
class GroundTruthRow:
    """Expected canonical values for a single row."""
    row_number: int
    values: dict[str, str | None]  # column_key → expected canonical value


@dataclass
class FieldMetric:
    """Accuracy metrics for a single field type."""
    field_name: str
    total: int = 0
    exact_matches: int = 0
    normalized_matches: int = 0
    missing_correct: int = 0      # correctly identified as missing
    missing_incorrect: int = 0    # predicted missing but expected a value
    false_positives: int = 0      # predicted a value but was wrong
    not_evaluated: int = 0        # ground truth had no value for comparison

    @property
    def exact_accuracy(self) -> float:
        return self.exact_matches / self.total if self.total else 0.0

    @property
    def normalized_accuracy(self) -> float:
        return (self.exact_matches + self.normalized_matches) / self.total if self.total else 0.0

    @property
    def precision(self) -> float:
        predicted = self.total - self.missing_correct - self.not_evaluated
        correct = self.exact_matches + self.normalized_matches
        return correct / predicted if predicted else 0.0

    def to_dict(self) -> dict:
        return {
            "field_name": self.field_name,
            "total": self.total,
            "exact_matches": self.exact_matches,
            "normalized_matches": self.normalized_matches,
            "missing_correct": self.missing_correct,
            "missing_incorrect": self.missing_incorrect,
            "false_positives": self.false_positives,
            "not_evaluated": self.not_evaluated,
            "exact_accuracy": round(self.exact_accuracy, 4),
            "normalized_accuracy": round(self.normalized_accuracy, 4),
        }


@dataclass
class RowResult:
    """Evaluation result for a single row."""
    row_number: int
    total_fields: int = 0
    exact_matches: int = 0
    normalized_matches: int = 0
    mismatches: list[dict] = field(default_factory=list)

    @property
    def is_complete_match(self) -> bool:
        return self.exact_matches == self.total_fields and self.total_fields > 0

    @property
    def partial_accuracy(self) -> float:
        return (self.exact_matches + self.normalized_matches) / self.total_fields if self.total_fields else 0.0

    def to_dict(self) -> dict:
        return {
            "row_number": self.row_number,
            "total_fields": self.total_fields,
            "exact_matches": self.exact_matches,
            "normalized_matches": self.normalized_matches,
            "partial_accuracy": round(self.partial_accuracy, 4),
            "is_complete_match": self.is_complete_match,
            "mismatches": self.mismatches,
        }


@dataclass
class EvaluationReport:
    """Complete evaluation report."""
    ground_truth_rows: int
    predicted_rows: int
    matched_rows: int
    unmatched_rows: int
    field_metrics: dict[str, FieldMetric] = field(default_factory=dict)
    row_results: list[RowResult] = field(default_factory=list)
    role_metrics: dict[str, FieldMetric] = field(default_factory=dict)

    @property
    def overall_exact_accuracy(self) -> float:
        total = sum(m.total for m in self.field_metrics.values())
        exact = sum(m.exact_matches for m in self.field_metrics.values())
        return exact / total if total else 0.0

    @property
    def overall_normalized_accuracy(self) -> float:
        total = sum(m.total for m in self.field_metrics.values())
        matches = sum(m.exact_matches + m.normalized_matches for m in self.field_metrics.values())
        return matches / total if total else 0.0

    @property
    def complete_row_accuracy(self) -> float:
        if not self.row_results:
            return 0.0
        complete = sum(1 for r in self.row_results if r.is_complete_match)
        return complete / len(self.row_results)

    @property
    def average_row_accuracy(self) -> float:
        if not self.row_results:
            return 0.0
        return sum(r.partial_accuracy for r in self.row_results) / len(self.row_results)

    @property
    def missing_detection_rate(self) -> float:
        total_missing = sum(m.missing_correct + m.missing_incorrect for m in self.field_metrics.values())
        correct_missing = sum(m.missing_correct for m in self.field_metrics.values())
        return correct_missing / total_missing if total_missing else 0.0

    def to_dict(self) -> dict:
        return {
            "summary": {
                "ground_truth_rows": self.ground_truth_rows,
                "predicted_rows": self.predicted_rows,
                "matched_rows": self.matched_rows,
                "unmatched_rows": self.unmatched_rows,
                "overall_exact_accuracy": round(self.overall_exact_accuracy, 4),
                "overall_normalized_accuracy": round(self.overall_normalized_accuracy, 4),
                "complete_row_accuracy": round(self.complete_row_accuracy, 4),
                "average_row_accuracy": round(self.average_row_accuracy, 4),
            },
            "field_metrics": {k: v.to_dict() for k, v in self.field_metrics.items()},
            "role_metrics": {k: v.to_dict() for k, v in self.role_metrics.items()},
            "row_results": [r.to_dict() for r in self.row_results],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def _normalize_for_comparison(value: str | None) -> str:
    """Create a stable comparison key for accuracy checking."""
    if value is None:
        return ""
    return value.strip().casefold()


def _values_match_exact(predicted: str | None, expected: str | None) -> bool:
    """Check if two values match exactly (case-insensitive)."""
    return _normalize_for_comparison(predicted) == _normalize_for_comparison(expected)


def _values_match_normalized(predicted: str | None, expected: str | None) -> bool:
    """Check if values match after normalization (whitespace, punctuation)."""
    if predicted is None or expected is None:
        return predicted is None and expected is None
    p = canonical_key(predicted)
    e = canonical_key(expected)
    return p == e and p != ""


_COLUMN_ALIASES = {
    "size_uom": "uom",
}


def load_ground_truth_csv(path: str | Path) -> list[GroundTruthRow]:
    """Load ground-truth data from a CSV file.

    Expected format: first column is ``row_number``, remaining columns
    are the expected canonical values for each field.
    """
    rows: list[GroundTruthRow] = []
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            row_number = int(row.pop("row_number", "0"))
            values = {}
            for k, v in row.items():
                ck = canonical_key(k)
                if ck:
                    ck = _COLUMN_ALIASES.get(ck, ck)
                    values[ck] = v.strip() if v and v.strip() else None
            rows.append(GroundTruthRow(row_number, values))
    return rows


def evaluate(predicted: EnrichedBatch, ground_truth: Sequence[GroundTruthRow]) -> EvaluationReport:
    """Evaluate enriched predictions against ground truth.

    Matching is by row_number. Fields present in ground truth but not in
    predictions are counted as missing_incorrect. Fields in predictions
    but not in ground truth are counted as not_evaluated.
    """
    gt_by_row: dict[int, GroundTruthRow] = {gt.row_number: gt for gt in ground_truth}

    report = EvaluationReport(
        ground_truth_rows=len(ground_truth),
        predicted_rows=predicted.row_count,
        matched_rows=0,
        unmatched_rows=0,
    )

    for enriched_row in predicted.rows:
        gt_row = gt_by_row.get(enriched_row.row_number)
        if gt_row is None:
            report.unmatched_rows += 1
            continue

        report.matched_rows += 1
        row_result = RowResult(enriched_row.row_number)

        for enriched_field in enriched_row.fields:
            col = _COLUMN_ALIASES.get(canonical_key(enriched_field.column), enriched_field.column)
            if col not in gt_row.values and enriched_field.role in gt_row.values:
                col = enriched_field.role
            predicted_value = enriched_field.canonical_value
            expected_value = gt_row.values.get(col)

            # Initialize field metric
            if col not in report.field_metrics:
                report.field_metrics[col] = FieldMetric(col)
            metric = report.field_metrics[col]

            # Initialize role metric
            role = enriched_field.role
            if role not in report.role_metrics:
                report.role_metrics[role] = FieldMetric(role)
            role_metric = report.role_metrics[role]

            # Ground truth has no value for this column — skip
            if col not in gt_row.values:
                metric.not_evaluated += 1
                role_metric.not_evaluated += 1
                continue

            metric.total += 1
            role_metric.total += 1
            row_result.total_fields += 1

            # Both missing
            if expected_value is None and predicted_value is None:
                metric.missing_correct += 1
                role_metric.missing_correct += 1
                row_result.exact_matches += 1
                continue

            # Predicted missing but expected a value
            if predicted_value is None and expected_value is not None:
                metric.missing_incorrect += 1
                role_metric.missing_incorrect += 1
                row_result.mismatches.append({
                    "column": col, "expected": expected_value, "predicted": None, "type": "missing_incorrect"
                })
                continue

            # Predicted a value but expected missing
            if predicted_value is not None and expected_value is None:
                metric.false_positives += 1
                role_metric.false_positives += 1
                row_result.mismatches.append({
                    "column": col, "expected": None, "predicted": predicted_value, "type": "false_positive"
                })
                continue

            # Both have values — compare
            if _values_match_exact(predicted_value, expected_value):
                metric.exact_matches += 1
                role_metric.exact_matches += 1
                row_result.exact_matches += 1
            elif _values_match_normalized(predicted_value, expected_value):
                metric.normalized_matches += 1
                role_metric.normalized_matches += 1
                row_result.normalized_matches += 1
            else:
                metric.false_positives += 1
                role_metric.false_positives += 1
                row_result.mismatches.append({
                    "column": col, "expected": expected_value, "predicted": predicted_value, "type": "mismatch"
                })

        report.row_results.append(row_result)

    return report
