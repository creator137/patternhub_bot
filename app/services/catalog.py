from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import monotonic

from app.models.product import CatalogBrand, CatalogCategory, Product, ProductFilter, SyncStats
from app.providers.base import BaseProvider
from app.repositories.products import ProductRepository


logger = logging.getLogger(__name__)


WOMEN_SECTION = "women"
MEN_SECTION = "men"
KIDS_SECTION = "kids"
UNISEX_SECTION = "unisex"
BRANDS_SECTION = "brands"
SALE_SECTION = "sale"
FREE_SECTION = "free"
NEW_SECTION = "new"
SOURCE_SECTION_PREFIX = "src_"


@dataclass(frozen=True, slots=True)
class CatalogSection:
    code: str
    title: str
    products: int
    available: bool = True


class CatalogService:
    def __init__(self, repository: ProductRepository) -> None:
        self.repository = repository

    async def synchronize(self, provider: BaseProvider) -> SyncStats:
        started = monotonic()
        logger.info("Starting parser: %s", provider.source)
        result = await provider.fetch_products()
        logger.info("Parser %s found %d products", provider.source, len(result.products))
        added, updated = await asyncio.to_thread(
            self.repository.upsert_many, result.products
        )
        unavailable = 0
        if result.complete and result.errors == 0:
            unavailable = await asyncio.to_thread(
                self.repository.mark_unavailable_missing,
                provider.source,
                result.products,
            )
        else:
            logger.warning(
                "Skipping availability reconciliation for %s: complete=%s errors=%d",
                provider.source,
                result.complete,
                result.errors,
            )
        if result.skipped_product_ids or result.skipped_product_urls:
            await asyncio.to_thread(
                self.repository.delete_source_products,
                provider.source,
                source_product_ids=result.skipped_product_ids,
                product_urls=result.skipped_product_urls,
            )
        stats = SyncStats(
            source=provider.source,
            found=len(result.products),
            added=added,
            updated=updated,
            skipped=result.skipped,
            unavailable=unavailable,
            errors=result.errors,
            complete=result.complete,
            duration_seconds=monotonic() - started,
        )
        logger.info(
            (
                "Parser %s complete: found=%d added=%d updated=%d skipped=%d "
                "unavailable=%d errors=%d complete=%s duration=%.2fs"
            ),
            stats.source,
            stats.found,
            stats.added,
            stats.updated,
            stats.skipped,
            stats.unavailable,
            stats.errors,
            stats.complete,
            stats.duration_seconds,
        )
        return stats

    async def get_sections(self) -> list[CatalogSection]:
        women_count = await self.count_products(ProductFilter(audience="women"))
        men_count = await self.count_products(ProductFilter(audience="men"))
        kids_count = await self.count_products(ProductFilter(audience="kids"))
        unisex_count = await self.count_products(ProductFilter(audience="unisex"))
        return [
            CatalogSection(WOMEN_SECTION, "👗 Женские", women_count, women_count > 0),
            CatalogSection(MEN_SECTION, "👔 Мужские", men_count, men_count > 0),
            CatalogSection(KIDS_SECTION, "🧒 Детские", kids_count, kids_count > 0),
            CatalogSection(BRANDS_SECTION, "🏷 Все бренды", await self.count_products()),
            CatalogSection(
                SALE_SECTION,
                "🔥 Скидки",
                await self.count_products(ProductFilter(is_sale=True)),
            ),
            CatalogSection(
                FREE_SECTION,
                "🆓 Бесплатные",
                await self.count_products(ProductFilter(is_free=True)),
            ),
            CatalogSection(
                NEW_SECTION,
                "🆕 Новинки",
                await self.count_products(ProductFilter(is_new=True)),
            ),
        ]

    async def get_categories(
        self, *, section: str | None = None, filters: ProductFilter | None = None
    ) -> list[CatalogCategory]:
        repository_filters = self._section_filter(section, filters)
        categories = await asyncio.to_thread(
            self.repository.list_categories, repository_filters
        )
        return categories

    async def get_category_by_code(
        self,
        code: str,
        *,
        section: str | None = None,
        filters: ProductFilter | None = None,
    ) -> CatalogCategory | None:
        for category in await self.get_categories(section=section, filters=filters):
            if category.code == code:
                return category
        return None

    async def get_brands(self, filters: ProductFilter | None = None) -> list[CatalogBrand]:
        return await asyncio.to_thread(self.repository.list_brands, filters)

    async def get_products(
        self,
        *,
        limit: int = 10,
        offset: int = 0,
        filters: ProductFilter | None = None,
    ) -> list[Product]:
        return await asyncio.to_thread(
            self.repository.list_products,
            limit,
            offset=offset,
            filters=filters,
        )

    async def get_product(self, product_id: int) -> Product | None:
        return await asyncio.to_thread(self.repository.get_product, product_id)

    async def save_product_photo_file_id(
        self,
        product_id: int,
        file_id: str,
        *,
        status: str = "telegram_file_id",
    ) -> None:
        await asyncio.to_thread(
            self.repository.set_photo_file_id,
            product_id,
            file_id,
            status=status,
        )

    async def save_product_image_status(self, product_id: int, status: str) -> None:
        await asyncio.to_thread(self.repository.set_image_status, product_id, status)

    async def count_products(self, filters: ProductFilter | None = None) -> int:
        return await asyncio.to_thread(self.repository.count_products, filters)

    @staticmethod
    def _section_filter(
        section: str | None, filters: ProductFilter | None
    ) -> ProductFilter | None:
        if filters is not None:
            return filters
        if section == WOMEN_SECTION:
            return ProductFilter(audience="women")
        if section == MEN_SECTION:
            return ProductFilter(audience="men")
        if section == KIDS_SECTION:
            return ProductFilter(audience="kids")
        if section == UNISEX_SECTION:
            return ProductFilter(audience="unisex")
        if section and section.startswith(SOURCE_SECTION_PREFIX):
            return ProductFilter(source=section.removeprefix(SOURCE_SECTION_PREFIX))
        if section == SALE_SECTION:
            return ProductFilter(is_sale=True)
        if section == FREE_SECTION:
            return ProductFilter(is_free=True)
        if section == NEW_SECTION:
            return ProductFilter(is_new=True)
        return None
