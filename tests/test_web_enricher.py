"""Tests for taxonomy classification signal priority."""

import unittest

from backend.specledger.web_enricher import (
    classify_category, enrich_product_web, product_name_from_fine,
)


class TaxonomySignalPriorityTests(unittest.TestCase):
    """Description outranks manufacturer name.

    Both are useful, but they are not equal: the description says what a
    product *is*, while the manufacturer name only suggests what they tend to
    make. Matching them together let the weaker signal win — testing a real
    14-product Diablo catalogue, saw blades, hole saws, auger bits and
    chisels all classified as Coated Abrasives on the brand name alone.
    """

    def test_description_beats_a_conflicting_manufacturer_hint(self) -> None:
        # Mirka is an abrasives specialist, but this row is plainly a valve.
        path = classify_category("2 in Brass Ball Valve 600 PSI", "Mirka Abrasives Inc")
        self.assertIn("Valves", path)
        self.assertNotIn("Abrasives", path)

    def test_manufacturer_hint_still_applies_when_the_description_says_nothing(self) -> None:
        # The case the hint was added for: a description that is a bare code.
        path = classify_category("49-94-0803", "Mirka Abrasives Inc")
        self.assertIn("Abrasives", path)

    def test_a_multi_category_manufacturer_does_not_force_one_bucket(self) -> None:
        # Freud/Diablo make saw blades, hole saws and drill bits as well as
        # abrasives, so their name must not decide the category by itself.
        hole_saw = classify_category("DHS3250 Bi-Metal Hole Saws", "Freud Inc")
        self.assertNotIn("Abrasives", hole_saw)

    def test_a_real_freud_abrasive_still_classifies_from_its_description(self) -> None:
        path = classify_category('DCB518ASTS06G Diablo 1/2"x18" - Sanding Belt 6pc', "Freud Inc")
        self.assertIn("Abrasives", path)


class DescriptionAssemblyTests(unittest.TestCase):
    """Descriptions must not repeat the part number.

    Supplier Part_Desc values in this dataset almost always start with the
    part number ("PDSH4816AF Dishwasher SS - Display Only"). Prepending it
    again produced "... PDSH4816AF PDSH4816AF Dishwasher SS - Display Only",
    which also burns characters against the 120-char MOBILE_DESC cap.
    """

    def test_mobile_desc_does_not_repeat_a_leading_part_number(self) -> None:
        res = enrich_product_web(
            "PDSH4816AF", "Appliance Dealers Cooperative (APPDE)",
            "PDSH4816AF Dishwasher SS - Display Only",
        )
        self.assertEqual(res.mobile_desc.count("PDSH4816AF"), 1, res.mobile_desc)

    def test_long_desc_does_not_repeat_a_leading_part_number(self) -> None:
        res = enrich_product_web(
            "WDTS7024RZ", "Appliance Dealers Cooperative (APPDE)",
            "WDTS7024RZ Dishwasher SS - Display Only",
        )
        self.assertEqual(res.long_desc1.count("WDTS7024RZ"), 1, res.long_desc1)

    def test_part_number_is_still_present_when_the_description_omits_it(self) -> None:
        # The prepend exists for a reason — descriptions that don't name the
        # part must still carry it.
        res = enrich_product_web(
            "V-100", "Parker Hannifin", "Brass Ball Valve 600 PSI",
        )
        self.assertIn("V-100", res.mobile_desc)
        self.assertIn("V-100", res.long_desc1)

    def test_matching_is_case_insensitive(self) -> None:
        res = enrich_product_web(
            "abc-123", "Parker Hannifin", "ABC-123 Brass Ball Valve",
        )
        self.assertEqual(res.mobile_desc.lower().count("abc-123"), 1, res.mobile_desc)


class ProductNameTests(unittest.TestCase):
    """Product Name is the product noun, not an identifier restatement.

    Unilog's gold rows put "Dishwasher" here. We put
    "Appliance Dealers Cooperative PDSH4816AF" — the manufacturer and the
    part number, both of which already have their own columns, and neither
    of which says what the thing is.
    """

    def test_singularises_a_simple_plural_category(self) -> None:
        self.assertEqual(product_name_from_fine("Dishwashers"), "Dishwasher")
        self.assertEqual(product_name_from_fine("Ball Valves"), "Ball Valve")

    def test_handles_es_and_ies_plurals(self) -> None:
        self.assertEqual(product_name_from_fine("Industrial Switches"), "Industrial Switch")
        self.assertEqual(product_name_from_fine("Supplies"), "Supply")

    def test_takes_the_first_alternative_of_a_compound_category(self) -> None:
        # "Sanding Belts & Discs" names two things; the product is one of them.
        self.assertEqual(product_name_from_fine("Sanding Belts & Discs"), "Sanding Belt")

    def test_leaves_a_mass_noun_alone(self) -> None:
        self.assertEqual(product_name_from_fine("Commercial Lighting"), "Commercial Lighting")

    def test_empty_category_yields_empty_rather_than_a_guess(self) -> None:
        self.assertEqual(product_name_from_fine(""), "")
        self.assertEqual(product_name_from_fine(None), "")
