"""Tests for deterministic fact extraction from datasheet text.

The patterns were originally tuned against label-value datasheets, where
every specification sits on its own line as ``Label: value``. Real
manufacturer PDFs are mostly prose and tables, and the optional separator
in the original patterns let an ordinary sentence match — a live upload of
a Leviton receptacle sheet produced ``material = "s and on installation
time."`` with confidence 0.85. These tests pin that down.
"""

import unittest

from backend.specledger.extraction import extract_facts


def _page(text: str, page: int = 1) -> dict:
    return {"page": page, "text": text}


def _named(facts, name: str) -> list:
    return [f for f in facts if f.name == name]


class ProseIsNotASpecificationTests(unittest.TestCase):
    """A specification is a labelled value, not any sentence mentioning one."""

    def test_prose_mentioning_materials_is_not_extracted(self) -> None:
        # Verbatim from leviton.com PK-A3158, the sentence that produced
        # `material = "s and on installation time."` in production.
        text = ("1™ Receptacle design saves on materials and on installation time.\n"
                "For example: you can easily replace the device.")
        assert _named(extract_facts([_page(text)]), "material") == []

    def test_prose_mentioning_construction_is_not_extracted(self) -> None:
        text = "Rugged construction means the unit withstands heavy commercial use."
        assert _named(extract_facts([_page(text)]), "material") == []

    def test_prose_mentioning_size_is_not_extracted(self) -> None:
        text = "Choose the size that best suits your installation requirements."
        assert _named(extract_facts([_page(text)]), "size") == []

    def test_no_facts_at_all_from_marketing_prose(self) -> None:
        text = ("Leviton products are built to the highest standards of quality and "
                "construction, in a size and pressure range suited to every job.")
        assert extract_facts([_page(text)]) == []


class LabelledValuesStillExtractTests(unittest.TestCase):
    """Regression guard: the label-value datasheets must keep working."""

    def test_material_with_colon_on_same_line(self) -> None:
        facts = _named(extract_facts([_page("Body Material: Bronze ASTM B584")]), "material")
        assert [f.value for f in facts] == ["Bronze ASTM B584"]

    def test_material_with_value_on_next_line(self) -> None:
        # The sample datasheets put the value on the line below the label.
        facts = _named(extract_facts([_page("Material:\nBronze ASTM B584")]), "material")
        assert [f.value for f in facts] == ["Bronze ASTM B584"]

    def test_pressure_rating_with_label(self) -> None:
        facts = _named(extract_facts([_page("Pressure Rating:\n600 WOG")]), "pressure_rating")
        assert [f.value for f in facts] == ["600 WOG"]

    def test_size_with_label(self) -> None:
        facts = _named(extract_facts([_page("Size:\n1/2 in")]), "size")
        assert [f.value for f in facts] == ["1/2 in"]


class ElectricalSpecificationTests(unittest.TestCase):
    """Real feeds are not all valves — an electrical sheet must yield facts."""

    def test_amperage_extracted(self) -> None:
        facts = _named(extract_facts([_page("Amperage Rating:\n15 A")]), "amperage")
        assert [f.value for f in facts] == ["15 A"]

    def test_voltage_extracted(self) -> None:
        facts = _named(extract_facts([_page("Voltage Rating:\n125 V")]), "voltage")
        assert [f.value for f in facts] == ["125 V"]

    def test_leviton_receptacle_sheet_yields_specifications(self) -> None:
        text = ("LEVITON - COMMERCIAL DUPLEX RECEPTACLE\n"
                "Catalog Number:\nR02D215P1RW\n"
                "Amperage Rating:\n15 A\n"
                "Voltage Rating:\n125 V\n")
        names = {f.name for f in extract_facts([_page(text)])}
        assert "amperage" in names
        assert "voltage" in names


class PartNumberExtractionTests(unittest.TestCase):
    """The part number is what links a datasheet back to a catalogue row."""

    def test_part_number_label(self) -> None:
        facts = _named(extract_facts([_page("Part Number:\n70-104-01")]), "part_number")
        assert [f.value for f in facts] == ["70-104-01"]

    def test_catalog_number_label(self) -> None:
        facts = _named(extract_facts([_page("Catalog Number:\nR02D215P1RW")]), "part_number")
        assert [f.value for f in facts] == ["R02D215P1RW"]

    def test_prose_mentioning_part_number_is_not_extracted(self) -> None:
        text = "Please quote the part number when contacting technical assistance."
        assert _named(extract_facts([_page(text)]), "part_number") == []


if __name__ == "__main__":
    unittest.main()
