"""Tests for source discovery and blocked-source enforcement."""

import unittest

from backend.specledger.source_discovery import (
    is_blocked_source, extract_domain, is_manufacturer_domain,
    classify_source_type, build_search_queries, build_direct_urls,
    discover_sources_simulated, discover_sources_batch,
    SourceType, SourceStatus, MANUFACTURER_DOMAINS,
)


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


if __name__ == "__main__":
    unittest.main()
