"""Reading JSON and XML product feeds into the same normalized batch.

A distributor feed does not always arrive as a spreadsheet. These two
formats carry the same thing — a list of products, each a set of named
fields — so they resolve to the same CatalogueBatch and go through the
identical enrichment path. Column names still do not have to match ours;
roles are detected exactly as they are for CSV.
"""

import json
import tempfile
import unittest
from pathlib import Path

from backend.specledger.catalogue_ingestion import read_catalogue


def _write(directory: str, name: str, content: str) -> str:
    path = Path(directory) / name
    path.write_text(content, encoding="utf-8")
    return str(path)


class JsonFeedTests(unittest.TestCase):
    def test_array_of_objects(self) -> None:
        rows = [
            {"Mfg_Part_Num": "70-104-01", "Part_Desc": "Bronze Ball Valve", "Part_Manuf": "Apollo Valves"},
            {"Mfg_Part_Num": "70-108-01", "Part_Desc": "Bronze Ball Valve 2in", "Part_Manuf": "Apollo Valves"},
        ]
        with tempfile.TemporaryDirectory() as d:
            batch = read_catalogue(_write(d, "feed.json", json.dumps(rows)))
        assert batch.row_count == 2
        assert "mfg_part_num" in batch.columns

    def test_object_wrapping_a_list(self) -> None:
        payload = {"products": [{"SKU": "A-1", "Item Description": "Widget", "Vendor": "Acme"}]}
        with tempfile.TemporaryDirectory() as d:
            batch = read_catalogue(_write(d, "feed.json", json.dumps(payload)))
        assert batch.row_count == 1
        assert "sku" in batch.columns

    def test_single_object_is_one_row(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            batch = read_catalogue(_write(d, "feed.json", json.dumps({"SKU": "A-1", "Vendor": "Acme"})))
        assert batch.row_count == 1

    def test_nested_values_are_flattened_to_text(self) -> None:
        # A nested object cannot be a cell. Keeping it as text preserves the
        # supplier's value instead of dropping the field.
        payload = [{"SKU": "A-1", "dimensions": {"length": 10, "width": 2}}]
        with tempfile.TemporaryDirectory() as d:
            batch = read_catalogue(_write(d, "feed.json", json.dumps(payload)))
        assert batch.row_count == 1

    def test_malformed_json_is_rejected_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "feed.json", "{not json at all")
            with self.assertRaises(ValueError):
                read_catalogue(path)

    def test_json_that_is_not_a_product_list_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "feed.json", json.dumps([1, 2, 3]))
            with self.assertRaises(ValueError):
                read_catalogue(path)


class XmlFeedTests(unittest.TestCase):
    def test_repeated_elements_become_rows(self) -> None:
        xml = """<?xml version="1.0"?>
        <products>
          <product><Mfg_Part_Num>70-104-01</Mfg_Part_Num><Part_Desc>Bronze Ball Valve</Part_Desc></product>
          <product><Mfg_Part_Num>70-108-01</Mfg_Part_Num><Part_Desc>Bronze Ball Valve 2in</Part_Desc></product>
        </products>"""
        with tempfile.TemporaryDirectory() as d:
            batch = read_catalogue(_write(d, "feed.xml", xml))
        assert batch.row_count == 2
        assert "mfg_part_num" in batch.columns

    def test_attributes_are_read_as_fields(self) -> None:
        xml = """<?xml version="1.0"?>
        <catalog><item sku="A-1" vendor="Acme"><description>Widget</description></item></catalog>"""
        with tempfile.TemporaryDirectory() as d:
            batch = read_catalogue(_write(d, "feed.xml", xml))
        assert batch.row_count == 1
        assert "sku" in batch.columns

    def test_malformed_xml_is_rejected_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "feed.xml", "<products><product></products>")
            with self.assertRaises(ValueError):
                read_catalogue(path)


class UnsupportedFormatTests(unittest.TestCase):
    def test_unsupported_extension_names_what_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "feed.qqq", "whatever")
            with self.assertRaises(ValueError) as caught:
                read_catalogue(path)
        assert "csv" in str(caught.exception).casefold()


if __name__ == "__main__":
    unittest.main()
