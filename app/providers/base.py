from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.product import ParsedProduct


@dataclass(frozen=True, slots=True)
class ProviderResult:
    products: list[ParsedProduct]
    errors: int = 0
    skipped: int = 0
    skipped_product_ids: tuple[str, ...] = ()
    skipped_product_urls: tuple[str, ...] = ()
    complete: bool = True


@dataclass(frozen=True)
class FilterSnapshot:
    products: list[ParsedProduct]
    complete: bool


class BaseProvider(ABC):
    source: str

    async def fetch_filter_snapshots(self) -> dict[str, FilterSnapshot]:
        return {}

    def parse_filter_metadata(self, html: str, product_url: str) -> dict:
        """Only authoritative detail facts; omitted fields remain unchanged."""
        return {}

    def parse_gallery(self, html: str, product_url: str) -> tuple[str, ...]:
        from app.providers.gallery import html_gallery
        return html_gallery(html, product_url)

    @abstractmethod
    async def fetch_products(self) -> ProviderResult:
        """Fetch source data and return products in the shared catalog format."""
        raise NotImplementedError
