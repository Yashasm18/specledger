import unittest

from backend.specledger.catalogue_ingestion import normalize_rows


class CatalogueIngestionTests(unittest.TestCase):
  def test_normalizes_headers_cells_and_placeholders(self) -> None:
    batch = normalize_rows("items.csv", [{"Mfg Part Num": "  A-1 ", "Part Desc": "Valve", "Brand": "--"}])

    assert batch.columns == ("mfg_part_num", "part_desc", "brand")
    assert batch.rows[0].row_number == 2
    assert batch.rows[0].values == {"mfg_part_num": "A-1", "part_desc": "Valve", "brand": None}
    assert len(batch.rows[0].source_fingerprint) == 64


  def test_rejects_empty_input(self) -> None:
    with self.assertRaisesRegex(ValueError, "no data rows"):
        normalize_rows("items.csv", [])
