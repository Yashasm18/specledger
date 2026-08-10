"""Tests for reference-data store and UOM normalization."""

import unittest
from pathlib import Path
import tempfile
import json
import csv

from backend.specledger.reference_data import ReferenceStore, ReferenceEntry, CanonicalMatch
from backend.specledger.uom import normalize_uom, normalize_material


class ManufacturerMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ReferenceStore()

    def test_exact_canonical_match(self) -> None:
        result = self.store.match_manufacturer("Parker Hannifin")
        assert result.canonical == "Parker Hannifin"
        assert result.confidence == 1.0
        assert result.match_type == "exact"

    def test_alias_match(self) -> None:
        result = self.store.match_manufacturer("Parker Hannifin Corp")
        assert result.canonical == "Parker Hannifin"
        assert result.confidence == 0.95
        assert result.match_type == "alias"

    def test_case_insensitive_match(self) -> None:
        result = self.store.match_manufacturer("PARKER HANNIFIN")
        assert result.canonical == "Parker Hannifin"
        assert result.confidence == 1.0

    def test_whitespace_tolerant(self) -> None:
        result = self.store.match_manufacturer("  Parker  Hannifin  ")
        assert result.canonical == "Parker Hannifin"
        assert result.confidence == 1.0

    def test_normalized_containment_match(self) -> None:
        result = self.store.match_manufacturer("Parker Hannifin Industrial Division")
        assert result.canonical == "Parker Hannifin"
        assert result.confidence == 0.80
        assert result.match_type == "normalized"

    def test_no_match_returns_none_canonical(self) -> None:
        result = self.store.match_manufacturer("Unknown Manufacturer XYZ")
        assert result.canonical == ""
        assert result.confidence == 0.0
        assert result.match_type == "none"

    def test_empty_input(self) -> None:
        result = self.store.match_manufacturer("")
        assert result.confidence == 0.0
        assert result.match_type == "none"

    def test_multiple_manufacturers_in_seed(self) -> None:
        assert self.store.manufacturer_count >= 20

    def test_emerson_alias(self) -> None:
        result = self.store.match_manufacturer("Emerson Electric Co.")
        assert result.canonical == "Emerson Electric"
        assert result.match_type == "alias"


class BrandMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ReferenceStore()

    def test_exact_brand_match(self) -> None:
        result = self.store.match_brand("Fisher")
        assert result.canonical == "Fisher"
        assert result.confidence == 1.0

    def test_brand_alias(self) -> None:
        result = self.store.match_brand("Fisher Controls")
        assert result.canonical == "Fisher"
        assert result.match_type == "alias"

    def test_no_brand_match(self) -> None:
        result = self.store.match_brand("UnknownBrand999")
        assert result.confidence == 0.0


class CategoryMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ReferenceStore()

    def test_exact_category(self) -> None:
        result = self.store.match_category("Ball Valve")
        assert result.canonical == "Ball Valve"
        assert result.confidence == 1.0

    def test_category_alias(self) -> None:
        result = self.store.match_category("non-return valve")
        assert result.canonical == "Check Valve"
        assert result.match_type == "alias"

    def test_category_case_insensitive(self) -> None:
        result = self.store.match_category("GATE VALVE")
        assert result.canonical == "Gate Valve"

    def test_category_count(self) -> None:
        assert self.store.category_count >= 18


class PrivateFileLoadingTests(unittest.TestCase):
    def test_load_json_reference_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data = {
                "type": "manufacturers",
                "entries": [
                    {"canonical": "TestMfg Inc", "aliases": ["TestMfg", "Test Manufacturing"]}
                ]
            }
            json_path = Path(tmpdir) / "manufacturers_custom.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")

            store = ReferenceStore(reference_dir=tmpdir)
            result = store.match_manufacturer("TestMfg")
            assert result.canonical == "TestMfg Inc"
            assert result.confidence == 0.95
            assert "file:" in result.entry_source

    def test_load_csv_reference_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "manufacturers_extra.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["canonical", "aliases"])
                writer.writeheader()
                writer.writerow({"canonical": "CSV Mfg Corp", "aliases": "CSVMfg|CSV Manufacturer"})

            store = ReferenceStore(reference_dir=tmpdir)
            result = store.match_manufacturer("CSVMfg")
            assert result.canonical == "CSV Mfg Corp"
            assert result.match_type == "alias"

    def test_seed_data_still_loaded_with_private_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ReferenceStore(reference_dir=tmpdir)
            # Seed data should still be present
            result = store.match_manufacturer("Parker Hannifin")
            assert result.canonical == "Parker Hannifin"


class UOMNormalizationTests(unittest.TestCase):
    def test_inches_variants(self) -> None:
        for raw in ["in", "inch", "inches", "IN", "INCH", "in."]:
            result = normalize_uom(raw)
            assert result.canonical == "in", f"Failed for {raw!r}: got {result.canonical!r}"
            assert result.dimension == "length"

    def test_psi(self) -> None:
        result = normalize_uom("PSI")
        assert result.canonical == "psi"
        assert result.dimension == "pressure"

    def test_bar(self) -> None:
        result = normalize_uom("bar")
        assert result.canonical == "bar"
        assert result.dimension == "pressure"

    def test_wog(self) -> None:
        result = normalize_uom("WOG")
        assert result.canonical == "WOG"
        assert result.dimension == "pressure"

    def test_celsius(self) -> None:
        result = normalize_uom("degrees celsius")
        assert result.canonical == "°C"
        assert result.dimension == "temperature"

    def test_fahrenheit(self) -> None:
        result = normalize_uom("°F")
        assert result.canonical == "°F"
        assert result.dimension == "temperature"

    def test_npt_thread(self) -> None:
        result = normalize_uom("NPT")
        assert result.canonical == "NPT"
        assert result.dimension == "angle"

    def test_gpm_flow(self) -> None:
        result = normalize_uom("GPM")
        assert result.canonical == "GPM"
        assert result.dimension == "volume"

    def test_unrecognized_uom(self) -> None:
        result = normalize_uom("zorbles")
        assert result.confidence == 0.0
        assert result.canonical == "zorbles"  # preserved as-is

    def test_empty_uom(self) -> None:
        result = normalize_uom("")
        assert result.confidence == 0.0
        assert result.dimension == "none"

    def test_millimeters(self) -> None:
        result = normalize_uom("millimeters")
        assert result.canonical == "mm"
        assert result.dimension == "length"

    def test_nominal_pipe_size(self) -> None:
        result = normalize_uom("NPS")
        assert result.canonical == "NPS"


class MaterialNormalizationTests(unittest.TestCase):
    def test_stainless_steel(self) -> None:
        result = normalize_material("Stainless Steel")
        assert result.canonical == "Stainless Steel"
        assert result.confidence == 1.0

    def test_ss316(self) -> None:
        result = normalize_material("316SS")
        assert result.canonical == "Stainless Steel 316"

    def test_brass(self) -> None:
        result = normalize_material("brass")
        assert result.canonical == "Brass"
        assert result.confidence == 1.0

    def test_teflon_alias(self) -> None:
        result = normalize_material("Teflon")
        assert result.canonical == "PTFE"

    def test_aluminium_spelling(self) -> None:
        result = normalize_material("aluminium")
        assert result.canonical == "Aluminum"

    def test_unrecognized_material(self) -> None:
        result = normalize_material("Unobtanium")
        assert result.confidence == 0.0
        assert result.canonical == "Unobtanium"  # preserved

    def test_empty_material(self) -> None:
        result = normalize_material("")
        assert result.confidence == 0.0

    def test_cast_iron(self) -> None:
        result = normalize_material("Cast Iron")
        assert result.canonical == "Cast Iron"


if __name__ == "__main__":
    unittest.main()
