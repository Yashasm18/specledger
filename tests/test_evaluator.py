"""Tests for the ground-truth evaluation engine."""

import json
import tempfile
import unittest
from pathlib import Path

from backend.specledger.catalogue_ingestion import normalize_rows
from backend.specledger.enrichment import enrich_batch
from backend.specledger.evaluator import (
    GroundTruthRow, evaluate, EvaluationReport, load_ground_truth_csv,
)
from backend.specledger.reference_data import ReferenceStore


class EvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ReferenceStore()

    def _evaluate_simple(self, raw_rows: list[dict], gt_values: list[dict]) -> EvaluationReport:
        batch = normalize_rows("eval_test.csv", raw_rows)
        enriched = enrich_batch(batch, self.store)
        ground_truth = [
            GroundTruthRow(row_number=gt["row_number"], values=gt["values"])
            for gt in gt_values
        ]
        return evaluate(enriched, ground_truth)

    def test_perfect_prediction_scores_1_0(self) -> None:
        report = self._evaluate_simple(
            [{"Manufacturer": "Parker Hannifin", "Part Number": "V-100"}],
            [{"row_number": 2, "values": {"manufacturer": "Parker Hannifin", "part_number": "V-100"}}],
        )
        assert report.overall_exact_accuracy == 1.0
        assert report.complete_row_accuracy == 1.0
        assert report.matched_rows == 1

    def test_partial_match_scores_proportionally(self) -> None:
        report = self._evaluate_simple(
            [{"Manufacturer": "Parker Hannifin", "Brand": "UnknownBrand", "Part Number": "V-100"}],
            [{"row_number": 2, "values": {
                "manufacturer": "Parker Hannifin",
                "brand": "CorrectBrand",  # enrichment won't match this
                "part_number": "V-100",
            }}],
        )
        # manufacturer and part_number should match, brand should not
        assert report.overall_exact_accuracy < 1.0
        assert report.overall_exact_accuracy > 0.0
        assert report.row_results[0].is_complete_match is False

    def test_missing_field_detected_correctly(self) -> None:
        report = self._evaluate_simple(
            [{"Manufacturer": "--", "Part Number": "V-100"}],
            [{"row_number": 2, "values": {"manufacturer": None, "part_number": "V-100"}}],
        )
        mfg_metric = report.field_metrics.get("manufacturer")
        assert mfg_metric is not None
        assert mfg_metric.missing_correct == 1

    def test_missing_field_when_value_expected(self) -> None:
        report = self._evaluate_simple(
            [{"Manufacturer": "--", "Part Number": "V-100"}],
            [{"row_number": 2, "values": {"manufacturer": "Parker Hannifin", "part_number": "V-100"}}],
        )
        mfg_metric = report.field_metrics.get("manufacturer")
        assert mfg_metric is not None
        assert mfg_metric.missing_incorrect == 1

    def test_mismatched_canonical_detected(self) -> None:
        report = self._evaluate_simple(
            [{"Manufacturer": "Emerson", "Part Number": "V-100"}],
            [{"row_number": 2, "values": {"manufacturer": "Parker Hannifin", "part_number": "V-100"}}],
        )
        mfg_metric = report.field_metrics.get("manufacturer")
        assert mfg_metric is not None
        assert mfg_metric.false_positives == 1
        # Should appear in row mismatches
        assert len(report.row_results[0].mismatches) == 1
        assert report.row_results[0].mismatches[0]["type"] == "mismatch"

    def test_per_field_breakdown(self) -> None:
        report = self._evaluate_simple(
            [{"Manufacturer": "Parker Hannifin", "Material": "Brass", "Part Number": "V-100"}],
            [{"row_number": 2, "values": {
                "manufacturer": "Parker Hannifin",
                "material": "Brass",
                "part_number": "V-100",
            }}],
        )
        assert "manufacturer" in report.field_metrics
        assert "material" in report.field_metrics
        assert report.field_metrics["manufacturer"].exact_matches == 1

    def test_role_metrics_present(self) -> None:
        report = self._evaluate_simple(
            [{"Manufacturer": "Parker Hannifin", "Brand": "Apollo", "Part Number": "V-100"}],
            [{"row_number": 2, "values": {
                "manufacturer": "Parker Hannifin",
                "brand": "Apollo",
                "part_number": "V-100",
            }}],
        )
        assert "manufacturer" in report.role_metrics
        assert "brand" in report.role_metrics

    def test_multi_row_evaluation(self) -> None:
        report = self._evaluate_simple(
            [
                {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
                {"Manufacturer": "Emerson", "Part Number": "V-2"},
                {"Manufacturer": "Honeywell", "Part Number": "V-3"},
            ],
            [
                {"row_number": 2, "values": {"manufacturer": "Parker Hannifin", "part_number": "V-1"}},
                {"row_number": 3, "values": {"manufacturer": "Emerson Electric", "part_number": "V-2"}},
                {"row_number": 4, "values": {"manufacturer": "Honeywell", "part_number": "V-3"}},
            ],
        )
        assert report.matched_rows == 3
        assert report.average_row_accuracy > 0.5

    def test_unmatched_rows_counted(self) -> None:
        report = self._evaluate_simple(
            [{"Manufacturer": "Parker Hannifin", "Part Number": "V-1"}],
            [{"row_number": 999, "values": {"manufacturer": "Parker Hannifin", "part_number": "V-1"}}],
        )
        assert report.unmatched_rows == 1
        assert report.matched_rows == 0

    def test_report_exports_to_json(self) -> None:
        report = self._evaluate_simple(
            [{"Manufacturer": "Parker Hannifin", "Part Number": "V-100"}],
            [{"row_number": 2, "values": {"manufacturer": "Parker Hannifin", "part_number": "V-100"}}],
        )
        output = json.loads(report.to_json())
        assert "summary" in output
        assert "field_metrics" in output
        assert "row_results" in output
        assert output["summary"]["overall_exact_accuracy"] == 1.0

    def test_normalized_match_counted_separately(self) -> None:
        # "Emerson" alias matches to "Emerson Electric" canonical
        report = self._evaluate_simple(
            [{"Manufacturer": "Emerson", "Part Number": "V-100"}],
            [{"row_number": 2, "values": {"manufacturer": "Emerson Electric", "part_number": "V-100"}}],
        )
        mfg_metric = report.field_metrics.get("manufacturer")
        assert mfg_metric is not None
        # Enrichment produces "Emerson Electric" from alias "Emerson", so this should be exact
        assert mfg_metric.exact_matches == 1

    def test_empty_ground_truth(self) -> None:
        report = self._evaluate_simple(
            [{"Manufacturer": "Parker Hannifin", "Part Number": "V-100"}],
            [],
        )
        assert report.ground_truth_rows == 0
        assert report.unmatched_rows == 1
        assert report.overall_exact_accuracy == 0.0


class GroundTruthCSVLoadingTests(unittest.TestCase):
    def test_load_from_csv(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("row_number,Manufacturer,Part Number,Material\n")
            f.write("2,Parker Hannifin,V-100,Brass\n")
            f.write("3,Emerson Electric,V-200,\n")
            tmp_path = f.name

        rows = load_ground_truth_csv(tmp_path)
        assert len(rows) == 2
        assert rows[0].row_number == 2
        assert rows[0].values["manufacturer"] == "Parker Hannifin"
        assert rows[0].values["material"] == "Brass"
        assert rows[1].values.get("material") is None  # empty cell

        Path(tmp_path).unlink()

    def test_csv_round_trip_with_evaluator(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("row_number,Manufacturer,Part Number\n")
            f.write("2,Parker Hannifin,V-100\n")
            tmp_path = f.name

        gt = load_ground_truth_csv(tmp_path)
        batch = normalize_rows("test.csv", [{"Manufacturer": "Parker Hannifin", "Part Number": "V-100"}])
        enriched = enrich_batch(batch, ReferenceStore())
        report = evaluate(enriched, gt)
        assert report.overall_exact_accuracy == 1.0

        Path(tmp_path).unlink()


if __name__ == "__main__":
    unittest.main()
