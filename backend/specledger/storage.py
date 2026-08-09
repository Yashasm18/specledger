"""Storage contracts shared by local and production adapters."""

from __future__ import annotations

from typing import Protocol

from .models import Product


class ProductStore(Protocol):
    def save_product(self, product: Product, organization_id: str = "default") -> None: ...

    def get_product(self, product_id: str, organization_id: str = "default") -> Product | None: ...

