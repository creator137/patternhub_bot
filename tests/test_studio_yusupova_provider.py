from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.database import Database
from app.models.product import ParsedProduct, ProductFilter
from app.providers.studio_yusupova import StudioYusupovaProvider
from app.repositories.products import ProductRepository
from app.services.catalog import CatalogService


FIXTURES = Path(__file__).parent / "fixtures"


class StudioYusupovaProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = StudioYusupovaProvider()
        categories_payload = json.loads(
            (FIXTURES / "studio_yusupova_categories.json").read_text(encoding="utf-8")
        )
        self.categories = self.provider._category_index(categories_payload)

    def test_parses_listing_fixture(self) -> None:
        payload = json.loads(
            (FIXTURES / "studio_yusupova_products.json").read_text(encoding="utf-8")
        )

        products = self.provider.parse_products_payload(payload, self.categories)

        self.assertEqual(len(products), 5)
        first, sale, unisex, men, skirt = products
        self.assertEqual(first.source, "studio_yusupova")
        self.assertEqual(first.source_product_id, "176766")
        self.assertEqual(first.name, "Дубленка Мирей О")
        self.assertEqual(first.brand, "Studio Yusupova")
        self.assertEqual(first.audience, "women")
        self.assertEqual(first.category, "Верхняя одежда")
        self.assertEqual(first.price, Decimal("490.00"))
        self.assertEqual(first.sizes, ("40", "42"))
        self.assertEqual(first.heights, ("162-166", "168-172"))
        self.assertEqual(
            first.image_url,
            "https://studio-yusupova.ru/wp-content/uploads/mireille.jpg",
        )
        self.assertEqual(sale.price, Decimal("380.00"))
        self.assertEqual(sale.old_price, Decimal("480.00"))
        self.assertTrue(sale.is_sale)
        self.assertFalse(sale.is_new)
        self.assertFalse(sale.is_free)
        self.assertEqual((unisex.audience, unisex.category), ("unisex", "Брюки и шорты"))
        self.assertEqual((men.audience, men.category), ("men", "Рубашки, блузки и топы"))
        self.assertEqual((skirt.audience, skirt.category), ("women", "Юбки"))

    def test_price_parser(self) -> None:
        self.assertEqual(self.provider._decimal("1 200 ₽"), Decimal("1200"))
        self.assertEqual(self.provider._decimal("329,50 ₽"), Decimal("329.50"))

    def test_slug_helps_normalize_category(self) -> None:
        self.assertEqual(
            self.provider._category_from_name(
                "Cвитшот MAGGIE F https://studio-yusupova.ru/shop/sweatshirt-maggie-fitzgerald/"
            ),
            "Худи, футболки и лонгсливы",
        )


class StudioYusupovaRepositoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp_directory.name) / "catalog.sqlite3")
        database.initialize()
        self.repository = ProductRepository(database)
        self.service = CatalogService(self.repository)

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    async def test_repeated_upsert_without_duplicates(self) -> None:
        product = ParsedProduct(
            source="studio_yusupova",
            source_product_id="176766",
            name="Дубленка Мирей О",
            brand="Studio Yusupova",
            audience="women",
            category="Верхняя одежда",
            product_url="https://studio-yusupova.ru/shop/jacket-mireille-o/",
        )

        self.assertEqual(self.repository.upsert_many([product]), (1, 0))
        self.assertEqual(self.repository.upsert_many([product]), (0, 1))
        self.assertEqual(
            self.repository.count_products(ProductFilter(source="studio_yusupova")),
            1,
        )

    async def test_same_names_from_four_sources_do_not_conflict(self) -> None:
        products = [
            ParsedProduct(
                source=source,
                source_product_id="same-id",
                name="Платье Тест",
                brand=brand,
                category="Платья",
                product_url=url,
            )
            for source, brand, url in (
                ("vikisews", "VikiSews", "https://vikisews.com/vykrojki/plate-test/"),
                ("grasser", "Grasser", "https://grasser.ru/vykrojki/plate-test/"),
                ("helpersew", "HelperSew", "https://helpersew.com/catalog/plate-test/"),
                (
                    "studio_yusupova",
                    "Studio Yusupova",
                    "https://studio-yusupova.ru/shop/plate-test/",
                ),
            )
        ]

        self.repository.upsert_many(products)

        self.assertEqual(self.repository.count_products(), 4)

    async def test_catalog_service_returns_four_sources(self) -> None:
        self.repository.upsert_many(
            [
                ParsedProduct(
                    source=source,
                    source_product_id=source,
                    name=f"Платье {source}",
                    brand=brand,
                    category="Платья",
                    product_url=url,
                )
                for source, brand, url in (
                    ("vikisews", "VikiSews", "https://vikisews.com/vykrojki/1/"),
                    ("grasser", "Grasser", "https://grasser.ru/vykrojki/2/"),
                    ("helpersew", "HelperSew", "https://helpersew.com/catalog/3/"),
                    (
                        "studio_yusupova",
                        "Studio Yusupova",
                        "https://studio-yusupova.ru/shop/4/",
                    ),
                )
            ]
        )

        products = await self.service.get_products(filters=ProductFilter(category="Платья"))

        self.assertEqual(
            {product.source for product in products},
            {"vikisews", "grasser", "helpersew", "studio_yusupova"},
        )


if __name__ == "__main__":
    unittest.main()
