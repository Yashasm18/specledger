"""Unit tests for the deep Industrial Web & PDF Scraper and PDF Submittal Generator."""

import pytest
from backend.specledger.pdf_and_web_scraper import (
    IndustrialWebScraper,
    generate_submittal_pdf,
    industrial_scraper,
    BLOCKED_SHOPPING_DOMAINS,
)


def test_anti_marketplace_firewall():
    """Verify that consumer shopping domains and cart URLs are strictly blocked."""
    scraper = IndustrialWebScraper()
    assert scraper.is_blocked("https://www.amazon.com/dp/B08XYZ123") is True
    assert scraper.is_blocked("https://www.ebay.com/itm/123456789") is True
    assert scraper.is_blocked("https://www.walmart.com/ip/Valve/12345") is True
    assert scraper.is_blocked("https://aliexpress.com/item/1000.html") is True
    assert scraper.is_blocked("https://www.temu.com/goods.html") is True
    assert scraper.is_blocked("https://www.homedepot.com/p/Valve/1001") is True
    assert scraper.is_blocked("https://www.grainger.com/product/12345") is True

    # Official manufacturer domains should NOT be blocked
    assert scraper.is_blocked("https://www.apollovalves.com/products/70-100") is False
    assert scraper.is_blocked("https://www.se.com/products/contactor") is False
    assert scraper.is_blocked("https://www.leviton.com/en/products/1221") is False


def test_manufacturer_domain_resolution():
    """Verify clean domain resolution for industrial suppliers."""
    scraper = IndustrialWebScraper()
    assert scraper.resolve_manufacturer_domain("Schneider Electric") in ["se.com", "schneider-electric.com"]
    assert scraper.resolve_manufacturer_domain("Apollo Valves") in ["apollovalves.com", "apolloflowcontrols.com"]
    assert scraper.resolve_manufacturer_domain("Honeywell") in ["honeywell.com", "honeywellhome.com"]
    assert scraper.resolve_manufacturer_domain("3M") == "3m.com"
    assert scraper.resolve_manufacturer_domain("Freud") in ["freudtools.com", "diablotools.com"]


def test_scrape_product_profile_synthesis():
    """Verify that scraping produces structured 252-column attributes, descriptions, and feature bullets."""
    profile = industrial_scraper.scrape_product_profile(
        part_number="70-100-01",
        manufacturer="Apollo Valves",
        category="Industrial Valves",
    )

    assert profile.part_number == "70-100-01"
    assert profile.manufacturer == "Apollo Valves"
    assert profile.canonical_domain in ["apollovalves.com", "apolloflowcontrols.com"]
    assert len(profile.features) == 20
    assert len(profile.attributes) >= 10
    assert len(profile.content_sha256) == 64
    assert profile.pressure_rating == "600 PSI WOG / 150 PSI WSP"
    assert "ASME B16.34" in profile.standards


def test_generate_submittal_pdf():
    """Verify that PyMuPDF generates an authentic, valid PDF document."""
    profile = industrial_scraper.scrape_product_profile(
        part_number="LC1D25B7",
        manufacturer="Schneider Electric",
        category="Electrical & Automation",
    )
    pdf_bytes = generate_submittal_pdf(profile)

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-")
