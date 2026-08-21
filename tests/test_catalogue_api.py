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

            # Retrieve the batch. Per-field evidence is opt-in — list
            # responses omit it by default — and this asserts on it.
            batch_response = self.client.get(
                f"/catalogue/batches/{data['batch_id']}?include_fields=true"
            )
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

    def test_batch_rows_have_real_category(self) -> None:
        csv_path = self._make_csv([
            {"Mfg_Part_Num": "70-100-01", "Part_Desc": "1/2 in Ball Valve 600 PSI",
             "Part_Manuf": "Apollo Valves"},
        ])
        try:
            with csv_path.open("rb") as f:
                ingest_response = self.client.post(
                    "/catalogue/ingest",
                    files={"file": ("test.csv", f, "text/csv")},
                )
            batch_id = ingest_response.json()["batch_id"]
            response = self.client.get(f"/catalogue/batches/{batch_id}")
            assert response.status_code == 200
            row = response.json()["rows"][0]
            assert row["category"] == "Plumbing & Industrial Piping > Industrial Valves & Fittings > Ball Valves"
        finally:
            csv_path.unlink(missing_ok=True)

    def test_get_batch_row_unilog252(self) -> None:
        csv_path = self._make_csv([
            {"Mfg_Part_Num": "70-100-01", "Part_Desc": "1/2 in Ball Valve 600 PSI Stainless Steel",
             "Part_Manuf": "Apollo Valves"},
        ])
        try:
            with csv_path.open("rb") as f:
                ingest_response = self.client.post(
                    "/catalogue/ingest",
                    files={"file": ("test.csv", f, "text/csv")},
                )
            batch_id = ingest_response.json()["batch_id"]
            response = self.client.get(f"/catalogue/batches/{batch_id}/rows/2/unilog252")
            assert response.status_code == 200
            row = response.json()
            assert row["PART_NUMBER"] == "70-100-01"
            assert row["MANUFACTURER_NAME"] == "Apollo Valves"
            assert "Ball Valve" in row["Part_Desc"]
            assert row["ATTRIBUTE_LABEL 1"] == "Manufacturer"
        finally:
            csv_path.unlink(missing_ok=True)

    def test_get_batch_row_unilog252_not_found(self) -> None:
        csv_path = self._make_csv([
            {"Mfg_Part_Num": "X-1", "Part_Desc": "Test", "Part_Manuf": "Test Co"},
        ])
        try:
            with csv_path.open("rb") as f:
                ingest_response = self.client.post(
                    "/catalogue/ingest",
                    files={"file": ("test.csv", f, "text/csv")},
                )
            batch_id = ingest_response.json()["batch_id"]
            response = self.client.get(f"/catalogue/batches/{batch_id}/rows/999/unilog252")
            assert response.status_code == 404
        finally:
            csv_path.unlink(missing_ok=True)

    def test_list_audit_events(self) -> None:
        csv_path = self._make_csv([
            {"Mfg_Part_Num": "V-100", "Part_Desc": "Ball valve", "Part_Manuf": "Parker Hannifin"},
        ])
        try:
            with csv_path.open("rb") as f:
                ingest_response = self.client.post(
                    "/catalogue/ingest",
                    files={"file": ("test.csv", f, "text/csv")},
                )
            batch_id = ingest_response.json()["batch_id"]
            response = self.client.get(f"/catalogue/batches/{batch_id}/audit")
            assert response.status_code == 200
            data = response.json()
            assert data["batch_id"] == batch_id
            assert data["count"] >= 1
            assert data["events"][0]["batch_id"] == batch_id
            assert data["events"][0]["action"] in ("auto_approve", "submit_for_review")
        finally:
            csv_path.unlink(missing_ok=True)

    def test_export_csv_endpoint(self) -> None:
        csv_path = self._make_csv([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        try:
            with csv_path.open("rb") as f:
                ingest_res = self.client.post("/catalogue/ingest", files={"file": ("export_test.csv", f, "text/csv")})
            batch_id = ingest_res.json()["batch_id"]

            res = self.client.get(f"/catalogue/batches/{batch_id}/export?format=csv")
            assert res.status_code == 200
            assert "text/csv" in res.headers["content-type"]
            assert "Parker Hannifin" in res.text
        finally:
            csv_path.unlink(missing_ok=True)

    def test_export_commerce_csv_endpoint(self) -> None:
        csv_path = self._make_csv([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        try:
            with csv_path.open("rb") as f:
                ingest_res = self.client.post("/catalogue/ingest", files={"file": ("export_test.csv", f, "text/csv")})
            batch_id = ingest_res.json()["batch_id"]

            res = self.client.get(f"/catalogue/batches/{batch_id}/export?format=commerce_csv")
            assert res.status_code == 200
            assert "text/csv" in res.headers["content-type"]
        finally:
            csv_path.unlink(missing_ok=True)

    def test_export_json_endpoint(self) -> None:
        csv_path = self._make_csv([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        try:
            with csv_path.open("rb") as f:
                ingest_res = self.client.post("/catalogue/ingest", files={"file": ("export_test.csv", f, "text/csv")})
            batch_id = ingest_res.json()["batch_id"]

            res = self.client.get(f"/catalogue/batches/{batch_id}/export?format=json")
            assert res.status_code == 200
            assert "application/json" in res.headers["content-type"]
            data = res.json()
            assert "batch" in data
            assert "rows" in data
        finally:
            csv_path.unlink(missing_ok=True)

    def test_export_audit_endpoint(self) -> None:
        csv_path = self._make_csv([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        try:
            with csv_path.open("rb") as f:
                ingest_res = self.client.post("/catalogue/ingest", files={"file": ("export_test.csv", f, "text/csv")})
            batch_id = ingest_res.json()["batch_id"]

            res = self.client.get(f"/catalogue/batches/{batch_id}/export?format=audit")
            assert res.status_code == 200
            data = res.json()
            assert data["export_type"] == "audit"
        finally:
            csv_path.unlink(missing_ok=True)

    def test_pending_review_endpoint(self) -> None:
        csv_path = self._make_csv([
            {"Manufacturer": "UnknownMfg999", "Part Number": "V-100"},
        ])
        try:
            with csv_path.open("rb") as f:
                ingest_res = self.client.post("/catalogue/ingest", files={"file": ("review_test.csv", f, "text/csv")})
            batch_id = ingest_res.json()["batch_id"]

            res = self.client.get(f"/catalogue/batches/{batch_id}/review/pending")
            assert res.status_code == 200
            data = res.json()
            assert data["count"] >= 1
        finally:
            csv_path.unlink(missing_ok=True)

    def test_review_row_action(self) -> None:
        csv_path = self._make_csv([
            {"Manufacturer": "UnknownMfg999", "Part Number": "V-100"},
        ])
        try:
            with csv_path.open("rb") as f:
                ingest_res = self.client.post("/catalogue/ingest", files={"file": ("review_action.csv", f, "text/csv")})
            batch_id = ingest_res.json()["batch_id"]

            res = self.client.post(
                f"/catalogue/batches/{batch_id}/rows/2/review",
                json={"action": "approve", "reviewer": "user@example.com", "comment": "Verified manually"},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["review_state"] == "approved"
        finally:
            csv_path.unlink(missing_ok=True)

    def test_batch_rows_are_paginated_and_cover_every_row_once(self) -> None:
        rows = [{"Manufacturer": "Parker Hannifin", "Part Number": f"V-{i}"} for i in range(12)]
        csv_path = self._make_csv(rows)
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("paged.csv", f, "text/csv")}
                ).json()["batch_id"]

            first = self.client.get(f"/catalogue/batches/{batch_id}?limit=5").json()
            # row_count is the batch total; returned_rows is this page.
            self.assertEqual(first["row_count"], 12)
            self.assertEqual(first["returned_rows"], 5)
            self.assertEqual(len(first["rows"]), 5)
            self.assertTrue(first["has_more"])

            seen: list[int] = []
            offset = 0
            while True:
                page = self.client.get(
                    f"/catalogue/batches/{batch_id}?limit=5&offset={offset}"
                ).json()
                seen.extend(r["row_number"] for r in page["rows"])
                if not page["has_more"]:
                    break
                offset += 5

            self.assertEqual(len(seen), 12)
            self.assertEqual(len(set(seen)), 12, "pagination duplicated or skipped rows")
        finally:
            csv_path.unlink(missing_ok=True)

    def test_list_rows_omit_field_evidence_but_single_row_keeps_it(self) -> None:
        # Per-field evidence is the bulk of the payload and list views don't
        # read it, so it must not ride along on every row by default.
        csv_path = self._make_csv([{"Manufacturer": "Parker Hannifin", "Part Number": "V-1"}])
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("fields.csv", f, "text/csv")}
                ).json()["batch_id"]

            listed = self.client.get(f"/catalogue/batches/{batch_id}").json()["rows"][0]
            self.assertNotIn("fields", listed)
            # The list view reads these instead, so they must survive.
            self.assertIn("raw_values", listed)
            self.assertIn("category", listed)

            opted_in = self.client.get(
                f"/catalogue/batches/{batch_id}?include_fields=true"
            ).json()["rows"][0]
            self.assertIn("fields", opted_in)

            single = self.client.get(f"/catalogue/batches/{batch_id}/rows/2").json()
            self.assertIn("fields", single)
        finally:
            csv_path.unlink(missing_ok=True)

    def test_ingest_never_calls_the_llm_unless_explicitly_asked(self) -> None:
        # The LLM tier is opt-in and billed. An ordinary ingest must not
        # reach it, and asking for it without a key must stay a no-op rather
        # than failing the upload.
        from unittest.mock import patch

        csv_path = self._make_csv([{"Manufacturer": "Generic", "Part Number": "X-1"}])
        try:
            with patch("backend.specledger.llm_enricher.requests.post") as post:
                with csv_path.open("rb") as f:
                    default_res = self.client.post(
                        "/catalogue/ingest", files={"file": ("no_ai.csv", f, "text/csv")}
                    )
                self.assertEqual(default_res.status_code, 200)
                self.assertEqual(post.call_count, 0)

                with patch.dict("os.environ", {"GEMINI_API_KEY": ""}, clear=False):
                    with csv_path.open("rb") as f:
                        opted_in_res = self.client.post(
                            "/catalogue/ingest?ai_assist=true",
                            files={"file": ("ai_no_key.csv", f, "text/csv")},
                        )
                self.assertEqual(opted_in_res.status_code, 200)
                self.assertEqual(post.call_count, 0)
        finally:
            csv_path.unlink(missing_ok=True)

    def test_row_review_state_agrees_with_review_summary(self) -> None:
        # review_state and review_summary are both derived from the routing
        # decision, so they must agree within a single response. They used to
        # disagree because the per-row value was replayed from what was
        # persisted at ingest while the summary was recomputed live.
        csv_path = self._make_csv([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
            {"Manufacturer": "UnknownMfg999", "Part Number": "V-200"},
            {"Manufacturer": "UnknownMfg998", "Part Number": "V-300"},
        ])
        try:
            with csv_path.open("rb") as f:
                ingest_res = self.client.post(
                    "/catalogue/ingest", files={"file": ("consistency.csv", f, "text/csv")}
                )
            batch_id = ingest_res.json()["batch_id"]

            batch = self.client.get(f"/catalogue/batches/{batch_id}").json()
            summary = batch["review_summary"]

            counts: dict[str, int] = {}
            for row in batch["rows"]:
                state = row["review_state"]
                counts[state] = counts.get(state, 0) + 1

            for state in ("pending_review", "auto_approved", "approved"):
                assert counts.get(state, 0) == summary[state], (
                    f"per-row {state}={counts.get(state, 0)} but "
                    f"summary says {summary[state]}"
                )
        finally:
            csv_path.unlink(missing_ok=True)

    def test_rebuild_preserves_human_decisions_but_not_auto_routing(self) -> None:
        # A queue rebuild (which happens whenever the process-local cache is
        # lost, e.g. after a redeploy) must re-derive auto-routing from the
        # current validation rules rather than replaying the state persisted
        # at ingest time — otherwise a row that newer rules can auto-approve
        # stays stranded in the pending queue forever. Real human decisions
        # must still survive that rebuild.
        from backend.specledger import catalogue_api

        csv_path = self._make_csv([
            {"Manufacturer": "UnknownMfg999", "Part Number": "V-100"},
            {"Manufacturer": "UnknownMfg998", "Part Number": "V-200"},
        ])
        try:
            with csv_path.open("rb") as f:
                ingest_res = self.client.post(
                    "/catalogue/ingest", files={"file": ("rebuild_test.csv", f, "text/csv")}
                )
            batch_id = ingest_res.json()["batch_id"]

            approve_res = self.client.post(
                f"/catalogue/batches/{batch_id}/rows/2/review",
                json={"action": "approve", "reviewer": "user@example.com"},
            )
            assert approve_res.status_code == 200

            # Drop the process-local caches to force a rebuild from storage.
            catalogue_api._review_queues.pop(batch_id, None)
            catalogue_api._batch_results.pop(batch_id, None)

            queue = catalogue_api._get_review_queue(batch_id)
            assert queue is not None

            # The human approval survived the rebuild.
            assert queue.get_row(batch_id, 2).state.value == "approved"

            # The untouched row was re-derived by the current rules, not
            # restored from its persisted auto-routed state.
            untouched = queue.get_row(batch_id, 3)
            expected = "auto_approved" if untouched.validation.can_auto_approve else "pending_review"
            assert untouched.state.value == expected
        finally:
            csv_path.unlink(missing_ok=True)

    def test_sources_endpoint(self) -> None:
        csv_path = self._make_csv([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        try:
            with csv_path.open("rb") as f:
                ingest_res = self.client.post("/catalogue/ingest", files={"file": ("sources_test.csv", f, "text/csv")})
            batch_id = ingest_res.json()["batch_id"]

            res = self.client.get(f"/catalogue/batches/{batch_id}/sources")
            assert res.status_code == 200
            data = res.json()
            assert "sources" in data
        finally:
            csv_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

