from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.product import ParsedProduct
from app.models.recency import RecencySnapshot, product_order_key
from app.models.catalog_policy import publication_datetime


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
    recency_basis = "source_publication_date"

    async def fetch_recency_snapshot(self, products) -> RecencySnapshot:
        """Use real source dates for the whole catalog, with no age cutoff."""
        products = list(products)
        dated = [(publication_datetime(p.source_published_at), p) for p in products]
        complete = bool(dated) and all(date is not None for date, _ in dated)
        ordered = sorted(((date, p) for date, p in dated if date is not None),
                         key=lambda pair: (pair[0], product_order_key(pair[1])), reverse=True)
        return RecencySnapshot.from_products(self.source, (p for _, p in ordered),
                                            basis=self.recency_basis, complete=complete)

    def publication_key(self, product) -> str:
        return str(product.source_product_id or '')

    async def fetch_publication_dates(self, client) -> dict:
        return {}

    async def publication_updates(self, products) -> dict:
        import httpx
        async with httpx.AsyncClient(timeout=httpx.Timeout(40,connect=10),follow_redirects=True,trust_env=False) as client:
            dates = await self.fetch_publication_dates(client)
        return {p.id:dates[self.publication_key(p)] for p in products if self.publication_key(p) in dates}

    async def fetch_filter_snapshots(self) -> dict[str, FilterSnapshot]:
        return {}

    def parse_publication_date(self, html: str, product_url: str):
        from app.providers.publication import product_publication_date
        return product_publication_date(html, product_url)

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
