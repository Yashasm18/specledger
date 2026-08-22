import tempfile
import unittest
from pathlib import Path

from backend.specledger.catalogue_ingestion import normalize_rows, read_catalogue


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


class RealWorldFileShapeTests(unittest.TestCase):
    """Files as they actually arrive, not as they ideally would.

    Every case here was found by uploading real spreadsheet exports rather
    than hand-written fixtures.
    """

    def _write(self, name: str, data: bytes) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=name, delete=False)
        tmp.write(data)
        tmp.close()
        return Path(tmp.name)

    def test_reads_a_cp1252_export_from_excel(self) -> None:
        # Excel on Windows writes cp1252 by default. Decoding as UTF-8 only
        # failed with a raw codec error naming a byte offset.
        body = (
            "Mfg_Part_Num,Part_Desc,Part_Manuf\n"
            "V-6,Vanne 1/2 pouce café — 600 PSI,Apollo Valves\n"
        ).encode("cp1252")
        path = self._write(".csv", body)
        try:
            batch = read_catalogue(path)
            self.assertEqual(batch.rows[0].values["part_desc"], "Vanne 1/2 pouce café — 600 PSI")
        finally:
            path.unlink(missing_ok=True)

    def test_skips_blank_rows_but_keeps_source_line_numbers(self) -> None:
        # Spreadsheets carry trailing blank rows; each would otherwise become
        # a product with no part number. Row numbers must still point at the
        # line they came from, because lineage is the point.
        body = (
            b"Mfg_Part_Num,Part_Desc,Part_Manuf\n"
            b"V-1,Ball Valve,Nibco\n"
            b",,\n"
            b"V-2,Gate Valve,Nibco\n"
            b"\n"
        )
        path = self._write(".csv", body)
        try:
            batch = read_catalogue(path)
            self.assertEqual(len(batch.rows), 2)
            self.assertEqual([r.row_number for r in batch.rows], [2, 4])
        finally:
            path.unlink(missing_ok=True)

    def test_a_file_of_only_blank_rows_is_rejected(self) -> None:
        path = self._write(".csv", b"Mfg_Part_Num,Part_Desc\n,,\n,,\n")
        try:
            with self.assertRaises(ValueError):
                read_catalogue(path)
        finally:
            path.unlink(missing_ok=True)

    def test_fields_beyond_the_header_do_not_become_a_column(self) -> None:
        # DictReader files overflow fields under a None key as a list. Treated
        # as a column that produced a phantom "none" column containing a
        # stringified Python list, which would reach the 252-column export.
        path = self._write(".csv", b"Mfg_Part_Num,Part_Desc,Part_Manuf\nV-1,Ball Valve,Nibco,EXTRA,MORE\n")
        try:
            batch = read_catalogue(path)
            self.assertEqual(list(batch.columns), ["mfg_part_num", "part_desc", "part_manuf"])
            self.assertNotIn("none", batch.columns)
            self.assertEqual(batch.rows[0].values["part_manuf"], "Nibco")
        finally:
            path.unlink(missing_ok=True)

    def test_rows_shorter_than_the_header_fill_with_none(self) -> None:
        path = self._write(".csv", b"Mfg_Part_Num,Part_Desc,Part_Manuf\nV-2,only two\n")
        try:
            batch = read_catalogue(path)
            self.assertIsNone(batch.rows[0].values["part_manuf"])
        finally:
            path.unlink(missing_ok=True)

    def test_undecodable_bytes_give_an_actionable_message(self) -> None:
        # latin-1 accepts any byte sequence, so this is hard to trigger — but
        # if it ever does, the message must tell the uploader what to do.
        from backend.specledger.catalogue_ingestion import _decode_text
        from unittest.mock import patch
        path = self._write(".csv", b"Mfg_Part_Num\nV-1\n")
        try:
            with patch("pathlib.Path.read_bytes", return_value=b"\xff"), \
                 patch("backend.specledger.catalogue_ingestion._TEXT_ENCODINGS", ("utf-8",)):
                with self.assertRaises(ValueError) as ctx:
                    _decode_text(path)
            self.assertIn("UTF-8", str(ctx.exception))
        finally:
            path.unlink(missing_ok=True)


def test_semicolon_delimited_csv_is_parsed_as_columns(tmp_path):
    """Excel writes ";"-separated CSV in many locales.

    Assuming a comma did not fail loudly: the file ingested, reported its
    rows, and put every value into one column named after the joined header,
    so the delivered record was garbage while the upload looked successful.
    """
    path = tmp_path / "euro.csv"
    path.write_text(
        "Part Number;Description;Manufacturer\n"
        "GR-1180;GR-1180 Grinding Wheel 7 in Type 27;Norton Abrasives\n",
        encoding="utf-8",
    )
    batch = read_catalogue(path)
    assert batch.row_count == 1
    values = batch.rows[0].values
    assert set(values) == {"part_number", "description", "manufacturer"}
    assert values["part_number"] == "GR-1180"
    assert values["manufacturer"] == "Norton Abrasives"


def test_pipe_delimited_csv_is_parsed_as_columns(tmp_path):
    path = tmp_path / "piped.csv"
    path.write_text(
        "Part Number|Description|Manufacturer\n"
        "V-1|V-1 Bronze Ball Valve|Apollo Valves\n",
        encoding="utf-8",
    )
    batch = read_catalogue(path)
    assert set(batch.rows[0].values) == {"part_number", "description", "manufacturer"}


def test_a_comma_file_is_unaffected(tmp_path):
    path = tmp_path / "plain.csv"
    path.write_text(
        "Part Number,Description,Manufacturer\n"
        "V-1,V-1 Bronze Ball Valve,Apollo Valves\n",
        encoding="utf-8",
    )
    batch = read_catalogue(path)
    assert batch.rows[0].values["part_number"] == "V-1"


def test_a_single_column_file_still_works(tmp_path):
    # Nothing to sniff: one column, no delimiter present anywhere.
    path = tmp_path / "one.csv"
    path.write_text("Part Number\nV-1\n", encoding="utf-8")
    batch = read_catalogue(path)
    assert batch.rows[0].values["part_number"] == "V-1"


def test_commas_inside_quoted_values_do_not_pick_the_wrong_delimiter(tmp_path):
    # A semicolon file whose descriptions contain commas must still split on ";".
    path = tmp_path / "tricky.csv"
    path.write_text(
        "Part Number;Description;Manufacturer\n"
        'V-2;"V-2 Valve, Bronze, 600 WOG";Apollo Valves\n',
        encoding="utf-8",
    )
    batch = read_catalogue(path)
    values = batch.rows[0].values
    assert values["part_number"] == "V-2"
    assert values["description"] == "V-2 Valve, Bronze, 600 WOG"
