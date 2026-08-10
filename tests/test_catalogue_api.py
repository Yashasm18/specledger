"""Tests for the catalogue API endpoints."""

import csv
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.specledger.http_api import app


class CatalogueApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def _make_csv(self, rows: list[dict]) -> Path:
        """Write a temporary CSV file and return its path."""
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="", encoding="utf-8")
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(tmp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        tmp.close()
        return Path(tmp.name)

    def test_reference_manufacturers_count(self) -> None:
        response = self.client.get("/catalogue/reference/manufacturers")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 20

    def test_reference_brands_count(self) -> None:
        response = self.client.get("/catalogue/reference/brands")
        assert response.status_code == 200
        assert response.json()["count"] >= 14

    def test_reference_categories_count(self) -> None:
        response = self.client.get("/catalogue/reference/categories")
        assert response.status_code == 200
        assert response.json()["count"] >= 18

    def test_match_manufacturer_exact(self) -> None:
        response = self.client.post("/catalogue/reference/match/manufacturer?raw=Parker%20Hannifin")
        assert response.status_code == 200
        data = response.json()
        assert data["canonical"] == "Parker Hannifin"
        assert data["confidence"] == 1.0
        assert data["match_type"] == "exact"

    def test_match_manufacturer_alias(self) -> None:
        response = self.client.post("/catalogue/reference/match/manufacturer?raw=Emerson%20Electric%20Co.")
        assert response.status_code == 200
        data = response.json()
        assert data["canonical"] == "Emerson Electric"
        assert data["match_type"] == "alias"

    def test_match_brand(self) -> None:
        response = self.client.post("/catalogue/reference/match/brand?raw=Fisher%20Controls")
        assert response.status_code == 200
        data = response.json()
        assert data["canonical"] == "Fisher"

    def test_normalize_uom(self) -> None:
        response = self.client.post("/catalogue/reference/normalize/uom?raw=inches")
        assert response.status_code == 200
        data = response.json()
        assert data["canonical"] == "in"
        assert data["dimension"] == "length"

    def test_normalize_material(self) -> None:
        response = self.client.post("/catalogue/reference/normalize/material?raw=316%20Stainless%20Steel")
        assert response.status_code == 200
        data = response.json()
        assert data["canonical"] == "Stainless Steel 316"

    def test_ingest_csv(self) -> None:
        csv_path = self._make_csv([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100", "Material": "Brass"},
            {"Manufacturer": "Emerson", "Part Number": "V-200", "Material": "316 SS"},
        ])
        try:
            with csv_path.open("rb") as f:
                response = self.client.post(
                    "/catalogue/ingest",
                    files={"file": ("test_products.csv", f, "text/csv")},
                )
            assert response.status_code == 200
            data = response.json()
            assert data["row_count"] == 2
            assert "batch_id" in data
            assert data["verified_rate"] > 0.5

            # Retrieve the batch
            batch_response = self.client.get(f"/catalogue/batches/{data['batch_id']}")
            assert batch_response.status_code == 200
            batch = batch_response.json()
            assert len(batch["rows"]) == 2

            # Check first row enrichment
            first_row = batch["rows"][0]
            mfg_field = next(f for f in first_row["fields"] if f["column"] == "manufacturer")
            assert mfg_field["canonical_value"] == "Parker Hannifin"
            assert mfg_field["status"] == "verified"
        finally:
            csv_path.unlink(missing_ok=True)

    def test_ingest_rejects_unsupported_format(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(b"not a real docx")
            tmp_path = tmp.name
        try:
            with open(tmp_path, "rb") as f:
                response = self.client.post(
                    "/catalogue/ingest",
                    files={"file": ("test.docx", f, "application/octet-stream")},
                )
            assert response.status_code == 415
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_ingest_rejects_empty_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            with open(tmp_path, "rb") as f:
                response = self.client.post(
                    "/catalogue/ingest",
                    files={"file": ("empty.csv", f, "text/csv")},
                )
            assert response.status_code == 400
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_list_batches(self) -> None:
        response = self.client.get("/catalogue/batches")
        assert response.status_code == 200
        data = response.json()
        assert "batches" in data
        assert "count" in data

    def test_batch_not_found(self) -> None:
        response = self.client.get("/catalogue/batches/nonexistent-id")
        assert response.status_code == 404

    def test_get_batch_row(self) -> None:
        csv_path = self._make_csv([
            {"Manufacturer": "Honeywell", "Part Number": "H-100"},
        ])
        try:
            with csv_path.open("rb") as f:
                ingest_response = self.client.post(
                    "/catalogue/ingest",
                    files={"file": ("test.csv", f, "text/csv")},
                )
            batch_id = ingest_response.json()["batch_id"]
            row_response = self.client.get(f"/catalogue/batches/{batch_id}/rows/2")
            assert row_response.status_code == 200
            row = row_response.json()
            assert row["row_number"] == 2
        finally:
            csv_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
