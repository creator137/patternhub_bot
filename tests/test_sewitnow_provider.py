from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.database import Database
from app.models.product import ParsedProduct, ProductFilter
from app.providers.sewitnow import SewItNowCategoryContext, SewItNowProvider
from app.repositories.products import ProductRepository
from app.services.catalog import CatalogService


FIXTURES = Path(__file__).parent / "fixtures"


class SewItNowProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = SewItNowProvider()
        self.payload = json.loads(
            (FIXTURES / "sewitnow_catalog.json").read_text(encoding="utf-8")
        )
        self.groups = self.payload["pageProps"]["initSeller"]["groups"]
        self.category_index = self.provider.category_index(self.groups)

    def test_parses_listing_fixture(self) -> None:
        products, skipped = self.provider.parse_catalog_payload(
            self.payload,
            self.category_index,
            SewItNowCategoryContext(
                id="5503",
                name="Платья и комбинезоны",
                slug="platya-i-kombinezony-5503",
            ),
        )

        self.assertEqual(skipped, 1)
        self.assertEqual(len(products), 3)
        first, kids, free = products
        self.assertEqual(first.source, "sewitnow")
        self.assertEqual(first.source_product_id, "1054081")
        self.assertEqual(first.name, "Платье Эми")
        self.assertEqual(first.brand, "SewItNow")
        self.assertEqual(first.audience, "women")
        self.assertEqual(first.category, "Платья")
        self.assertEqual(first.price, Decimal("290.00"))
        self.assertEqual(first.old_price, Decimal("390.00"))
        self.assertTrue(first.is_sale)
        self.assertFalse(first.is_new)
        self.assertFalse(first.is_free)
        self.assertEqual(first.sizes, ("40",))
        self.assertEqual(first.heights, ("158",))
        self.assertEqual(
            first.image_url,
            "https://sewitnow.ru/images/plate-emi.jpg",
        )
        self.assertEqual(
            first.product_url,
            "https://sewitnow.ru/product/plate-emi-1054081/",
        )
        self.assertEqual((kids.audience, kids.category), ("kids", "Брюки и шорты"))
        self.assertEqual(kids.heights, ("104",))
        self.assertTrue(free.is_free)
        self.assertIsNone(free.image_url)

    def test_stable_catalog_data_url_uses_next_data_path(self) -> None:
        self.assertEqual(
            self.provider.catalog_data_url("build-id", "platya-i-kombinezony-5503"),
            "https://sewitnow.ru/_next/data/build-id/catalog/platya-i-kombinezony-5503.json",
        )
        self.assertEqual(
            self.provider.catalog_data_url(
                "build-id",
                "platya-i-kombinezony-5503/kombinezony-33038",
            ),
            (
                "https://sewitnow.ru/_next/data/build-id/catalog/"
                "platya-i-kombinezony-5503/kombinezony-33038.json"
            ),
        )

    def test_catalog_pages_include_nested_categories(self) -> None:
        pages = self.provider.catalog_pages(self.groups)

        self.assertIn(
            SewItNowCategoryContext(
                id="33038",
                name="Комбинезоны",
                slug="kombinezony-33038",
                parent_name="Платья и комбинезоны",
                parent_id="5503",
                parent_slug="platya-i-kombinezony-5503",
            ),
            pages,
        )
        nested = next(page for page in pages if page.id == "33038")
        self.assertEqual(
            self.provider.catalog_context_data_url("build-id", nested),
            (
                "https://sewitnow.ru/_next/data/build-id/catalog/"
                "platya-i-kombinezony-5503/kombinezony-33038.json"
            ),
        )

    def test_incomplete_snapshot_detected_from_payload_pages(self) -> None:
        self.provider.parse_catalog_payload(
            self.payload,
            self.category_index,
            SewItNowCategoryContext(
                id="5503",
                name="Платья и комбинезоны",
                slug="platya-i-kombinezony-5503",
            ),
        )

        self.assertEqual(
            self.provider.incomplete_pages,
            ["platya-i-kombinezony-5503 (2 pages, 25 products)"],
        )

    def test_price_parser(self) -> None:
        self.assertEqual(self.provider._decimal("1 200 ₽"), Decimal("1200"))
        self.assertEqual(self.provider._decimal("329,50"), Decimal("329.50"))

    def test_category_normalization(self) -> None:
        context = SewItNowCategoryContext(
            id="34131",
            name="Юбки из трикотажа",
            slug="yubki-iz-trikotaza-34131",
            parent_name="Юбки",
        )

        self.assertEqual(self.provider._category("Юбка Тест", context), "Юбки")


class SewItNowRepositoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
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
            source="sewitnow",
            source_product_id="1054081",
            name="Платье Эми",
            brand="SewItNow",
            audience="women",
            category="Платья",
            product_url="https://sewitnow.ru/product/plate-emi-1054081/",
        )

        self.assertEqual(self.repository.upsert_many([product]), (1, 0))
        self.assertEqual(self.repository.upsert_many([product]), (0, 1))
        self.assertEqual(
            self.repository.count_products(ProductFilter(source="sewitnow")),
            1,
        )

    async def test_same_name_from_five_sources_does_not_conflict(self) -> None:
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
                ("sewitnow", "SewItNow", "https://sewitnow.ru/product/plate-test/"),
            )
        ]

        self.repository.upsert_many(products)

        self.assertEqual(self.repository.count_products(), 5)

    async def test_catalog_service_returns_five_sources(self) -> None:
        self.repository.upsert_many(
            [
                ParsedProduct(
                    source=source,
                    source_product_id=source,
                    name=f"Платье {source}",
                    brand=brand,
                    audience="women",
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
                    ("sewitnow", "SewItNow", "https://sewitnow.ru/product/5/"),
                )
            ]
        )

        products = await self.service.get_products(filters=ProductFilter(category="Платья"))

        self.assertEqual(
            {product.source for product in products},
            {"vikisews", "grasser", "helpersew", "studio_yusupova", "sewitnow"},
        )

    async def test_duplicate_item_from_multiple_categories_updates_one_product(self) -> None:
        self.repository.upsert_many(
            [
                ParsedProduct(
                    source="sewitnow",
                    source_product_id="1054081",
                    name="Платье Эми",
                    brand="SewItNow",
                    audience="women",
                    category="Платья",
                    product_url="https://sewitnow.ru/product/plate-emi-1054081/",
                ),
                ParsedProduct(
                    source="sewitnow",
                    source_product_id="1054081",
                    name="Платье Эми",
                    brand="SewItNow",
                    audience=None,
                    category="Платья",
                    product_url="https://sewitnow.ru/product/plate-emi-1054081/",
                    is_free=True,
                ),
            ]
        )

        self.assertEqual(
            self.repository.count_products(ProductFilter(source="sewitnow")),
            1,
        )


if __name__ == "__main__":
    unittest.main()
