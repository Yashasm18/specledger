"""Tests for the deterministic validation engine."""

import unittest

from backend.specledger.catalogue_ingestion import normalize_rows
from backend.specledger.enrichment import enrich_batch, EnrichedBatch
from backend.specledger.reference_data import ReferenceStore
from backend.specledger.validation_engine import (
    validate_row, validate_batch, get_required_fields,
    ValidationIssue, RowValidationResult, BatchValidationResult,
    AUTO_APPROVE_CONFIDENCE, CATEGORY_REQUIRED_FIELDS,
)


class TestHelpers(unittest.TestCase):
    """Test utility methods and configuration."""

    def setUp(self) -> None:
        self.store = ReferenceStore()

    def _make_enriched(self, rows: list[dict]) -> EnrichedBatch:
        batch = normalize_rows("test.csv", rows)
        return enrich_batch(batch, self.store)


class RequiredFieldsTests(TestHelpers):
    def test_valve_required_fields(self) -> None:
        req = get_required_fields("Ball Valve")
        assert "manufacturer" in req
        assert "part_number" in req
        assert "material" in req
        assert "size" in req
        assert "pressure_rating" in req

    def test_fitting_required_fields(self) -> None:
        req = get_required_fields("Pipe Fitting")
        assert "manufacturer" in req
        assert "material" in req
        assert "size" in req

    def test_unknown_category_returns_defaults(self) -> None:
        req = get_required_fields("Unknown Widget")
        assert req == frozenset({"manufacturer", "part_number"})

    def test_none_category_returns_defaults(self) -> None:
        req = get_required_fields(None)
        assert "manufacturer" in req
        assert "part_number" in req


class RowValidationTests(TestHelpers):
    def test_complete_verified_row_passes(self) -> None:
        enriched = self._make_enriched([{
            "Manufacturer": "Parker Hannifin",
            "Part Number": "V-100",
            "Material": "Brass",
            "Category": "Ball Valve",
            "Size": "2",
            "Pressure Rating": "150",
        }])
        result = validate_row(enriched.rows[0], "Ball Valve")
        # No errors expected — all required fields present and verified
        assert result.error_count == 0

    def test_missing_required_field_produces_error(self) -> None:
        enriched = self._make_enriched([{
            "Manufacturer": "Parker Hannifin",
            "Part Number": "V-100",
            # Missing: material, size, pressure_rating
        }])
        result = validate_row(enriched.rows[0], "Ball Valve")
        missing_codes = [i.code for i in result.issues if i.code == "MISSING_REQUIRED_COLUMN"]
        # material, size, pressure_rating are missing columns
        assert len(missing_codes) >= 2

    def test_placeholder_value_detected_as_missing(self) -> None:
        enriched = self._make_enriched([{
            "Manufacturer": "--",  # placeholder → missing
            "Part Number": "V-100",
        }])
        result = validate_row(enriched.rows[0], None)
        missing_value_issues = [i for i in result.issues if i.code == "MISSING_REQUIRED_VALUE"]
        assert len(missing_value_issues) >= 1
        assert missing_value_issues[0].field_name == "manufacturer"

    def test_unmatched_lov_produces_warning(self) -> None:
        enriched = self._make_enriched([{
            "Manufacturer": "TotallyUnknownCorp",
            "Part Number": "V-100",
        }])
        result = validate_row(enriched.rows[0], None)
        lov_issues = [i for i in result.issues if i.code == "LOV_UNMATCHED"]
        assert len(lov_issues) >= 1

    def test_no_errors_for_verified_fields(self) -> None:
        enriched = self._make_enriched([{
            "Manufacturer": "Parker Hannifin",
            "Part Number": "V-100",
        }])
        result = validate_row(enriched.rows[0], None)
        # With default required fields (manufacturer + part_number),
        # both should be verified
        assert result.error_count == 0

    def test_completeness_scoring(self) -> None:
        enriched = self._make_enriched([{
            "Manufacturer": "Parker Hannifin",
            "Part Number": "V-100",
            "Material": "Brass",
            "Size": "2",
            "Pressure Rating": "150",
        }])
        result = validate_row(enriched.rows[0], "Ball Valve")
        # All 5 required fields for Ball Valve are present
        assert result.completeness == 1.0

    def test_partial_completeness(self) -> None:
        enriched = self._make_enriched([{
            "Manufacturer": "Parker Hannifin",
            "Part Number": "V-100",
            "Category": "Ball Valve",
            # Missing: material, size, pressure_rating columns
        }])
        result = validate_row(enriched.rows[0], "Ball Valve")
        assert result.completeness < 1.0
        assert result.completeness > 0.0

    def test_character_limit_violation(self) -> None:
        # Create a description that exceeds the 2000 char limit
        long_desc = "A" * 2100
        enriched = self._make_enriched([{
            "Description": long_desc,
            "Part Number": "V-100",
            "Manufacturer": "Parker Hannifin",
        }])
        result = validate_row(enriched.rows[0], None)
        char_issues = [i for i in result.issues if i.code == "CHAR_LIMIT_EXCEEDED"]
        assert len(char_issues) >= 1

    def test_auto_approve_high_confidence_row(self) -> None:
        enriched = self._make_enriched([{
            "Manufacturer": "Parker Hannifin",
            "Part Number": "V-100",
        }])
        result = validate_row(enriched.rows[0], None)
        # Both fields should be verified with high confidence
        assert result.can_auto_approve is True

    def test_no_auto_approve_with_errors(self) -> None:
        enriched = self._make_enriched([{
            "Manufacturer": "--",  # Missing required
            "Part Number": "V-100",
        }])
        result = validate_row(enriched.rows[0], None)
        assert result.can_auto_approve is False

    def test_no_auto_approve_with_unknown_manufacturer(self) -> None:
        enriched = self._make_enriched([{
            "Manufacturer": "TotallyUnknownCorp",
            "Part Number": "V-100",
        }])
        result = validate_row(enriched.rows[0], None)
        assert result.can_auto_approve is False

    def test_cross_field_material_pressure_warning(self) -> None:
        enriched = self._make_enriched([{
            "Manufacturer": "Parker Hannifin",
            "Part Number": "V-100",
            "Material": "PVC",
            "Pressure Rating": "800",
        }])
        result = validate_row(enriched.rows[0], None)
        mismatch_issues = [i for i in result.issues if i.code == "MATERIAL_PRESSURE_MISMATCH"]
        assert len(mismatch_issues) >= 1

    def test_no_cross_field_warning_for_safe_combo(self) -> None:
        enriched = self._make_enriched([{
            "Manufacturer": "Parker Hannifin",
            "Part Number": "V-100",
            "Material": "Stainless Steel",
            "Pressure Rating": "1000",
        }])
        result = validate_row(enriched.rows[0], None)
        mismatch_issues = [i for i in result.issues if i.code == "MATERIAL_PRESSURE_MISMATCH"]
        assert len(mismatch_issues) == 0


class BatchValidationTests(TestHelpers):
    def test_batch_validation_processes_all_rows(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
            {"Manufacturer": "Emerson", "Part Number": "V-2"},
            {"Manufacturer": "Honeywell", "Part Number": "V-3"},
        ])
        result = validate_batch(enriched)
        assert result.total_rows == 3
        assert len(result.row_results) == 3

    def test_batch_auto_approve_count(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
            {"Manufacturer": "UnknownCo", "Part Number": "V-2"},
        ])
        result = validate_batch(enriched)
        assert result.auto_approve_count >= 1
        assert result.review_required_count >= 1

    def test_duplicate_part_numbers_detected(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "DUPE-001"},
            {"Manufacturer": "Emerson", "Part Number": "DUPE-001"},
            {"Manufacturer": "Honeywell", "Part Number": "UNIQUE-001"},
        ])
        result = validate_batch(enriched)
        # The two rows with DUPE-001 should have duplicate warnings
        dupe_rows = [
            r for r in result.row_results
            if any(i.code == "DUPLICATE_PART_NUMBER" for i in r.issues)
        ]
        assert len(dupe_rows) == 2

    def test_no_false_duplicate_detection(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "UNIQUE-001"},
            {"Manufacturer": "Emerson", "Part Number": "UNIQUE-002"},
        ])
        result = validate_batch(enriched)
        dupe_rows = [
            r for r in result.row_results
            if any(i.code == "DUPLICATE_PART_NUMBER" for i in r.issues)
        ]
        assert len(dupe_rows) == 0

    def test_batch_result_serialization(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
        ])
        result = validate_batch(enriched)
        output = result.to_dict()
        assert "total_rows" in output
        assert "auto_approve_count" in output
        assert "review_required_count" in output
        assert "auto_approve_rate" in output
        assert "row_results" in output

    def test_row_result_serialization(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
        ])
        result = validate_row(enriched.rows[0], None)
        output = result.to_dict()
        assert "row_number" in output
        assert "issues" in output
        assert "completeness" in output
        assert "can_auto_approve" in output


if __name__ == "__main__":
    unittest.main()
