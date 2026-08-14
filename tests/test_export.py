"""Tests for the export module."""

import csv
import io
import json
import unittest

from backend.specledger.catalogue_ingestion import normalize_rows
from backend.specledger.enrichment import enrich_batch
from backend.specledger.reference_data import ReferenceStore
from backend.specledger.validation_engine import validate_batch
from backend.specledger.human_review import route_batch_for_review
from backend.specledger.export import (
    export_csv, export_json, export_commerce_csv, export_audit_json,
    COMMERCE_COLUMNS,
)


class ExportHelpers(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ReferenceStore()

    def _make_enriched(self, rows: list[dict]):
        batch = normalize_rows("test.csv", rows)
        return enrich_batch(batch, self.store)


class CSVExportTests(ExportHelpers):
    def test_csv_has_header(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        csv_str = export_csv(enriched)
        reader = csv.DictReader(io.StringIO(csv_str))
        headers = reader.fieldnames or []
        assert "row_number" in headers
        assert "manufacturer_canonical" in headers
        assert "manufacturer_raw" in headers

    def test_csv_row_count(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
            {"Manufacturer": "Emerson", "Part Number": "V-2"},
        ])
        csv_str = export_csv(enriched)
        reader = list(csv.DictReader(io.StringIO(csv_str)))
        assert len(reader) == 2

    def test_csv_includes_confidence(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        csv_str = export_csv(enriched, include_confidence=True)
        reader = csv.DictReader(io.StringIO(csv_str))
        headers = reader.fieldnames or []
        assert "manufacturer_confidence" in headers

    def test_csv_without_raw(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        csv_str = export_csv(enriched, include_raw=False)
        reader = csv.DictReader(io.StringIO(csv_str))
        headers = reader.fieldnames or []
        assert "manufacturer_raw" not in headers
        assert "manufacturer_canonical" in headers

    def test_csv_without_status(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        csv_str = export_csv(enriched, include_status=False)
        reader = csv.DictReader(io.StringIO(csv_str))
        headers = reader.fieldnames or []
        assert "manufacturer_status" not in headers


class JSONExportTests(ExportHelpers):
    def test_json_structure(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        json_str = export_json(enriched)
        data = json.loads(json_str)
        assert "batch" in data
        assert "rows" in data
        assert data["batch"]["row_count"] == 1

    def test_json_includes_evidence(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        json_str = export_json(enriched, include_evidence=True)
        data = json.loads(json_str)
        mfg = data["rows"][0]["fields"]["manufacturer"]
        assert "evidence" in mfg
        assert mfg["evidence"]["source_file"] == "test.csv"

    def test_json_without_evidence(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        json_str = export_json(enriched, include_evidence=False)
        data = json.loads(json_str)
        mfg = data["rows"][0]["fields"]["manufacturer"]
        assert "evidence" not in mfg

    def test_json_includes_validation(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        validation = validate_batch(enriched)
        json_str = export_json(enriched, validation=validation)
        data = json.loads(json_str)
        assert "validation" in data
        assert "auto_approve_count" in data["validation"]

    def test_json_field_confidence(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        json_str = export_json(enriched)
        data = json.loads(json_str)
        mfg = data["rows"][0]["fields"]["manufacturer"]
        assert mfg["confidence"] == 1.0
        assert mfg["status"] == "verified"


class CommerceCSVTests(ExportHelpers):
    def test_commerce_csv_columns(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100", "Material": "Brass"},
        ])
        csv_str = export_commerce_csv(enriched)
        reader = csv.DictReader(io.StringIO(csv_str))
        headers = reader.fieldnames or []
        for col in ["row_number", "manufacturer", "part_number", "material"]:
            assert col in headers

    def test_commerce_csv_values(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100", "Material": "316 Stainless Steel"},
        ])
        csv_str = export_commerce_csv(enriched)
        reader = list(csv.DictReader(io.StringIO(csv_str)))
        assert reader[0]["manufacturer"] == "Parker Hannifin"
        assert reader[0]["part_number"] == "V-100"
        assert reader[0]["material"] == "Stainless Steel 316"

    def test_commerce_csv_empty_fields(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        csv_str = export_commerce_csv(enriched)
        reader = list(csv.DictReader(io.StringIO(csv_str)))
        # Material, size, etc. should be empty but present
        assert reader[0]["material"] == ""


class AuditExportTests(ExportHelpers):
    def test_audit_json_structure(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        json_str = export_audit_json(enriched, batch_id="batch-1")
        data = json.loads(json_str)
        assert data["export_type"] == "audit"
        assert data["batch_id"] == "batch-1"
        assert data["row_count"] == 1
        assert "transformations" in data["rows"][0]

    def test_audit_detects_transformation(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Emerson", "Part Number": "V-100"},  # alias → "Emerson Electric"
        ])
        json_str = export_audit_json(enriched)
        data = json.loads(json_str)
        mfg_transform = next(
            t for t in data["rows"][0]["transformations"]
            if t["field"] == "manufacturer"
        )
        assert mfg_transform["was_transformed"] is True
        assert mfg_transform["supplier_value"] == "Emerson"
        assert mfg_transform["canonical_value"] == "Emerson Electric"

    def test_audit_with_review_queue(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "UnknownCo", "Part Number": "V-100"},
        ])
        validation = validate_batch(enriched)
        queue = route_batch_for_review("batch-1", enriched, validation)
        json_str = export_audit_json(enriched, review_queue=queue, batch_id="batch-1")
        data = json.loads(json_str)
        assert "review" in data["rows"][0]
        assert data["rows"][0]["review"]["state"] == "pending_review"

    def test_audit_includes_evidence(self) -> None:
        enriched = self._make_enriched([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        json_str = export_audit_json(enriched)
        data = json.loads(json_str)
        mfg_transform = next(
            t for t in data["rows"][0]["transformations"]
            if t["field"] == "manufacturer"
        )
        assert "evidence" in mfg_transform
        assert mfg_transform["evidence"]["source_file"] == "test.csv"


class SchemaOrgExportTests(ExportHelpers):
    def test_schema_org_jsonld_structure(self) -> None:
        from backend.specledger.export import export_schema_org_jsonld
        enriched = self._make_enriched([
            {
                "Manufacturer": "Parker Hannifin",
                "Part Number": "V-100",
                "Description": "2-way brass ball valve 150 psi",
                "Material": "Brass",
                "Size": "1/2 inch",
                "Pressure Rating": "150 PSI",
            },
        ])
        json_str = export_schema_org_jsonld(enriched)
        data = json.loads(json_str)
        assert data["@context"] == "https://schema.org/"
        assert "@graph" in data
        assert len(data["@graph"]) == 1
        product = data["@graph"][0]
        assert product["@type"] == "Product"
        assert product["sku"] == "V-100"
        assert product["mpn"] == "V-100"
        assert product["manufacturer"]["name"] == "Parker Hannifin"
        assert product["brand"]["name"] == "Parker Hannifin"
        assert "additionalProperty" in product
        prop_names = [p["name"] for p in product["additionalProperty"]]
        assert "Body Material" in prop_names


if __name__ == "__main__":
    unittest.main()
