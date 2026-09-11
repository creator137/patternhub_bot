from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.database import Database
from app.models.product import ParsedProduct, ProductFilter
from app.providers.base import BaseProvider, ProviderResult
from app.repositories.products import ProductRepository
from app.services.catalog import CatalogService


def product(
    name: str,
    category: str,
    *,
    source_product_id: str,
    source: str = "vikisews",
    price: str | None = "280",
    old_price: str | None = None,
    image_url: str | None = "https://example.com/item.jpg",
    audience: str | None = "women",
) -> ParsedProduct:
    return ParsedProduct(
        source=source,
        source_product_id=source_product_id,
        name=name,
        brand="VikiSews",
        audience=audience,
        category=category,
        subcategory=category,
        price=Decimal(price) if price is not None else None,
        old_price=Decimal(old_price) if old_price is not None else None,
        currency="RUB",
        product_url=f"https://example.com/{source}/{source_product_id}/",
        image_url=image_url,
    )


class CatalogServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp_directory.name) / "catalog.sqlite3")
        database.initialize()
        self.repository = ProductRepository(database)
        self.service = CatalogService(self.repository)
        self.repository.upsert_many(
            [
                product("Алиса платье", "Платья", source_product_id="1"),
                product("Бетти платье", "Платья", source_product_id="2", price=None),
                product(
                    "Вега жакет",
                    "Жакеты и жилеты",
                    source_product_id="3",
                    price="350",
                    old_price="440",
                    image_url=None,
                ),
                product(
                    "Макс брюки",
                    "Брюки и шорты",
                    source_product_id="4",
                    audience="men",
                ),
                product(
                    "Детское платье",
                    "Платья",
                    source_product_id="5",
                    audience="kids",
                ),
            ]
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    async def test_get_categories(self) -> None:
        categories = await self.service.get_categories(section="women")

        self.assertEqual(
            [(category.name, category.products) for category in categories],
            [("Жакеты и жилеты", 1), ("Платья", 2)],
        )

    async def test_get_products_by_category(self) -> None:
        products = await self.service.get_products(
            filters=ProductFilter(category="Платья")
        )

        self.assertEqual(
            [product.name for product in products],
            ["Алиса платье", "Бетти платье", "Детское платье"],
        )

    async def test_empty_category(self) -> None:
        count = await self.service.count_products(ProductFilter(category="Юбки"))
        products = await self.service.get_products(filters=ProductFilter(category="Юбки"))

        self.assertEqual(count, 0)
        self.assertEqual(products, [])

    async def test_get_product(self) -> None:
        saved = await self.service.get_products(limit=1)

        product = await self.service.get_product(saved[0].id)

        self.assertIsNotNone(product)
        self.assertEqual(product.name, "Алиса платье")

    async def test_combines_audience_and_category_filters(self) -> None:
        products = await self.service.get_products(
            filters=ProductFilter(audience="men", category="Брюки и шорты")
        )

        self.assertEqual([product.name for product in products], ["Макс брюки"])

    async def test_complete_snapshot_marks_missing_products_unavailable(self) -> None:
        self.repository.upsert_many(
            [
                product("Старое платье", "Платья", source_product_id="old", source="studio_yusupova"),
                product("Новое платье", "Платья", source_product_id="new", source="studio_yusupova"),
            ]
        )

        stats = await self.service.synchronize(
            FakeProvider(
                [
                    product("Новое платье", "Платья", source_product_id="new", source="studio_yusupova"),
                ],
                source="studio_yusupova",
                complete=True,
            )
        )

        self.assertEqual(stats.unavailable, 1)
        self.assertTrue(stats.complete)
        self.assertEqual(await self.service.count_products(ProductFilter(source="studio_yusupova")), 1)
        self.assertEqual(self.repository.stats().unavailable, 1)

    async def test_incomplete_snapshot_does_not_mark_missing_products_unavailable(self) -> None:
        self.repository.upsert_many(
            [
                product("Старое платье", "Платья", source_product_id="old", source="studio_yusupova"),
                product("Новое платье", "Платья", source_product_id="new", source="studio_yusupova"),
            ]
        )

        stats = await self.service.synchronize(
            FakeProvider(
                [
                    product("Новое платье", "Платья", source_product_id="new", source="studio_yusupova"),
                ],
                source="studio_yusupova",
                complete=False,
            )
        )

        self.assertEqual(stats.unavailable, 0)
        self.assertFalse(stats.complete)
        self.assertEqual(await self.service.count_products(ProductFilter(source="studio_yusupova")), 2)

    async def test_reappeared_product_becomes_available_again(self) -> None:
        old = product("Старое платье", "Платья", source_product_id="old", source="studio_yusupova")
        new = product("Новое платье", "Платья", source_product_id="new", source="studio_yusupova")
        self.repository.upsert_many([old, new])
        await self.service.synchronize(FakeProvider([new], source="studio_yusupova", complete=True))

        stats = await self.service.synchronize(FakeProvider([old, new], source="studio_yusupova", complete=True))

        self.assertEqual(stats.unavailable, 0)
        products = await self.service.get_products(filters=ProductFilter(source="studio_yusupova"))
        self.assertEqual({item.source_product_id for item in products}, {"old", "new"})

    async def test_unavailable_products_are_hidden_from_categories(self) -> None:
        visible = product("Видимое платье", "Платья", source_product_id="visible", source="studio_yusupova")
        hidden = product(
            "Скрытое платье",
            "Платья",
            source_product_id="hidden",
            source="studio_yusupova",
        )
        self.repository.upsert_many([visible, hidden])
        await self.service.synchronize(FakeProvider([visible], source="studio_yusupova", complete=True))

        categories = await self.service.get_categories(
            filters=ProductFilter(source="studio_yusupova", audience="women")
        )
        products = await self.service.get_products(
            filters=ProductFilter(source="studio_yusupova", category="Платья")
        )

        self.assertEqual([(category.name, category.products) for category in categories], [("Платья", 1)])
        self.assertEqual([item.name for item in products], ["Видимое платье"])


class FakeProvider(BaseProvider):
    def __init__(
        self,
        products: list[ParsedProduct],
        *,
        source: str = "vikisews",
        complete: bool,
        errors: int = 0,
    ) -> None:
        self.source = source
        self.products = products
        self.complete = complete
        self.errors = errors

    async def fetch_products(self) -> ProviderResult:
        return ProviderResult(
            self.products,
            errors=self.errors,
            complete=self.complete,
        )


if __name__ == "__main__":
    unittest.main()
