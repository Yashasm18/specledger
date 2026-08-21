"""Unit tests for Unilog input ingestion, web enrichment, and 252-column export."""

from pathlib import Path
import csv
import pytest

from backend.specledger.catalogue_ingestion import read_catalogue, clean_manufacturer_name
from backend.specledger.source_discovery import is_blocked_source, discover_sources_simulated
from backend.specledger.web_enricher import enrich_product_web, WebEnrichmentResult
from backend.specledger.unilog_exporter import export_unilog_csv, UNILOG_252_HEADERS
from backend.specledger.enrichment import enrich_batch


def test_clean_manufacturer_name():
    assert clean_manufacturer_name("Freud Inc (2435)") == "Freud Inc"
    assert clean_manufacturer_name("Jam Industrial Supply LLC (JAMIN)") == "Jam Industrial Supply LLC"
    assert clean_manufacturer_name("Milwaukee Accessory (4031)") == "Milwaukee Accessory"
    assert clean_manufacturer_name("Simple Mfr") == "Simple Mfr"
    assert clean_manufacturer_name(None) is None


def _get_input_path() -> Path | None:
    repo_root = Path(__file__).resolve().parent.parent
    data_path = repo_root / "data" / "challenge" / "Unihack_ Sample Dataset - Input.csv"
    if data_path.exists():
        return data_path
    local_path = repo_root / "Unihack_ Sample Dataset - Input.csv"
    if local_path.exists():
        return local_path
    downloads_path = Path("/Users/yashas/Downloads/Unihack_ Sample Dataset - Input.csv")
    if downloads_path.exists():
        return downloads_path
    return None


def test_unilog_input_ingestion():
    input_path = _get_input_path()
    if input_path is None:
        pytest.skip("Unilog input file not present")

    batch = read_catalogue(input_path)
    assert batch.row_count == 1000
    assert "mfg_part_num" in batch.columns
    assert "part_desc" in batch.columns
    assert "part_manuf" in batch.columns

    # Test first row
    first_row = batch.rows[0]
    assert first_row.values["mfg_part_num"] == "DCB518ASTS06G"
    assert "Freud Inc" in (first_row.values["part_manuf"] or "")


def test_marketplace_blocking():
    assert is_blocked_source("https://www.amazon.com/dp/B08N5WRWNW") is True
    assert is_blocked_source("https://www.ebay.com/itm/123456789") is True
    assert is_blocked_source("https://www.freudtools.com/products/DCB518ASTS06G") is False
    assert is_blocked_source("https://www.3m.com/3M/en_US/p/d/v100075678/") is False


def test_domain_agnostic_web_enricher():
    # Test abrasive product
    res1 = enrich_product_web(
        part_number="DCB518ASTS06G",
        raw_manufacturer="Freud Inc (2435)",
        raw_description="DCB518ASTS06G Diablo 1/2x18 - Sanding Belt 6pc",
    )
    assert res1.manufacturer_clean == "Freud Inc"
    assert "freudtools.com" in (res1.mfr_url or "")
    assert res1.dept == "Abrasives & Cutting Tools"
    # Features are derived only from genuinely extracted attributes (no
    # generic filler text), so the count reflects what's actually in the
    # raw description — real, not padded.
    assert res1.features == [f"{a.label}: {a.value}" for a in res1.attributes[2:]]
    assert res1.marketing_desc == ""
    assert "Industrial grade component" not in res1.long_desc1

    # Test appliance product
    res2 = enrich_product_web(
        part_number="PDSH4816AF",
        raw_manufacturer="Appliance Dealers Cooperative (APPDE)",
        raw_description="PDSH4816AF Frigidaire Dishwasher SS",
    )
    assert res2.dept == "Appliances"
    assert "frigidaire.com" in (res2.mfr_url or "")


def test_unilog_252_exporter():
    assert len(UNILOG_252_HEADERS) == 252

    input_path = _get_input_path()
    if input_path is None:
        pytest.skip("Unilog input file not present")

    batch = read_catalogue(input_path)
    # Take first 5 rows for test speed
    mini_batch = type(batch)(batch.source_name, batch.columns, batch.rows[:5])
    
    csv_out = export_unilog_csv(mini_batch)
    reader = list(csv.reader(csv_out.splitlines()))
    assert len(reader) == 6  # Header + 5 data rows
    assert len(reader[0]) == 252
    assert reader[0][0] == "MFR URL"
    assert reader[0][6] == "PART_NUMBER"
    assert reader[0][251] == "Actual Image (Yes/No)"
