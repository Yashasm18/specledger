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
        # Slot order now follows the category's declared schema, which is how
        # Unilog's own rows are laid out, so the first slot is the first
        # attribute of that schema rather than the first thing extracted.
        # What matters is that identity fields hold none of them, and that
        # extracted values land on their own label with the right unit.
        by_label = {a.label: a for a in res.attributes}
        self.assertNotIn("Manufacturer", by_label)
        self.assertNotIn("Part Number", by_label)
        self.assertEqual(by_label["Voltage Rating"].value, "120")
        self.assertEqual(by_label["Voltage Rating"].uom, "V")

    def test_feature_bullets_cover_every_spec_that_has_a_value(self) -> None:
        # A bullet is a claim about the product, so it needs a value behind
        # it. Attributes now include the category's declared labels, which
        # are delivered empty when the description does not state them —
        # those are schema, not features.
        res = enrich_product_web(
            "PDSH4816AF", "Appliance Dealers Cooperative (APPDE)",
            "PDSH4816AF Dishwasher 120V 15A",
        )
        with_values = [a for a in res.attributes if a.value]
        self.assertEqual(len(res.features), len(with_values))
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


class SpecExtractionPrecisionTests(unittest.TestCase):
    """Specs must come from the description, never from the part number.

    Identifiers sitting at the head of a description were being mined for
    specifications on the official dataset:

      "49-94-0013 Milw 5\"x.045\" Metal Cut Off Disc"  -> Grit 49   (34 rows)
      "37418A Kichler Bath Light"                     -> 37418 A
      "9A-570-240 Abranet 2.75x30"                    -> 9 A

    None of those are specs, and a cut-off disc has no grit at all. A part
    number is an identifier by definition, so it is removed before any spec
    is read out of the text.
    """

    def test_no_grit_from_a_part_number_prefix(self) -> None:
        res = enrich_product_web(
            "49-94-0013", "Milwaukee Tool",
            '49-94-0013 Milw 5"x.045"x7/8" Metal Cut Off Disc',
        )
        # The abrasives template declares a Grit attribute, so the label is
        # present. What must not appear is a value: a cut-off disc has no
        # grit, and "49" was its part number.
        grit = {a.label: a.value for a in res.attributes}.get("Grit", "")
        self.assertEqual(grit, "")

    def test_no_amperage_from_a_part_number_suffix(self) -> None:
        res = enrich_product_web("37418A", "Kichler", "37418A Kichler Bath Light")
        amps = {a.label: a.value for a in res.attributes}.get("Amperage Rating", "")
        self.assertEqual(amps, "")

    def test_no_grit_from_a_fractional_size(self) -> None:
        # 1/2" is a width. It is not grit 1.
        res = enrich_product_web(
            "DCB518ASTS06G", "Freud Inc",
            'DCB518ASTS06G Diablo 1/2"x18" - Sanding Belt 6pc',
        )
        grit = {a.label: a.value for a in res.attributes}.get("Grit", "")
        self.assertEqual(grit, "")

    def test_a_real_p_designation_is_still_read(self) -> None:
        res = enrich_product_web(
            "3MABR-7100075678", "3M",
            "3M 775L Stikit Film P150 - Cubitron II 50 Disc/Box",
        )
        grit = [a for a in res.attributes if a.label == "Grit"]
        self.assertEqual([a.value for a in grit], ["P150"])

    def test_a_number_stated_as_grit_is_still_read(self) -> None:
        res = enrich_product_web(
            "DFBLBLOMFN01G", "Freud Inc",
            "DFBLBLOMFN01G Diablo 220 Grit - Flat Edge Sanding Sponge",
        )
        grit = [a for a in res.attributes if a.label == "Grit"]
        self.assertEqual([a.value for a in grit], ["220"])

    def test_a_real_amperage_is_still_read(self) -> None:
        res = enrich_product_web(
            "R02D215P1RW", "Leviton", "R02D215P1RW 15A Mini Outlet Wh",
        )
        amps = [a for a in res.attributes if a.label == "Amperage Rating"]
        self.assertEqual([(a.value, a.uom) for a in amps], [("15", "A")])

    def test_voltage_and_horsepower_are_unaffected(self) -> None:
        res = enrich_product_web(
            "10047VS", "Oliver", "10047VS Oliver 3HP 230V 1PH Shaper 1-1/4 Spindle",
        )
        found = {a.label: a.value for a in res.attributes}
        self.assertEqual(found.get("Voltage Rating"), "230")
        self.assertEqual(found.get("Horsepower"), "3")


class KeywordBoundaryTests(unittest.TestCase):
    """Category keywords must match words, not fragments inside other words.

    The cascade tested membership with `kw in text`, so every keyword also
    matched anything containing it. Found by running a real 1,081-row public
    product catalogue through the live app: a Bose speaker system came back
    as a kitchen appliance ("range" inside "wide-range drivers") and a Sony
    A/V switcher as an electrical wiring device ("switch" inside "Switcher").

    The same flaw reaches much further — "lamp" inside "clamp", "led" inside
    "sealed", "trap" inside "strap", "oven" inside "proven", "tape" inside
    "tapered" — so a hose clamp classified as lighting.
    """

    def _cat(self, desc: str) -> str:
        return classify_category(desc, "")

    def test_fragments_do_not_trigger_a_category(self) -> None:
        for desc, fragment in [
            ("Stainless Steel Hose Clamp 2 in", "lamp/clamp"),
            ("Nylon Strap Tie Down 10 ft", "trap/strap"),
            ("Sealed Ball Bearing 6203-2RS", "led/sealed"),
            ("Tapered Roller Bearing Set", "tape/tapered"),
            ("Sony Switcher SBV40S A/V Selector", "switch/switcher"),
        ]:
            with self.subTest(fragment=fragment):
                self.assertEqual(
                    self._cat(desc), "Industrial Supplies > Maintenance",
                    f"{fragment}: {desc!r} matched on a word fragment",
                )

    def test_a_hyphenated_compound_is_not_its_last_word(self) -> None:
        # "wide-range" is not a kitchen range.
        cat = self._cat("Bose Speaker System 2 Wide-range Drivers 200 Watts")
        self.assertNotIn("Kitchen", cat)

    def test_real_keywords_still_match(self) -> None:
        self.assertIn("Lighting", self._cat("65W Led BR40 Med 27k"))
        self.assertIn("Valves", self._cat("1/2 in Bronze Ball Valve 600 PSI"))
        self.assertIn("Switches", self._cat("20A Industrial Rocker Switch"))
        self.assertIn("Abrasives", self._cat("3M Stikit Film P150 Disc/Box"))
        self.assertIn("Kitchen", self._cat("Frigidaire Gas Range 30 in Stainless"))


class PlaceholderHonestyTests(unittest.TestCase):
    """Missing identity is delivered blank, not as invented text.

    A file with no usable manufacturer or part-number column exported
    "Industrial Manufacturer" and "UNKNOWN-PN" — strings that read like data
    in a spreadsheet and are not. Same defect as the "manufacturer.com"
    placeholder URL: absent is a real answer, and stating it plainly is
    better than filling the cell with something that isn't true.
    """

    def test_absent_manufacturer_is_blank(self) -> None:
        res = enrich_product_web("X-1", None, "X-1 Widget Assembly")
        self.assertEqual(res.manufacturer_clean or "", "")
        self.assertNotIn("Industrial Manufacturer", str(res.manufacturer_clean))

    def test_absent_part_number_is_blank(self) -> None:
        res = enrich_product_web("", "Parker Hannifin", "Bronze Ball Valve")
        self.assertEqual(res.part_number or "", "")

    def test_present_values_are_untouched(self) -> None:
        res = enrich_product_web("V-100", "Parker Hannifin", "Bronze Ball Valve")
        self.assertEqual(res.part_number, "V-100")
        self.assertEqual(res.manufacturer_clean, "Parker Hannifin")


class SizeAttributeTests(unittest.TestCase):
    """Dimensions belong in the attribute slots too.

    Unilog's worked rows carry a "Size" attribute (`24 in W x 24-1/4 in D`).
    We already parsed dimensions out of the description and wrote them to the
    LENGTH/WIDTH columns, then left the attribute slot empty — the data was
    computed and simply not delivered where their format expects it.
    """

    def _attrs(self, desc: str) -> dict:
        res = enrich_product_web("X-1", "Freud Inc", desc)
        return {a.label: (a.value, a.uom) for a in res.attributes}

    def test_size_is_emitted_when_two_dimensions_are_present(self) -> None:
        attrs = self._attrs('DCB518ASTS06G Diablo 1/2"x18" - Sanding Belt 6pc')
        self.assertEqual(attrs.get("Size"), ("1/2 in x 18 in", None))

    def test_weight_is_emitted_with_its_unit(self) -> None:
        attrs = self._attrs("Mortar Mix 50 lb Bag")
        self.assertEqual(attrs.get("Weight"), ("50", "LB"))

    def test_nothing_is_invented_when_no_dimension_is_stated(self) -> None:
        attrs = self._attrs("Plain Widget Assembly")
        self.assertNotIn("Size", attrs)
        self.assertNotIn("Weight", attrs)

    def test_size_does_not_displace_a_real_spec(self) -> None:
        attrs = self._attrs('Bandsaw 18" 1.75HP 1PH 115V')
        self.assertIn("Voltage Rating", attrs)
        self.assertIn("Horsepower", attrs)


class ManufacturerUrlShapeTests(unittest.TestCase):
    """The guessed URL should land somewhere that exists.

    The generated MFR URL was `https://www.{domain}/product/{slug}`. Probed
    against the registry's own domains, that shape 404s about as often as it
    resolves — freudtools, milwaukeetool, makitatools and southwire all
    reject it, while dewalt, leviton, kichler and apollovalves accept it.
    A search URL resolved on seven of the eight domains that answered.

    Unilog's own worked row does the same thing: its Whirlpool entry is
    `learnwhirlpool.com/smartsearchresults?searchtext=WDTS7024R`, a search,
    not a product path.

    This is the unverified candidate a person clicks. Live verification
    builds its own candidates and is unaffected.
    """

    def test_url_queries_the_manufacturer_site_for_the_part(self) -> None:
        res = enrich_product_web("70-100-01", "Apollo Valves", "Bronze Ball Valve")
        self.assertIn("apollovalves.com", res.mfr_url)
        self.assertIn("70-100-01", res.mfr_url)
        self.assertNotIn("/product/", res.mfr_url)

    def test_part_numbers_are_encoded_for_a_query_string(self) -> None:
        res = enrich_product_web("A&B 100/2", "Apollo Valves", "Bronze Ball Valve")
        # A raw "&" would end the query parameter early.
        self.assertNotIn("&B", res.mfr_url)
        self.assertIn("%26", res.mfr_url)

    def test_still_nothing_when_the_manufacturer_is_unknown(self) -> None:
        res = enrich_product_web("X-1", "V & V Appliance Parts Inc", "Dryer Timer")
        self.assertFalse(res.mfr_url)


class AttributeTemplateTests(unittest.TestCase):
    """Each category declares the attributes it expects.

    Unilog's two worked rows use the same 15 attribute labels in the same
    order, and emit the label even where they have no value for it —
    "Model", "Plug Type" and "Colour" are all present and blank. That is a
    per-category schema, and it is most of the gap between the 79 columns
    their rows populate and the 43 ours did.

    The label says which attribute the category has. The value is only
    filled when the description actually states it, so a blank stays a
    blank rather than becoming a guess.
    """

    def _labels(self, desc: str, mfr: str = "") -> list:
        res = enrich_product_web("X-1", mfr, desc)
        return [a.label for a in res.attributes]

    def test_a_dishwasher_declares_unilogs_own_schema(self) -> None:
        labels = self._labels("Frigidaire Dishwasher Built-in 120V 15A Stainless")
        for expected in ("Series", "Voltage Rating", "Sound Level", "Material"):
            self.assertIn(expected, labels)
        # Their order, so a column position means the same thing row to row.
        self.assertLess(labels.index("Series"), labels.index("Voltage Rating"))

    def test_an_extracted_value_lands_on_its_template_label(self) -> None:
        res = enrich_product_web("X-1", "", "Frigidaire Dishwasher Built-in 120V 15A")
        by_label = {a.label: a.value for a in res.attributes}
        self.assertEqual(by_label["Voltage Rating"], "120")
        self.assertEqual(by_label["Amperage Rating"], "15")

    def test_template_labels_without_a_value_stay_empty(self) -> None:
        res = enrich_product_web("X-1", "", "Frigidaire Dishwasher Built-in 120V 15A")
        by_label = {a.label: a.value for a in res.attributes}
        self.assertIn("Series", by_label)
        self.assertEqual(by_label["Series"], "")

    def test_a_category_with_no_template_still_reports_real_specs(self) -> None:
        labels = self._labels("Widget Assembly 240V")
        self.assertIn("Voltage Rating", labels)

    def test_feature_bullets_only_come_from_values_we_have(self) -> None:
        # A declared-but-empty attribute is not a feature of the product.
        res = enrich_product_web("X-1", "", "Frigidaire Dishwasher Built-in 120V 15A")
        self.assertTrue(res.features)
        self.assertTrue(all(":" in f and not f.endswith(": ") for f in res.features))
        self.assertFalse(any(f.startswith("Series") for f in res.features))
