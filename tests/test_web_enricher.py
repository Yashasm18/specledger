"""Tests for taxonomy classification signal priority."""

import unittest

from backend.specledger.web_enricher import classify_category, enrich_product_web


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
