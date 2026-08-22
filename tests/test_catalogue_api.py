"""Tests for the catalogue API endpoints."""

import csv
import tempfile
import time
import unittest
from urllib.parse import quote
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
            # Attribute slots hold specifications, never identity fields:
            # Unilog's own delivery examples use them for Series, Voltage
            # Rating, Material and the like, and MANUFACTURER_NAME /
            # MANUFACTURER_PART_NUMBER already have dedicated columns. This
            # description states no extractable spec, so the slot is honestly
            # empty rather than padded with something already delivered.
            assert row["ATTRIBUTE_LABEL 1"] not in ("Manufacturer", "Part Number")
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

    def test_pending_review_rows_identify_themselves(self) -> None:
        # The queue is priority-ordered across the whole batch, so its rows
        # are mostly outside whatever catalogue page is loaded. Without the
        # identity inline, the UI rendered "Row 743" for every entry and a
        # reviewer could not tell what they were approving.
        csv_path = self._make_csv([
            {"Mfg_Part_Num": "V-100", "Part_Desc": "2 in Gate Valve Cast Iron",
             "Part_Manuf": "UnknownMfg999"},
        ])
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("ident.csv", f, "text/csv")}
                ).json()["batch_id"]

            pending = self.client.get(
                f"/catalogue/batches/{batch_id}/review/pending"
            ).json()["pending_rows"]
            self.assertTrue(pending)
            row = pending[0]
            self.assertEqual(row["part_number"], "V-100")
            self.assertEqual(row["description"], "2 in Gate Valve Cast Iron")
            self.assertEqual(row["manufacturer"], "UnknownMfg999")
        finally:
            csv_path.unlink(missing_ok=True)

    def test_audit_export_carries_review_decisions_and_the_real_batch_id(self) -> None:
        # The audit export is the compliance artifact. Transformations alone
        # are not an audit — the human decisions are the half that matters.
        # It previously shipped with neither, because the review queue was
        # looked up by the caller's alias ("latest" is never a key) and via
        # the raw cache rather than the accessor that rebuilds from storage.
        import json as _json

        csv_path = self._make_csv([
            {"Manufacturer": "UnknownMfg999", "Part Number": "V-1",
             "Description": "2 in Gate Valve Cast Iron"},
        ])
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("audit.csv", f, "text/csv")}
                ).json()["batch_id"]

            for identifier in (batch_id, "latest"):
                body = _json.loads(
                    self.client.get(
                        f"/catalogue/batches/{identifier}/export?format=audit"
                    ).text
                )
                # Never the alias — an audit file must name the batch it describes.
                self.assertEqual(body["batch_id"], batch_id)
                self.assertNotEqual(body["batch_id"], "latest")
                reviewed = [r for r in body["rows"] if r.get("review")]
                self.assertTrue(
                    reviewed, f"audit export via {identifier!r} carried no review decisions"
                )
                self.assertIn("state", reviewed[0]["review"])
                self.assertIn("audit_trail", reviewed[0]["review"])
        finally:
            csv_path.unlink(missing_ok=True)

    def test_verify_endpoint_reports_honest_failure_without_inventing_sources(self) -> None:
        # The whole value of live verification is that it can say "nothing
        # found". A fabricated URL here would be worse than no answer.
        from unittest.mock import patch
        from backend.specledger.source_discovery import SourceDiscoveryResult

        csv_path = self._make_csv([{"Manufacturer": "Nonexistent Vendor Ltd", "Part Number": "ZZZ-999"}])
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("verify.csv", f, "text/csv")}
                ).json()["batch_id"]

            empty = SourceDiscoveryResult(manufacturer="Nonexistent Vendor Ltd", part_number="ZZZ-999")
            with patch("backend.specledger.catalogue_api.discover_sources_live", return_value=empty) as live:
                res = self.client.post(f"/catalogue/batches/{batch_id}/rows/2/verify")

            live.assert_called_once()
            body = res.json()
            self.assertEqual(res.status_code, 200)
            self.assertFalse(body["verified"])
            self.assertEqual(body["sources"], [])
            self.assertEqual(body["verified_source_count"], 0)
            self.assertTrue(body["fetched_at_request_time"])
        finally:
            csv_path.unlink(missing_ok=True)

    def test_verify_endpoint_surfaces_the_match_snippet_and_corrected_manufacturer(self) -> None:
        from unittest.mock import patch
        from backend.specledger.source_discovery import (
            DiscoveredSource, SourceDiscoveryResult, SourceStatus, SourceType,
        )

        csv_path = self._make_csv([{"Manufacturer": "Appliance Dealers Cooperative", "Part Number": "WDTS7024RZ"}])
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("verify2.csv", f, "text/csv")}
                ).json()["batch_id"]

            found = SourceDiscoveryResult(
                manufacturer="Appliance Dealers Cooperative", part_number="WDTS7024RZ",
                resolved_manufacturer="Whirlpool Corporation", discovery_mode="live",
            )
            found.sources.append(DiscoveredSource(
                url="https://www.whirlpool.com/p/WDTS7024RZ",
                source_type=SourceType.PRODUCT_PAGE, status=SourceStatus.VERIFIED,
                manufacturer="Whirlpool Corporation", part_number="WDTS7024RZ",
                domain="whirlpool.com", confidence=0.9,
                match_snippet="Whirlpool WDTS7024RZ Dishwasher, 41 dBA",
                extracted_attributes=(("Voltage Rating", "120 V"),),
            ))
            with patch("backend.specledger.catalogue_api.discover_sources_live", return_value=found):
                body = self.client.post(f"/catalogue/batches/{batch_id}/rows/2/verify").json()

            self.assertTrue(body["verified"])
            # The distributor -> real manufacturer correction must be explicit.
            self.assertTrue(body["manufacturer_was_corrected"])
            self.assertEqual(body["resolved_manufacturer"], "Whirlpool Corporation")
            # The snippet is the receipt that makes the claim checkable.
            self.assertIn("WDTS7024RZ", body["sources"][0]["match_snippet"])
            self.assertEqual(body["extracted_attributes"][0]["label"], "Voltage Rating")
            self.assertEqual(
                body["extracted_attributes"][0]["source_url"],
                "https://www.whirlpool.com/p/WDTS7024RZ",
            )
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

    def test_human_decision_survives_rebuild_as_an_audit_event(self) -> None:
        # A rebuild re-runs the pipeline, which mints a fresh routing event
        # per row. If the human decision is replayed by assigning state
        # directly, the row reads "approved" while the audit trail contains
        # nobody approving it — the compliance artifact contradicts the state
        # it exists to explain.
        from backend.specledger import catalogue_api

        csv_path = self._make_csv([
            {"Manufacturer": "UnknownMfg999", "Part Number": "V-100"},
            {"Manufacturer": "UnknownMfg998", "Part Number": "V-200"},
        ])
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("audit_rebuild.csv", f, "text/csv")}
                ).json()["batch_id"]

            approved = self.client.post(
                f"/catalogue/batches/{batch_id}/rows/2/review",
                json={"action": "approve", "reviewer": "Catalog QA Reviewer (Catalog QA)"},
            )
            self.assertEqual(approved.status_code, 200)

            catalogue_api._review_queues.pop(batch_id, None)
            catalogue_api._batch_results.pop(batch_id, None)

            events = self.client.get(
                f"/catalogue/batches/{batch_id}/audit?limit=50"
            ).json()["events"]

            approve_events = [
                e for e in events
                if e["row_number"] == 2 and e["action"] == "approve"
            ]
            self.assertEqual(
                len(approve_events), 1,
                "the approval vanished from the audit trail on rebuild",
            )
            self.assertEqual(
                approve_events[0]["reviewer"], "Catalog QA Reviewer (Catalog QA)"
            )
            self.assertEqual(approve_events[0]["new_state"], "approved")

        finally:
            csv_path.unlink(missing_ok=True)

    def test_rebuilt_audit_event_says_it_was_reconstructed(self) -> None:
        # The original reviewer comment is not persisted, so the restored
        # event must not imply it is the verbatim original record.
        from backend.specledger import catalogue_api

        csv_path = self._make_csv([
            {"Manufacturer": "UnknownMfg999", "Part Number": "V-100"},
            {"Manufacturer": "UnknownMfg998", "Part Number": "V-200"},
        ])
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("audit_note.csv", f, "text/csv")}
                ).json()["batch_id"]

            self.client.post(
                f"/catalogue/batches/{batch_id}/rows/2/review",
                json={"action": "approve", "reviewer": "qa@example.com",
                      "comment": "checked against the datasheet"},
            )
            catalogue_api._review_queues.pop(batch_id, None)
            catalogue_api._batch_results.pop(batch_id, None)

            events = self.client.get(
                f"/catalogue/batches/{batch_id}/audit?limit=50"
            ).json()["events"]
            restored = next(
                e for e in events if e["row_number"] == 2 and e["action"] == "approve"
            )
            self.assertIn("reconstructed", (restored["comment"] or "").lower())
        finally:
            csv_path.unlink(missing_ok=True)

    def test_restored_event_carries_the_real_decision_time(self) -> None:
        # The restored event must be dated when the human actually decided,
        # not when the container happened to restart — otherwise every
        # approval in the trail appears to have happened at deploy time.
        from backend.specledger import catalogue_api

        csv_path = self._make_csv([
            {"Manufacturer": "UnknownMfg999", "Part Number": "V-100"},
            {"Manufacturer": "UnknownMfg998", "Part Number": "V-200"},
        ])
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("audit_when.csv", f, "text/csv")}
                ).json()["batch_id"]

            self.client.post(
                f"/catalogue/batches/{batch_id}/rows/2/review",
                json={"action": "approve", "reviewer": "qa@example.com"},
            )
            decided_at = time.time()

            catalogue_api._review_queues.pop(batch_id, None)
            catalogue_api._batch_results.pop(batch_id, None)
            # Rebuild happens strictly later than the decision.
            time.sleep(0.05)

            events = self.client.get(
                f"/catalogue/batches/{batch_id}/audit?limit=50"
            ).json()["events"]
            restored = next(
                e for e in events if e["row_number"] == 2 and e["action"] == "approve"
            )
            routing = next(
                e for e in events
                if e["row_number"] == 2 and e["action"] in {"submit_for_review", "auto_approve"}
            )
            # Dated from the decision, and earlier than the rebuild's own event.
            self.assertLess(abs(restored["timestamp"] - decided_at), 5.0)
            self.assertLess(restored["timestamp"], routing["timestamp"])
        finally:
            csv_path.unlink(missing_ok=True)

    def test_rows_without_a_human_decision_get_no_review_event(self) -> None:
        # Only real decisions may appear as human actions. An auto-routed row
        # must not acquire an approve/reject event from the rebuild.
        from backend.specledger import catalogue_api

        csv_path = self._make_csv([
            {"Manufacturer": "UnknownMfg999", "Part Number": "V-100"},
            {"Manufacturer": "UnknownMfg998", "Part Number": "V-200"},
        ])
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("audit_clean.csv", f, "text/csv")}
                ).json()["batch_id"]

            catalogue_api._review_queues.pop(batch_id, None)
            catalogue_api._batch_results.pop(batch_id, None)

            events = self.client.get(
                f"/catalogue/batches/{batch_id}/audit?limit=50"
            ).json()["events"]
            human_actions = [
                e for e in events if e["action"] in {"approve", "reject", "correct"}
            ]
            self.assertEqual(human_actions, [])
            self.assertTrue(all(e["reviewer"] is None for e in events))
        finally:
            csv_path.unlink(missing_ok=True)

    def test_audit_can_filter_to_human_actions_across_the_whole_trail(self) -> None:
        # Restored approvals are dated when the human decided, which is older
        # than the routing events a rebuild mints. Sorted newest-first they
        # fall outside any reasonable page, so "Human approvals" must be a
        # server-side filter — filtering the fetched page finds nothing and
        # reports "no audit events" while the approvals plainly exist.
        from backend.specledger import catalogue_api

        rows = [
            {"Manufacturer": f"UnknownMfg{i}", "Part Number": f"V-{i}"}
            for i in range(30)
        ]
        csv_path = self._make_csv(rows)
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("audit_filter.csv", f, "text/csv")}
                ).json()["batch_id"]

            self.client.post(
                f"/catalogue/batches/{batch_id}/rows/2/review",
                json={"action": "approve", "reviewer": "qa@example.com"},
            )
            catalogue_api._review_queues.pop(batch_id, None)
            catalogue_api._batch_results.pop(batch_id, None)

            human = self.client.get(
                f"/catalogue/batches/{batch_id}/audit?actor=human&limit=5"
            ).json()
            self.assertEqual(human["total_events"], 1)
            self.assertEqual(len(human["events"]), 1)
            self.assertEqual(human["events"][0]["reviewer"], "qa@example.com")

            system = self.client.get(
                f"/catalogue/batches/{batch_id}/audit?actor=system&limit=100"
            ).json()
            self.assertTrue(all(e["reviewer"] is None for e in system["events"]))
            self.assertGreater(system["total_events"], 1)

            everything = self.client.get(
                f"/catalogue/batches/{batch_id}/audit?limit=100"
            ).json()
            self.assertEqual(
                everything["total_events"],
                human["total_events"] + system["total_events"],
            )
        finally:
            csv_path.unlink(missing_ok=True)

    def test_unilog252_endpoint_resolves_a_foreign_columned_file(self) -> None:
        # The CSV export and this endpoint each kept their own copy of the
        # "which column means what" mapping, so fixing the export alone left
        # the inspector still showing UNKNOWN-PN. Both now share one resolver;
        # this covers the endpoint path specifically.
        csv_path = self._make_csv([{
            "SKU": "IV-8890",
            "Item Description": "IV-8890 IV Infusion Pump 15A 120V Volumetric",
            "Vendor": "Baxter International",
        }])
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("foreign.csv", f, "text/csv")}
                ).json()["batch_id"]

            body = self.client.get(
                f"/catalogue/batches/{batch_id}/rows/2/unilog252"
            ).json()
            row = body.get("unilog252") or body.get("row") or body

            self.assertEqual(row["Mfg_Part_Num"], "IV-8890")
            self.assertEqual(row["MANUFACTURER_NAME"], "Baxter International")
            self.assertIn("Infusion Pump", row["Part_Desc"])
            # Spec extraction is column-name agnostic too.
            labels = {
                row.get(f"ATTRIBUTE_LABEL {i}"): row.get(f"ATTRIBUTE_VALUE {i}")
                for i in range(1, 6)
            }
            self.assertEqual(labels.get("Voltage Rating"), "120")
            self.assertEqual(labels.get("Amperage Rating"), "15")
        finally:
            csv_path.unlink(missing_ok=True)

    def test_organizations_do_not_see_each_other_s_batches(self) -> None:
        # The workspace switcher in the dashboard is an organization_id, so
        # separation has to be real: a catalogue uploaded into one workspace
        # must not appear in another, or "switch workspace" is a label.
        csv_path = self._make_csv([{"Manufacturer": "Parker Hannifin", "Part Number": "V-1"}])
        try:
            with csv_path.open("rb") as f:
                created = self.client.post(
                    "/catalogue/ingest?organization_id=sandbox",
                    files={"file": ("sandboxed.csv", f, "text/csv")},
                ).json()["batch_id"]

            listed = self.client.get("/catalogue/batches?organization_id=sandbox").json()
            self.assertIn("sandboxed.csv", [b["source_name"] for b in listed["batches"]])

            other = self.client.get("/catalogue/batches?organization_id=someone_else").json()
            self.assertNotIn(
                "sandboxed.csv", [b["source_name"] for b in other.get("batches", [])],
                "a batch leaked across organizations",
            )

            # And the rows are not reachable by id from another organization.
            cross = self.client.get(
                f"/catalogue/batches/{created}?organization_id=someone_else"
            )
            self.assertEqual(cross.status_code, 404)
        finally:
            csv_path.unlink(missing_ok=True)

    def test_a_non_default_organization_starts_empty(self) -> None:
        # Seeding exists so a fresh deployment has something to show. Applied
        # to every organization it filled the dashboard's "Evaluation Sandbox"
        # with the challenge dataset as soon as it was opened, which is the
        # opposite of what that workspace is for.
        listed = self.client.get("/catalogue/batches?organization_id=fresh_org").json()
        self.assertEqual(listed.get("batches", []), [])

        # Resolving "latest" must not conjure one either.
        res = self.client.get("/catalogue/batches/latest?organization_id=fresh_org")
        self.assertEqual(res.status_code, 404)

        still_empty = self.client.get("/catalogue/batches?organization_id=fresh_org").json()
        self.assertEqual(still_empty.get("batches", []), [])

    def test_categories_endpoint_reports_the_real_distribution(self) -> None:
        # The dashboard's category chips were five hardcoded verticals that
        # only matched the sample data's vocabulary, filtering the loaded page
        # by keyword. On any other catalogue they emptied the table. The chips
        # have to come from what the batch actually contains.
        rows = [
            {"Manufacturer": "Apollo Valves", "Part Number": "V-1",
             "Description": "1/2 in Bronze Ball Valve 600 PSI"},
            {"Manufacturer": "Apollo Valves", "Part Number": "V-2",
             "Description": "2 in Bronze Ball Valve 600 PSI"},
            {"Manufacturer": "Leviton", "Part Number": "S-1",
             "Description": "20A Industrial Rocker Switch"},
            {"Manufacturer": "UnknownCo", "Part Number": "X-1",
             "Description": "X-1 Widget"},
        ]
        csv_path = self._make_csv(rows)
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("cats.csv", f, "text/csv")}
                ).json()["batch_id"]

            body = self.client.get(f"/catalogue/batches/{batch_id}/categories").json()
            self.assertEqual(body["total_rows"], 4)
            self.assertEqual(body["unclassified"], 1)

            by_path = {c["classpath"]: c["count"] for c in body["categories"]}
            valves = next(p for p in by_path if "Ball Valves" in p)
            self.assertEqual(by_path[valves], 2)
            # Ordered by how many rows fall in each, so the chips are useful.
            self.assertGreaterEqual(body["categories"][0]["count"], body["categories"][-1]["count"])
            # A label short enough to put on a button.
            self.assertTrue(body["categories"][0]["label"])

        finally:
            csv_path.unlink(missing_ok=True)

    def test_rows_can_be_filtered_by_category_across_the_batch(self) -> None:
        rows = [
            {"Manufacturer": "Apollo Valves", "Part Number": f"V-{i}",
             "Description": "1/2 in Bronze Ball Valve 600 PSI"}
            for i in range(8)
        ]
        rows += [
            {"Manufacturer": "Leviton", "Part Number": f"S-{i}",
             "Description": "20A Industrial Rocker Switch"}
            for i in range(3)
        ]
        csv_path = self._make_csv(rows)
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("catfilter.csv", f, "text/csv")}
                ).json()["batch_id"]

            cats = self.client.get(f"/catalogue/batches/{batch_id}/categories").json()
            valve_path = next(
                c["classpath"] for c in cats["categories"] if "Ball Valves" in c["classpath"]
            )

            # Filtered across the whole batch, before paging — the defect in
            # the old chips was filtering only the rows already on screen.
            encoded = quote(valve_path, safe="")
            page = self.client.get(
                f"/catalogue/batches/{batch_id}?limit=3&category={encoded}"
            ).json()
            self.assertEqual(page["matched_rows"], 8)
            self.assertEqual(page["returned_rows"], 3)
            self.assertTrue(page["has_more"])

            second = self.client.get(
                f"/catalogue/batches/{batch_id}?limit=3&offset=6&category={encoded}"
            ).json()
            self.assertEqual(second["returned_rows"], 2)
            self.assertFalse(second["has_more"])

            unclassified = self.client.get(
                f"/catalogue/batches/{batch_id}?category=__unclassified__"
            ).json()
            self.assertEqual(unclassified["matched_rows"], 0)
        finally:
            csv_path.unlink(missing_ok=True)

    def test_a_batch_can_be_deleted(self) -> None:
        # Without this there is no way to remove an uploaded catalogue from
        # the dashboard at all — a judge's test file becomes the newest batch
        # permanently, and clearing it meant going into Postgres by hand.
        csv_path = self._make_csv([{"Manufacturer": "Parker Hannifin", "Part Number": "V-1"}])
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("throwaway.csv", f, "text/csv")}
                ).json()["batch_id"]

            self.assertEqual(
                self.client.get(f"/catalogue/batches/{batch_id}").status_code, 200
            )

            deleted = self.client.delete(f"/catalogue/batches/{batch_id}")
            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(deleted.json()["deleted_rows"], 1)

            self.assertEqual(
                self.client.get(f"/catalogue/batches/{batch_id}").status_code, 404
            )
            listed = self.client.get("/catalogue/batches").json()
            self.assertNotIn("throwaway.csv", [b["source_name"] for b in listed["batches"]])
        finally:
            csv_path.unlink(missing_ok=True)

    def test_deleting_an_unknown_batch_is_a_404(self) -> None:
        res = self.client.delete("/catalogue/batches/00000000-0000-0000-0000-000000000000")
        self.assertEqual(res.status_code, 404)

    def test_delete_will_not_cross_organizations(self) -> None:
        # Deleting is destructive, so it must obey the same namespacing as
        # every read: one workspace cannot remove another's catalogue.
        csv_path = self._make_csv([{"Manufacturer": "Parker Hannifin", "Part Number": "V-1"}])
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest?organization_id=owner",
                    files={"file": ("owned.csv", f, "text/csv")},
                ).json()["batch_id"]

            intruder = self.client.delete(
                f"/catalogue/batches/{batch_id}?organization_id=someone_else"
            )
            self.assertEqual(intruder.status_code, 404)

            still_there = self.client.get(
                f"/catalogue/batches/{batch_id}?organization_id=owner"
            )
            self.assertEqual(still_there.status_code, 200)
        finally:
            csv_path.unlink(missing_ok=True)

    def test_evidence_sources_name_the_same_manufacturer_as_the_record(self) -> None:
        # The inspector resolved a Diablo-branded belt to diablotools.com
        # while the evidence library listed freudtools.com for the same SKU:
        # source discovery during batch processing was called with only the
        # manufacturer and part number, so it fell back to the first domain
        # registered for "Freud Inc" instead of reading the brand.
        csv_path = self._make_csv([{
            "Manufacturer": "Freud Inc (2435)",
            "Part Number": "DCB518ASTS06G",
            "Description": 'DCB518ASTS06G Diablo 1/2"x18" - Sanding Belt 6pc',
        }])
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("evidence.csv", f, "text/csv")}
                ).json()["batch_id"]

            row = self.client.get(
                f"/catalogue/batches/{batch_id}/rows/2/unilog252"
            ).json()
            record = row.get("unilog252") or row
            self.assertIn("diablotools.com", record["MFR URL"])

            sources = self.client.get(f"/catalogue/batches/{batch_id}/sources").json()
            urls = [s["url"] for s in sources["sources"]]
            self.assertTrue(urls, "expected candidate sources")
            for url in urls:
                self.assertIn(
                    "diablotools.com", url,
                    f"evidence library names a different manufacturer than the record: {url}",
                )
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



    def test_search_finds_rows_beyond_the_first_page(self) -> None:
        # The catalogue search box promises "search SKU, description, or
        # manufacturer" across the batch. Filtering only the loaded page makes
        # it report a row that exists as absent — a silently wrong answer.
        rows = [{"Manufacturer": "Parker Hannifin", "Part Number": f"V-{i}"} for i in range(30)]
        rows.append({"Manufacturer": "Philips Lighting", "Part Number": "576512"})
        csv_path = self._make_csv(rows)
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("search.csv", f, "text/csv")}
                ).json()["batch_id"]

            # "576512" is the last row, well past a 5-row first page.
            page = self.client.get(
                f"/catalogue/batches/{batch_id}?limit=5&offset=0&search=576512"
            ).json()

            self.assertEqual(page["returned_rows"], 1)
            self.assertEqual(page["matched_rows"], 1)
            self.assertFalse(page["has_more"])
            # row_count stays the batch total so the UI can say "1 of 31".
            self.assertEqual(page["row_count"], 31)
            self.assertIn("576512", str(page["rows"][0]["raw_values"].values()))
        finally:
            csv_path.unlink(missing_ok=True)

    def test_search_is_case_insensitive_and_matches_manufacturer(self) -> None:
        rows = [{"Manufacturer": "Parker Hannifin", "Part Number": f"V-{i}"} for i in range(4)]
        rows.append({"Manufacturer": "Philips Lighting", "Part Number": "X-9"})
        csv_path = self._make_csv(rows)
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("srch2.csv", f, "text/csv")}
                ).json()["batch_id"]

            page = self.client.get(
                f"/catalogue/batches/{batch_id}?search=philips"
            ).json()
            self.assertEqual(page["matched_rows"], 1)

            # A term that matches nothing must report zero, not fall back to
            # returning the unfiltered page.
            empty = self.client.get(
                f"/catalogue/batches/{batch_id}?search=zzzznotpresent"
            ).json()
            self.assertEqual(empty["matched_rows"], 0)
            self.assertEqual(empty["returned_rows"], 0)
        finally:
            csv_path.unlink(missing_ok=True)

    def test_search_paginates_within_the_matched_set(self) -> None:
        # has_more must be computed against the matched total, not the batch
        # total, or the UI offers a "Next" that returns an empty page.
        rows = [{"Manufacturer": "Parker Hannifin", "Part Number": f"V-{i}"} for i in range(12)]
        rows += [{"Manufacturer": "Philips Lighting", "Part Number": f"P-{i}"} for i in range(7)]
        csv_path = self._make_csv(rows)
        try:
            with csv_path.open("rb") as f:
                batch_id = self.client.post(
                    "/catalogue/ingest", files={"file": ("srch3.csv", f, "text/csv")}
                ).json()["batch_id"]

            first = self.client.get(
                f"/catalogue/batches/{batch_id}?limit=5&offset=0&search=philips"
            ).json()
            self.assertEqual(first["matched_rows"], 7)
            self.assertEqual(first["returned_rows"], 5)
            self.assertTrue(first["has_more"])

            second = self.client.get(
                f"/catalogue/batches/{batch_id}?limit=5&offset=5&search=philips"
            ).json()
            self.assertEqual(second["returned_rows"], 2)
            self.assertFalse(second["has_more"])
        finally:
            csv_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
