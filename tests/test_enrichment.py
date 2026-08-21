"""Tests for the field-level enrichment pipeline."""

import unittest

from backend.specledger.catalogue_ingestion import normalize_rows, CatalogueBatch
from backend.specledger.enrichment import (
    enrich_batch, detect_role, EnrichedBatch, EnrichedField,
)
from backend.specledger.reference_data import ReferenceStore


class RoleDetectionTests(unittest.TestCase):
    def test_manufacturer_columns(self) -> None:
        for key in ["manufacturer", "mfr", "mfg", "mfg_name"]:
            assert detect_role(key) == "manufacturer", f"Failed for {key}"

    def test_brand_columns(self) -> None:
        for key in ["brand", "brand_name"]:
            assert detect_role(key) == "brand", f"Failed for {key}"

    def test_material_columns(self) -> None:
        for key in ["material", "body_material", "construction"]:
            assert detect_role(key) == "material", f"Failed for {key}"

    def test_uom_columns(self) -> None:
        for key in ["uom", "unit", "unit_of_measure"]:
            assert detect_role(key) == "uom", f"Failed for {key}"

    def test_category_columns(self) -> None:
        for key in ["category", "product_type"]:
            assert detect_role(key) == "category", f"Failed for {key}"

    def test_part_number_columns(self) -> None:
        for key in ["part_number", "sku", "model_number", "mfg_part_num"]:
            assert detect_role(key) == "part_number", f"Failed for {key}"

    def test_description_columns(self) -> None:
        for key in ["description", "part_desc", "product_name"]:
            assert detect_role(key) == "description", f"Failed for {key}"

    def test_unknown_column(self) -> None:
        assert detect_role("some_random_field") == "other"


class EnrichmentPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ReferenceStore()

    def _make_batch(self, rows: list[dict]) -> CatalogueBatch:
        return normalize_rows("test.csv", rows)

    def test_verified_manufacturer_exact_match(self) -> None:
        batch = self._make_batch([{"Manufacturer": "Parker Hannifin", "Part Number": "V-123"}])
        enriched = enrich_batch(batch, self.store)
        mfg_field = enriched.rows[0].field_map["manufacturer"]
        assert mfg_field.status == "verified"
        assert mfg_field.canonical_value == "Parker Hannifin"
        assert mfg_field.confidence == 1.0

    def test_verified_manufacturer_alias(self) -> None:
        batch = self._make_batch([{"Manufacturer": "Parker Hannifin Corp", "SKU": "X"}])
        enriched = enrich_batch(batch, self.store)
        mfg_field = enriched.rows[0].field_map["manufacturer"]
        assert mfg_field.status == "verified"
        assert mfg_field.canonical_value == "Parker Hannifin"
        assert mfg_field.confidence == 0.95

    def test_inferred_manufacturer_normalized(self) -> None:
        batch = self._make_batch([{"Manufacturer": "Parker Hannifin Industrial Division", "SKU": "Y"}])
        enriched = enrich_batch(batch, self.store)
        mfg_field = enriched.rows[0].field_map["manufacturer"]
        assert mfg_field.status == "inferred"
        assert mfg_field.canonical_value == "Parker Hannifin"
        assert mfg_field.confidence == 0.80

    def test_review_required_unknown_manufacturer(self) -> None:
        batch = self._make_batch([{"Manufacturer": "UnknownMfg XYZ", "SKU": "Z"}])
        enriched = enrich_batch(batch, self.store)
        mfg_field = enriched.rows[0].field_map["manufacturer"]
        assert mfg_field.status == "review_required"
        assert mfg_field.confidence == 0.0
        # Raw value preserved
        assert mfg_field.canonical_value == "UnknownMfg XYZ"

    def test_missing_field(self) -> None:
        batch = self._make_batch([{"Manufacturer": "--", "Brand": "Apollo", "SKU": "A"}])
        enriched = enrich_batch(batch, self.store)
        mfg_field = enriched.rows[0].field_map["manufacturer"]
        assert mfg_field.status == "missing"
        assert mfg_field.canonical_value is None

    def test_dash_wrapped_placeholder_detected_as_missing(self) -> None:
        # Unilog's own brand columns encode "no value" as a descriptive
        # phrase like "-- Unbranded --" rather than a bare token — this
        # must be recognized as a placeholder, not treated as unmatched
        # real data (which used to block auto-approval on nearly every
        # row in the real 1,000-SKU challenge dataset).
        batch = self._make_batch([{
            "Manufacturer": "Parker Hannifin",
            "Brand": "-- Unbranded --",
            "SKU": "H",
        }])
        enriched = enrich_batch(batch, self.store)
        brand_field = enriched.rows[0].field_map["brand"]
        assert brand_field.status == "missing"
        assert brand_field.canonical_value is None

    def test_placeholder_fields_excluded_from_confidence_average(self) -> None:
        # A row with a solid manufacturer match and only placeholder/blank
        # extra fields should have overall_confidence reflect the fields
        # actually resolved, not be dragged toward 0 by fields that carry
        # no data by design.
        batch = self._make_batch([{
            "Manufacturer": "Parker Hannifin",
            "Brand": "-- Unbranded --",
            "SKU": "I",
        }])
        enriched = enrich_batch(batch, self.store)
        row = enriched.rows[0]
        assert row.overall_confidence == 1.0

    def test_brand_enrichment(self) -> None:
        batch = self._make_batch([{"Brand": "Fisher Controls", "Part Number": "B-1"}])
        enriched = enrich_batch(batch, self.store)
        brand_field = enriched.rows[0].field_map["brand"]
        assert brand_field.status == "verified"
        assert brand_field.canonical_value == "Fisher"

    def test_material_enrichment(self) -> None:
        batch = self._make_batch([{"Material": "316 Stainless Steel", "SKU": "C"}])
        enriched = enrich_batch(batch, self.store)
        mat_field = enriched.rows[0].field_map["material"]
        assert mat_field.status == "verified"
        assert mat_field.canonical_value == "Stainless Steel 316"

    def test_uom_enrichment(self) -> None:
        batch = self._make_batch([{"UOM": "inches", "Part Number": "D"}])
        enriched = enrich_batch(batch, self.store)
        uom_field = enriched.rows[0].field_map["uom"]
        assert uom_field.status == "verified"
        assert uom_field.canonical_value == "in"
        assert uom_field.normalized_unit == "in"

    def test_category_enrichment(self) -> None:
        batch = self._make_batch([{"Category": "ball valve", "SKU": "E"}])
        enriched = enrich_batch(batch, self.store)
        cat_field = enriched.rows[0].field_map["category"]
        assert cat_field.status == "verified"
        assert cat_field.canonical_value == "Ball Valve"

    def test_part_number_passthrough(self) -> None:
        batch = self._make_batch([{"Part Number": "ABC-123-XYZ", "Description": "A valve"}])
        enriched = enrich_batch(batch, self.store)
        pn_field = enriched.rows[0].field_map["part_number"]
        assert pn_field.status == "verified"
        assert pn_field.canonical_value == "ABC-123-XYZ"
        assert pn_field.confidence == 1.0

    def test_description_passthrough(self) -> None:
        batch = self._make_batch([{"Description": "2 inch brass ball valve", "SKU": "F"}])
        enriched = enrich_batch(batch, self.store)
        desc_field = enriched.rows[0].field_map["description"]
        assert desc_field.status == "verified"
        assert desc_field.canonical_value == "2 inch brass ball valve"

    def test_evidence_preserved(self) -> None:
        batch = self._make_batch([{"Manufacturer": "Parker Hannifin", "SKU": "G"}])
        enriched = enrich_batch(batch, self.store)
        mfg_field = enriched.rows[0].field_map["manufacturer"]
        assert mfg_field.evidence.source_file == "test.csv"
        assert mfg_field.evidence.source_row == 2
        assert mfg_field.evidence.source_column == "manufacturer"
        assert mfg_field.evidence.raw_value == "Parker Hannifin"

    def test_row_overall_status_worst_case(self) -> None:
        batch = self._make_batch([{"Manufacturer": "--", "Brand": "Apollo", "SKU": "H"}])
        enriched = enrich_batch(batch, self.store)
        row = enriched.rows[0]
        assert row.overall_status == "missing"  # worst of missing + verified

    def test_batch_verified_rate(self) -> None:
        batch = self._make_batch([
            {"Manufacturer": "Parker Hannifin", "Brand": "Apollo", "Part Number": "V-1"},
        ])
        enriched = enrich_batch(batch, self.store)
        assert enriched.verified_rate > 0.5

    def test_multi_row_batch(self) -> None:
        batch = self._make_batch([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
            {"Manufacturer": "Emerson", "Part Number": "V-2"},
            {"Manufacturer": "UnknownCo", "Part Number": "V-3"},
        ])
        enriched = enrich_batch(batch, self.store)
        assert enriched.row_count == 3
        assert enriched.rows[0].field_map["manufacturer"].status == "verified"
        assert enriched.rows[1].field_map["manufacturer"].status == "verified"
        assert enriched.rows[2].field_map["manufacturer"].status == "review_required"

    def test_default_store_used_when_none(self) -> None:
        batch = self._make_batch([{"Manufacturer": "Parker Hannifin", "SKU": "I"}])
        enriched = enrich_batch(batch)  # no store passed
        assert enriched.rows[0].field_map["manufacturer"].canonical_value == "Parker Hannifin"

    def test_size_field_passthrough(self) -> None:
        batch = self._make_batch([{"Size": "2 inch", "SKU": "J"}])
        enriched = enrich_batch(batch, self.store)
        size_field = enriched.rows[0].field_map["size"]
        assert size_field.status == "verified"
        assert size_field.role == "size"


class EnrichedRowPropertyTests(unittest.TestCase):
    def test_verified_and_review_counts(self) -> None:
        store = ReferenceStore()
        batch = normalize_rows("test.csv", [
            {"Manufacturer": "Parker Hannifin", "Brand": "UnknownBrand", "Part Number": "X-1"}
        ])
        enriched = enrich_batch(batch, store)
        row = enriched.rows[0]
        assert row.verified_count >= 1  # part_number at minimum
        assert row.review_count >= 1    # unknown brand


if __name__ == "__main__":
    unittest.main()
