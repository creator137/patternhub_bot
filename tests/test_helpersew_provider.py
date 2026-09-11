from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.database import Database
from app.models.categories import normalize_category
from app.models.product import ParsedProduct, ProductFilter
from app.providers.helpersew import HelperSewProvider
from app.repositories.products import ProductRepository
from app.services.catalog import CatalogService


FIXTURES = Path(__file__).parent / "fixtures"


class HelperSewProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = HelperSewProvider()

    def test_parses_listing_into_shared_products(self) -> None:
        html = (FIXTURES / "helpersew_catalog.html").read_text(encoding="utf-8")

        products = self.provider.parse_catalog_page(
            html,
            "https://helpersew.com/catalog/zhenskie/platya-i-sarafany/",
            page_audience="women",
            page_category="Платья и сарафаны",
        )

        self.assertEqual(len(products), 4)
        first, sale, free, unisex = products
        self.assertEqual(first.source, "helpersew")
        self.assertEqual(first.source_product_id, "1034345")
        self.assertEqual(first.name, "Платье Флоранс")
        self.assertEqual(first.brand, "HelperSew")
        self.assertEqual(first.audience, "women")
        self.assertEqual(first.price, Decimal("329.00"))
        self.assertEqual(first.category, "Платья")
        self.assertTrue(first.is_new)
        self.assertFalse(first.is_sale)
        self.assertEqual(
            first.image_url,
            "https://helpersew.com/upload/resize_cache/iblock/f10/261_367_1/plate.jpg",
        )
        self.assertEqual(sale.price, Decimal("399.00"))
        self.assertEqual(sale.old_price, Decimal("499.00"))
        self.assertTrue(sale.is_sale)
        self.assertTrue(free.is_free)
        self.assertEqual(free.price, Decimal("0.00"))
        self.assertFalse(unisex.is_free)
        self.assertEqual(unisex.audience, "unisex")
        self.assertEqual(self.provider.last_skipped, 1)

    def test_parses_optional_detail_fields(self) -> None:
        html = (FIXTURES / "helpersew_product.html").read_text(encoding="utf-8")

        product = self.provider.parse_product_page(
            html,
            "https://helpersew.com/catalog/zhenskie/platya-i-sarafany/plate-florans/",
        )

        self.assertEqual(product.price, Decimal("329.00"))
        self.assertEqual(product.sizes, ("40–54",))
        self.assertEqual(product.heights, ("149-184",))
        self.assertEqual(product.difficulty, "Уровень сложности: Средний")
        self.assertTrue(product.is_new)

    def test_helpersew_men_and_kids_keep_product_category(self) -> None:
        men = ParsedProduct(
            source="helpersew",
            name="Брюки мужские",
            brand="HelperSew",
            audience=self.provider._audience_from_url(
                "https://helpersew.com/catalog/muzhskie/bryukimen/bryuki/"
            ),
            category=self.provider._category_from_url(
                "https://helpersew.com/catalog/muzhskie/bryukimen/bryuki/"
            ),
            product_url="https://helpersew.com/catalog/muzhskie/bryukimen/bryuki/",
        ).normalized()
        kids = ParsedProduct(
            source="helpersew",
            name="Платье детское",
            brand="HelperSew",
            audience=self.provider._audience_from_url(
                "https://helpersew.com/catalog/detskie/platya-i-sarafanydeti/plate/"
            ),
            category=self.provider._category_from_url(
                "https://helpersew.com/catalog/detskie/platya-i-sarafanydeti/plate/"
            ),
            product_url="https://helpersew.com/catalog/detskie/platya-i-sarafanydeti/plate/",
        ).normalized()

        self.assertEqual((men.audience, men.category), ("men", "Брюки и шорты"))
        self.assertEqual((kids.audience, kids.category), ("kids", "Платья"))

    def test_price_parser(self) -> None:
        self.assertEqual(self.provider._decimal("1 200 ₽"), Decimal("1200"))
        self.assertEqual(self.provider._decimal("329,50 ₽"), Decimal("329.50"))

    def test_category_normalization(self) -> None:
        self.assertEqual(normalize_category("Платья и сарафаны"), "Платья")
        self.assertEqual(normalize_category("Рубашки и блузы"), "Рубашки, блузки и топы")

    def test_filters_obvious_non_patterns(self) -> None:
        product = ParsedProduct(
            source="helpersew",
            source_product_id="gift",
            name="Подарочная карта",
            brand="HelperSew",
            category="Подарочная карта",
            product_url="https://helpersew.com/catalog/gift-card/",
        ).normalized()

        self.assertTrue(self.provider._should_skip_product(product))


class HelperSewRepositoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
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
            source="helpersew",
            source_product_id="1034345",
            name="Платье Тест",
            brand="HelperSew",
            category="Платья",
            price=Decimal("329"),
            currency="RUB",
            is_new=True,
            product_url="https://helpersew.com/catalog/zhenskie/plate-test/",
        )

        self.assertEqual(self.repository.upsert_many([product]), (1, 0))
        self.assertEqual(self.repository.upsert_many([product]), (0, 1))
        self.assertEqual(self.repository.count_products(ProductFilter(source="helpersew")), 1)

    async def test_same_names_from_three_sources_do_not_conflict(self) -> None:
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
            )
        ]

        self.repository.upsert_many(products)

        self.assertEqual(self.repository.count_products(), 3)

    async def test_catalog_service_returns_three_sources_and_flags(self) -> None:
        self.repository.upsert_many(
            [
                ParsedProduct(
                    source="vikisews",
                    source_product_id="1",
                    name="Платье V",
                    brand="VikiSews",
                    category="Платья",
                    product_url="https://vikisews.com/vykrojki/1/",
                ),
                ParsedProduct(
                    source="grasser",
                    source_product_id="2",
                    name="Платье G",
                    brand="Grasser",
                    category="Платья и сарафаны",
                    price=Decimal("196"),
                    old_price=Decimal("280"),
                    product_url="https://grasser.ru/vykrojki/2/",
                ),
                ParsedProduct(
                    source="helpersew",
                    source_product_id="3",
                    name="Платье H",
                    brand="HelperSew",
                    category="Платья и сарафаны",
                    is_new=True,
                    product_url="https://helpersew.com/catalog/3/",
                ),
            ]
        )

        products = await self.service.get_products(filters=ProductFilter(category="Платья"))
        sale = await self.service.get_products(filters=ProductFilter(is_sale=True))
        new = await self.service.get_products(filters=ProductFilter(is_new=True))

        self.assertEqual({product.source for product in products}, {"vikisews", "grasser", "helpersew"})
        self.assertEqual([product.source for product in sale], ["grasser"])
        self.assertEqual([product.source for product in new], ["helpersew"])


if __name__ == "__main__":
    unittest.main()
