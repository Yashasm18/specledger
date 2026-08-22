"""Unit tests for Unilog input ingestion, web enrichment, and 252-column export."""

from pathlib import Path
import csv
import pytest

from backend.specledger.catalogue_ingestion import read_catalogue, clean_manufacturer_name
from backend.specledger.source_discovery import is_blocked_source, discover_sources_simulated
from backend.specledger.web_enricher import enrich_product_web, WebEnrichmentResult, classify_category
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
    # "Freud Inc" lists freudtools.com and diablotools.com. This row is a
    # Diablo-branded belt, and the brand named in the description decides:
    # the product page lives on the brand's own site, not the parent's.
    assert "diablotools.com" in (res1.mfr_url or "")
    assert res1.dept == "Abrasives & Cutting Tools"
    # Features are derived only from genuinely extracted attributes (no
    # generic filler text), so the count reflects what's actually in the
    # raw description — real, not padded. Every attribute is a spec now that
    # the identity pair no longer occupies the first two slots, so nothing
    # is skipped.
    # Bullets come only from attributes that carry a value; the rest are the
    # category's declared schema, delivered empty rather than guessed. This
    # description states no extractable spec, so there is nothing to bullet.
    assert res1.features == []
    assert [a.label for a in res1.attributes if a.value] == []
    # The schema is still declared, and holds no identity fields.
    labels = [a.label for a in res1.attributes]
    assert labels, "expected the abrasives schema to be declared"
    assert "Manufacturer" not in labels
    assert "Part Number" not in labels
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


def test_classify_category_is_real_not_uncategorized():
    # The raw 6-column input never has a category column, so this is the
    # only real classification available for the catalogue list view.
    assert classify_category("1/2 in Ball Valve 600 PSI", "Apollo Valves") == \
        "Plumbing & Industrial Piping > Industrial Valves & Fittings > Ball Valves"
    assert classify_category("20A Industrial Rocker Switch", "Leviton") == \
        "Electrical Supplies > Wiring Devices & Distribution > Industrial Switches & Receptacles"
    # Unknown/unmatched descriptions get a real (if generic) bucket, not a crash.
    assert classify_category("", "") == "Industrial Supplies > Maintenance"


def test_exported_classpath_uses_the_delivery_format_separator():
    """Unilog's own Expected Output rows write Classpath with a bare ">".

    Their gold row reads
    "Appliances & Consumer Electronics>Kitchen Appliances>Built-In Dishwashers".
    We render " > " internally because it is readable in the dashboard, but
    the delivered CSV has to match their format exactly — a separator that
    differs by two spaces fails any string comparison they run.
    """
    input_path = _get_input_path()
    if input_path is None:
        pytest.skip("Unilog input file not present")

    batch = read_catalogue(input_path)
    mini_batch = type(batch)(batch.source_name, batch.columns, batch.rows[:5])
    reader = list(csv.reader(export_unilog_csv(mini_batch).splitlines()))
    idx = reader[0].index("Classpath")

    classpaths = [r[idx] for r in reader[1:] if r[idx]]
    assert classpaths, "no row produced a classpath to check"
    for path in classpaths:
        assert " > " not in path, f"delivery CSV must not pad the separator: {path!r}"
        assert ">" in path, f"expected a hierarchical classpath, got {path!r}"
        # And the segments must survive intact, not get their spaces stripped.
        assert not any(s.startswith(" ") or s.endswith(" ") for s in path.split(">"))


def test_export_reads_roles_not_hardcoded_column_names():
    """The 252 export must work on a file that isn't the sample dataset.

    The challenge brief is explicit that the solution has to handle "different
    data/field combinations rather than being designed only for the sample
    dataset". The exporter looked up "mfg_part_num" / "part_desc" /
    "part_manuf" by name, so a catalogue using SKU / Item Description / Vendor
    exported every row as UNKNOWN-PN with "Industrial Manufacturer" as the
    maker — the input was ingested fine and then thrown away at delivery.

    detect_role() already classifies columns by keyword; this is the export
    path using it.
    """
    from backend.specledger.catalogue_ingestion import CatalogueBatch, SourceRow

    columns = ("sku", "item_description", "vendor", "brand_code")
    rows = (
        SourceRow(
            row_number=1,
            source_name="medical.csv",
            source_fingerprint="fp-1",
            values={
                "sku": "MED-4471",
                "item_description": "MED-4471 Nitrile Exam Glove Powder-Free Large 100/Box",
                "vendor": "Halyard Health Inc (HALYD)",
                "brand_code": "-- Unbranded --",
            },
        ),
    )
    batch = CatalogueBatch("medical.csv", columns, rows)

    reader = list(csv.reader(export_unilog_csv(batch).splitlines()))
    hdr, row = reader[0], reader[1]
    get = lambda name: row[hdr.index(name)]

    assert get("Mfg_Part_Num") == "MED-4471"
    assert get("PART_NUMBER") == "MED-4471"
    assert "UNKNOWN-PN" not in row
    assert get("MANUFACTURER_NAME") == "Halyard Health Inc"
    assert "Nitrile Exam Glove" in get("Part_Desc")
    assert "Nitrile Exam Glove" in get("SHORT_DESC")


def test_export_still_prefers_the_sample_dataset_column_names():
    """Role detection must not change behaviour on the official input."""
    input_path = _get_input_path()
    if input_path is None:
        pytest.skip("Unilog input file not present")

    batch = read_catalogue(input_path)
    mini = type(batch)(batch.source_name, batch.columns, batch.rows[:3])
    reader = list(csv.reader(export_unilog_csv(mini).splitlines()))
    hdr = reader[0]
    for row in reader[1:]:
        assert row[hdr.index("Mfg_Part_Num")]
        assert row[hdr.index("Mfg_Part_Num")] != "UNKNOWN-PN"
        assert row[hdr.index("MANUFACTURER_NAME")] != "Industrial Manufacturer"


def test_unresolved_category_is_left_blank_not_asserted():
    """An unmatched product must not be labelled a maintenance product.

    Where no keyword matched, the taxonomy fell back to a generic bucket and
    the export delivered it as a resolved answer: Classpath "Industrial
    Supplies>Maintenance", Fine "Maintenance Products", and (since Product
    Name began deriving from Fine) "Maintenance Product". On the official
    1,000-row input that was 249 rows, among them a digital tire pressure
    gauge, fence gate balusters and 4x4 post trim.

    The pipeline already treats that bucket as unresolved — needs_llm() keys
    on it, and the LLM prompt uses it as the model's "don't guess" answer. It
    is only the delivered file that presented it as fact.
    """
    from backend.specledger.catalogue_ingestion import CatalogueBatch, SourceRow

    rows = (
        SourceRow(
            row_number=1, source_name="x.csv", source_fingerprint="fp-1",
            values={
                "mfg_part_num": "RDI-4X4",
                "part_desc": "4x4 Wh Heritage Post Trim RDI",
                "part_manuf": "RDI",
            },
        ),
        SourceRow(
            row_number=2, source_name="x.csv", source_fingerprint="fp-2",
            values={
                "mfg_part_num": "70-100-01",
                "part_desc": "1/2 in Bronze Ball Valve 600 PSI",
                "part_manuf": "Apollo Valves",
            },
        ),
    )
    reader = list(csv.reader(export_unilog_csv(
        CatalogueBatch("x.csv", ("mfg_part_num", "part_desc", "part_manuf"), rows)
    ).splitlines()))
    hdr = reader[0]
    unresolved, resolved = reader[1], reader[2]

    for column in ("Dept", "Class", "Fine", "Classpath", "Product Name"):
        assert unresolved[hdr.index(column)] == "", (
            f"{column} asserted a category for an unmatched product: "
            f"{unresolved[hdr.index(column)]!r}"
        )
    assert "Maintenance" not in ",".join(unresolved)

    # A row the rules do place must be unaffected.
    assert resolved[hdr.index("Fine")] == "Ball Valves"
    assert resolved[hdr.index("Product Name")] == "Ball Valve"
    assert ">" in resolved[hdr.index("Classpath")]
