"""Small HTTP API for the first SpecLedger workflow."""

from __future__ import annotations

from typing import Any

from .diff import compare_versions
from .models import Product
from .repository import ProductRepository
from .validation import validate_version


def product_summary(product: Product) -> dict[str, Any]:
    latest = product.latest_version()
    return {
        "product_id": product.product_id,
        "sku": product.sku,
        "name": product.name,
        "category": product.category,
        "version_count": len(product.versions),
        "latest_version": latest.version_id,
        "attribute_count": len(latest.attributes),
    }


class SpecLedgerService:
    """Application service kept framework-independent for easy testing."""

    def __init__(self, repository: ProductRepository) -> None:
        self.repository = repository

    def create_or_update_product(self, product: Product) -> dict[str, Any]:
        self.repository.save_product(product)
        return product_summary(product)

    def get_product(self, product_id: str) -> Product | None:
        return self.repository.get_product(product_id)

    def validate_latest(self, product_id: str, required_attributes: set[str] | None = None) -> list[dict[str, Any]]:
        product = self.repository.get_product(product_id)
        if product is None:
            raise KeyError(f"Product '{product_id}' was not found")
        return [issue.__dict__ for issue in validate_version(product.latest_version(), required_attributes)]

    def compare_latest_versions(self, product_id: str) -> list[dict[str, Any]]:
        product = self.repository.get_product(product_id)
        if product is None:
            raise KeyError(f"Product '{product_id}' was not found")
        if len(product.versions) < 2:
            return []
        previous, current = product.versions[-2:]
        return [change.as_dict() for change in compare_versions(previous, current)]

