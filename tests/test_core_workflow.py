import unittest

from backend.specledger.diff import compare_versions
from backend.specledger.sample_data import sample_product, valve_version
from backend.specledger.validation import validate_version


class CoreWorkflowTests(unittest.TestCase):
    def test_sample_product_has_evidence_backed_latest_version(self) -> None:
        product = sample_product()
        self.assertEqual(product.latest_version().attribute_map()["pressure_rating"].value, 600)
        self.assertTrue(product.latest_version().attribute_map()["pressure_rating"].evidence)

    def test_version_diff_detects_pressure_change(self) -> None:
        previous = valve_version("v1", 600, "old-datasheet.pdf")
        current = valve_version("v2", 500, "new-datasheet.pdf")
        changes = compare_versions(previous, current)
        pressure_changes = [change for change in changes if change.attribute == "pressure_rating"]
        self.assertEqual(len(pressure_changes), 1)
        self.assertEqual(pressure_changes[0].change_type, "changed")

    def test_validation_reports_missing_required_attribute(self) -> None:
        version = valve_version("v1", 600, "old-datasheet.pdf")
        issues = validate_version(version, {"pressure_rating", "certification"})
        self.assertTrue(any(issue.code == "MISSING_REQUIRED" and issue.attribute == "certification" for issue in issues))

    def test_versions_from_different_products_cannot_be_compared(self) -> None:
        previous = valve_version("v1", 600, "old-datasheet.pdf")
        current = valve_version("v2", 500, "new-datasheet.pdf")
        object.__setattr__(current, "product_id", "different-product")
        with self.assertRaises(ValueError):
            compare_versions(previous, current)


if __name__ == "__main__":
    unittest.main()

