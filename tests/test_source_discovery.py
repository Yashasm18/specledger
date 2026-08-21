"""Tests for source discovery and blocked-source enforcement."""

import unittest

from backend.specledger.source_discovery import (
    is_blocked_source, extract_domain, is_manufacturer_domain, extract_match_snippet,
    prioritise_candidates,
    classify_source_type, build_search_queries, build_direct_urls,
    discover_sources_simulated, discover_sources_batch,
    extract_pdf_attributes,
    SourceType, SourceStatus, MANUFACTURER_DOMAINS,
)


def _make_pdf(text: str) -> bytes:
    import fitz
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 50), text, fontsize=11)
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


class BlockedSourceTests(unittest.TestCase):
    def test_amazon_blocked(self) -> None:
        assert is_blocked_source("https://www.amazon.com/dp/B001234")
        assert is_blocked_source("https://amazon.co.uk/product/xyz")

    def test_ebay_blocked(self) -> None:
        assert is_blocked_source("https://www.ebay.com/itm/123456")

    def test_walmart_blocked(self) -> None:
        assert is_blocked_source("https://www.walmart.com/ip/valve")

    def test_alibaba_blocked(self) -> None:
        assert is_blocked_source("https://www.alibaba.com/product-detail/valve")

    def test_industrial_distributors_blocked(self) -> None:
        # Distributors resell rather than manufacture, so they are not an
        # authoritative source of record even though they carry real
        # industrial catalogue data.
        assert is_blocked_source("https://www.grainger.com/product/12345")
        assert is_blocked_source("https://www.mcmaster.com/1234A56/")
        assert is_blocked_source("https://www.zoro.com/product/G1234567/")
        assert is_blocked_source("https://www.fastenal.com/product/98765")
        assert is_blocked_source("https://www.mscdirect.com/product/details/1234")
        assert is_blocked_source("https://www.ferguson.com/product/faucet-123")

    def test_additional_marketplaces_blocked(self) -> None:
        assert is_blocked_source("https://www.temu.com/goods.html")
        assert is_blocked_source("https://www.dhgate.com/product/1234.html")
        assert is_blocked_source("https://www.made-in-china.com/product/abc")
        assert is_blocked_source("https://www.bestbuy.com/site/item/123")
        assert is_blocked_source("https://www.menards.com/main/p-1234.htm")

    def test_manufacturer_not_blocked(self) -> None:
        assert not is_blocked_source("https://www.parker.com/product/valve-123")
        assert not is_blocked_source("https://www.emerson.com/catalog/item")

    def test_shopping_url_patterns_blocked(self) -> None:
        assert is_blocked_source("https://example.com/shop/add-to-cart?id=123")
        assert is_blocked_source("https://example.com/checkout/buy-now")

    def test_generic_url_not_blocked(self) -> None:
        assert not is_blocked_source("https://www.swagelok.com/en/product/valves")

    def test_empty_url_not_blocked(self) -> None:
        assert not is_blocked_source("")

    def test_invalid_url_not_blocked(self) -> None:
        assert not is_blocked_source("not-a-url")


class DomainExtractionTests(unittest.TestCase):
    def test_extract_simple_domain(self) -> None:
        assert extract_domain("https://www.parker.com/product") == "parker.com"

    def test_extract_with_www(self) -> None:
        assert extract_domain("https://www.emerson.com/us/en") == "emerson.com"

    def test_extract_subdomain(self) -> None:
        assert extract_domain("https://shop.nibco.com/catalog") == "shop.nibco.com"

    def test_extract_empty_url(self) -> None:
        assert extract_domain("") == ""


class ManufacturerDomainTests(unittest.TestCase):
    def test_parker_domain(self) -> None:
        assert is_manufacturer_domain("https://www.parker.com/product/V-100", "Parker Hannifin")

    def test_emerson_domain(self) -> None:
        assert is_manufacturer_domain("https://www.emerson.com/en-us/catalog", "Emerson Electric")

    def test_wrong_manufacturer_domain(self) -> None:
        assert not is_manufacturer_domain("https://www.parker.com/product", "Emerson Electric")

    def test_unknown_manufacturer(self) -> None:
        assert not is_manufacturer_domain("https://www.example.com", "UnknownCo")


class SourceTypeClassificationTests(unittest.TestCase):
    def test_pdf_datasheet(self) -> None:
        assert classify_source_type("https://parker.com/docs/V100-datasheet.pdf") == SourceType.SPECIFICATION_SHEET

    def test_generic_pdf(self) -> None:
        assert classify_source_type("https://parker.com/docs/brochure.pdf") == SourceType.PDF_DATASHEET

    def test_manual_pdf(self) -> None:
        assert classify_source_type("https://parker.com/docs/V100-manual.pdf") == SourceType.TECHNICAL_MANUAL

    def test_product_page(self) -> None:
        assert classify_source_type("https://parker.com/product/V-100") == SourceType.PRODUCT_PAGE

    def test_catalogue_page(self) -> None:
        assert classify_source_type("https://parker.com/catalogue/valves") == SourceType.CATALOGUE_PAGE

    def test_video(self) -> None:
        assert classify_source_type("https://parker.com/video/install-guide.mp4") == SourceType.VIDEO


class SearchQueryTests(unittest.TestCase):
    def test_builds_multiple_queries(self) -> None:
        queries = build_search_queries("Parker Hannifin", "V-100")
        assert len(queries) >= 3
        assert any("datasheet" in q for q in queries)
        assert any("product page" in q for q in queries)

    def test_builds_site_restricted_query(self) -> None:
        queries = build_search_queries("Parker Hannifin", "V-100")
        assert any("site:parker.com" in q for q in queries)


class DirectURLTests(unittest.TestCase):
    def test_builds_urls_for_known_manufacturer(self) -> None:
        urls = build_direct_urls("Parker Hannifin", "V-100")
        assert len(urls) >= 2
        assert all("parker.com" in u for u in urls)

    def test_no_urls_for_unknown_manufacturer(self) -> None:
        urls = build_direct_urls("UnknownCo", "X-999")
        assert len(urls) == 0


class SimulatedDiscoveryTests(unittest.TestCase):
    def test_discovers_sources_for_known_manufacturer(self) -> None:
        result = discover_sources_simulated("Parker Hannifin", "V-100")
        assert result.source_count >= 2
        assert result.has_product_page
        assert result.has_datasheet
        assert all(s.manufacturer == "Parker Hannifin" for s in result.sources)
        assert all(s.part_number == "V-100" for s in result.sources)

    def test_no_sources_for_unknown_manufacturer(self) -> None:
        result = discover_sources_simulated("UnknownCo", "X-999")
        assert result.source_count == 0
        assert len(result.search_queries) > 0

    def test_source_has_timestamp(self) -> None:
        result = discover_sources_simulated("Emerson Electric", "E-200")
        for source in result.sources:
            assert source.discovered_at > 0

    def test_source_has_content_hash(self) -> None:
        result = discover_sources_simulated("Honeywell", "H-300")
        for source in result.sources:
            assert source.content_hash is not None
            assert len(source.content_hash) > 0

    def test_result_serialization(self) -> None:
        result = discover_sources_simulated("Parker Hannifin", "V-100")
        output = result.to_dict()
        assert "manufacturer" in output
        assert "part_number" in output
        assert "source_count" in output
        assert "sources" in output
        assert len(output["sources"]) >= 2


class BatchDiscoveryTests(unittest.TestCase):
    def test_batch_discovers_multiple_products(self) -> None:
        rows = [
            ("Parker Hannifin", "V-100"),
            ("Emerson Electric", "E-200"),
            ("Honeywell", "H-300"),
        ]
        results = discover_sources_batch(rows)
        assert len(results) == 3
        assert all(r.source_count >= 2 for r in results)

    def test_batch_deduplicates_same_product(self) -> None:
        rows = [
            ("Parker Hannifin", "V-100"),
            ("Parker Hannifin", "V-100"),  # duplicate
        ]
        results = discover_sources_batch(rows)
        assert len(results) == 2
        # Both should reference the same discovery result
        assert results[0].sources[0].url == results[1].sources[0].url

    def test_batch_handles_unknown_manufacturers(self) -> None:
        rows = [
            ("Parker Hannifin", "V-100"),
            ("UnknownCo", "X-999"),
        ]
        results = discover_sources_batch(rows)
        assert results[0].source_count >= 2
        assert results[1].source_count == 0


class PdfAttributeExtractionTests(unittest.TestCase):
    def test_extracts_real_label_value_rows(self) -> None:
        pdf_bytes = _make_pdf(
            "Datasheet\n"
            "Series: Professional Series\n"
            "Voltage Rating: 120 V\n"
            "Amperage Rating: 15 A\n"
            "Material: Stainless Steel\n"
        )
        attrs = extract_pdf_attributes(pdf_bytes)
        assert ("Series", "Professional Series") in attrs
        assert ("Voltage Rating", "120 V") in attrs
        assert ("Material", "Stainless Steel") in attrs

    def test_ignores_prose_sentences(self) -> None:
        pdf_bytes = _make_pdf(
            "During assembly of the advanced-geometry design the installer\n"
            "should verify torque before use. Visit our website: https://example.com\n"
            "This is a long descriptive sentence that should not match the pattern at all.\n"
        )
        attrs = extract_pdf_attributes(pdf_bytes)
        assert attrs == ()

    def test_returns_empty_tuple_for_invalid_pdf_bytes(self) -> None:
        assert extract_pdf_attributes(b"not a real pdf") == ()

    def test_deduplicates_labels_and_caps_count(self) -> None:
        words = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta"]
        lines = "\n".join(f"Attribute {word}: Value {i}" for i, word in enumerate(words))
        pdf_bytes = _make_pdf(lines)
        attrs = extract_pdf_attributes(pdf_bytes, max_attributes=5)
        assert len(attrs) == 5


if __name__ == "__main__":
    unittest.main()


class MatchSnippetTests(unittest.TestCase):
    """The snippet is the receipt — it must come from text a reader can find."""

    def test_returns_visible_text_around_the_part_number(self) -> None:
        html = "<h1>Diablo D1050X</h1><p>The D1050X is a 10 in. combination blade.</p>"
        snippet = extract_match_snippet(html, {"d1050x"})
        self.assertIsNotNone(snippet)
        self.assertIn("D1050X", snippet)
        self.assertIn("combination blade", snippet)

    def test_ignores_matches_inside_script_and_style_blocks(self) -> None:
        # A hit in a JSON blob is not something a reader can find on the page,
        # so quoting it back as evidence would be misleading.
        html = (
            '<script>var data = {"sku":"D1050X","internal":"unreachable text"};</script>'
            "<p>Visible copy mentioning D1050X here.</p>"
        )
        snippet = extract_match_snippet(html, {"d1050x"})
        self.assertIn("Visible copy", snippet)
        self.assertNotIn("unreachable text", snippet)

    def test_returns_none_when_the_part_number_is_absent(self) -> None:
        self.assertIsNone(extract_match_snippet("<p>Some other product</p>", {"d1050x"}))

    def test_collapses_whitespace_so_the_snippet_is_readable(self) -> None:
        html = "<p>Model\n\n   D1050X   \t  blade</p>"
        self.assertEqual(extract_match_snippet(html, {"d1050x"}), "Model D1050X blade")

    def test_marks_truncation_with_ellipses(self) -> None:
        html = "<p>" + ("padding " * 40) + "D1050X" + (" padding" * 40) + "</p>"
        snippet = extract_match_snippet(html, {"d1050x"})
        self.assertTrue(snippet.startswith("…"))
        self.assertTrue(snippet.endswith("…"))

    def test_prefers_the_longest_matching_variant(self) -> None:
        # "d1050x" and "d1050" both appear; the more specific one is the
        # stronger evidence and should anchor the snippet.
        html = "<p>D1050 family. The exact model is D1050X here.</p>"
        snippet = extract_match_snippet(html, {"d1050", "d1050x"}, window=10)
        self.assertIn("D1050X", snippet)


class CandidatePrioritisationTests(unittest.TestCase):
    """Search endpoints can never verify, so they must not spend the budget."""

    def test_search_urls_are_ordered_last(self) -> None:
        candidates = [
            "https://a.com/search?q=X1",
            "https://a.com/product/x1",
            "https://b.com/search?q=X1",
            "https://b.com/products/x1",
        ]
        ordered = prioritise_candidates(candidates)
        self.assertEqual(ordered[:2], ["https://a.com/product/x1", "https://b.com/products/x1"])
        self.assertTrue(all("search" in u for u in ordered[2:]))

    def test_every_candidate_is_kept(self) -> None:
        candidates = build_direct_urls("Freud Inc", "D1050X")
        self.assertCountEqual(prioritise_candidates(candidates), candidates)

    def test_a_product_page_on_the_second_domain_outranks_a_search_url_on_the_first(self) -> None:
        # This is the case that regressed: the real page lived on the second
        # registered domain, behind two search URLs that could never verify.
        ordered = prioritise_candidates(build_direct_urls("Freud Inc", "D1050X"))
        first_search = next(i for i, u in enumerate(ordered) if "search" in u)
        diablo_product = next(i for i, u in enumerate(ordered) if "diablotools" in u and "search" not in u)
        self.assertLess(diablo_product, first_search)

    def test_recognises_query_style_search_urls(self) -> None:
        ordered = prioritise_candidates([
            "https://a.com/find?query=X1",
            "https://a.com/product/x1",
        ])
        self.assertEqual(ordered[0], "https://a.com/product/x1")
