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


class AttributeTripletTests(unittest.TestCase):
    """Attribute slots carry specifications, not identifiers.

    Unilog's two gold rows use 15 attribute slots each and neither contains
    a "Manufacturer" or "Part Number" entry — they hold Series, Voltage
    Rating, Sound Level, Material and so on. We seeded every row's slots 1
    and 2 with the manufacturer and part number, which already have
    dedicated columns (MANUFACTURER_NAME, MANUFACTURER_PART_NUMBER), and
    whose value was the distributor rather than the manufacturer anyway.
    """

    def test_identity_fields_are_not_emitted_as_specifications(self) -> None:
        res = enrich_product_web(
            "PDSH4816AF", "Appliance Dealers Cooperative (APPDE)",
            "PDSH4816AF Dishwasher 120V 15A",
        )
        labels = [a.label for a in res.attributes]
        self.assertNotIn("Manufacturer", labels)
        self.assertNotIn("Part Number", labels)

    def test_real_specs_take_the_first_slots(self) -> None:
        res = enrich_product_web(
            "PDSH4816AF", "Appliance Dealers Cooperative (APPDE)",
            "PDSH4816AF Dishwasher 120V 15A",
        )
        self.assertTrue(res.attributes, "expected extracted specifications")
        # Labels and UOMs match Unilog's own vocabulary exactly.
        self.assertEqual(res.attributes[0].label, "Voltage Rating")
        self.assertEqual(res.attributes[0].value, "120")
        self.assertEqual(res.attributes[0].uom, "V")

    def test_feature_bullets_still_cover_every_extracted_spec(self) -> None:
        # Bullets used to skip the first two entries because they were the
        # identity pair. With those gone, nothing may be skipped.
        res = enrich_product_web(
            "PDSH4816AF", "Appliance Dealers Cooperative (APPDE)",
            "PDSH4816AF Dishwasher 120V 15A",
        )
        self.assertEqual(len(res.features), len(res.attributes))
        self.assertIn("Voltage Rating: 120 V", res.features)

    def test_a_row_with_no_extractable_spec_reports_none(self) -> None:
        res = enrich_product_web("X-1", "Parker Hannifin", "X-1 Widget")
        self.assertEqual(res.attributes, [])
        self.assertEqual(res.features, [])


class ManufacturerUrlHonestyTests(unittest.TestCase):
    """MFR URL must name a real manufacturer or nothing at all.

    Two defects on the official 1,000-row dataset:

    * 272 rows were given "https://www.manufacturer.com/product/<sku>" — a
      placeholder domain that is not anybody's site, emitted as if it were
      the manufacturer's product page.
    * 84 rows resolved through "Appliance Dealers Cooperative", a buying
      co-operative mapped to three unrelated competitors
      (frigidaire.com, whirlpool.com, geappliances.com). The code took the
      first, so a Whirlpool dishwasher was published with a Frigidaire URL.

    A guessed URL is the same failure as an invented specification. When the
    manufacturer cannot be determined from the input, the honest output is
    no URL.
    """

    def test_unknown_manufacturer_yields_no_url_not_a_placeholder(self) -> None:
        res = enrich_product_web(
            "D519127", "V & V Appliance Parts Inc (VVAPP)", "D519127 Dryer Timer",
        )
        self.assertFalse(res.mfr_url, f"expected no URL, got {res.mfr_url!r}")
        self.assertNotIn("manufacturer.com", res.mfr_url or "")

    def test_distributor_with_unrelated_brands_and_no_signal_yields_no_url(self) -> None:
        # Appliance Dealers Cooperative fronts Frigidaire, Whirlpool and GE.
        # This description names none of them, so the manufacturer genuinely
        # cannot be determined and must not be guessed.
        res = enrich_product_web(
            "WDTS7024RZ", "Appliance Dealers Cooperative (APPDE)",
            "WDTS7024RZ Dishwasher SS - Display Only",
        )
        self.assertFalse(res.mfr_url, f"expected no URL, got {res.mfr_url!r}")

    def test_a_brand_in_the_description_picks_the_right_candidate(self) -> None:
        res = enrich_product_web(
            "PDSH4816AF", "Appliance Dealers Cooperative (APPDE)",
            "PDSH4816AF Frigidaire Dishwasher SS",
        )
        self.assertIn("frigidaire.com", res.mfr_url or "")

    def test_a_brand_column_picks_the_right_candidate(self) -> None:
        # DIB_Brand carries the real brand on many rows even when the
        # description does not.
        res = enrich_product_web(
            "576512", "Phillips Lighting (5831)", "576512 65W Led BR40 Med 27k",
            dib_brand="Philips",
        )
        self.assertIn("philips", res.mfr_url or "")

    def test_an_unambiguous_manufacturer_still_resolves(self) -> None:
        res = enrich_product_web(
            "70-100-01", "Apollo Valves", "1/2 in Bronze Ball Valve 600 PSI",
        )
        self.assertTrue(res.mfr_url)
        self.assertIn("apollo", res.mfr_url)
