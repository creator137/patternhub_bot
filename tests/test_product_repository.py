from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.database import Database
from app.models.product import ParsedProduct
from app.repositories.products import ProductRepository


def product(
    *,
    source: str = "vikisews",
    source_product_id: str | None = "100",
    url: str = "https://vikisews.com/vykrojki/category/item/",
    price: str = "280",
    audience: str | None = "women",
    category: str | None = None,
    subcategory: str | None = None,
    description: str | None = None,
    difficulty: str | None = None,
    brand: str = "VikiSews",
) -> ParsedProduct:
    return ParsedProduct(
        source=source,
        source_product_id=source_product_id,
        name="Платье Тест",
        brand=brand,
        audience=audience,
        category=category,
        subcategory=subcategory,
        product_url=url,
        price=Decimal(price),
        currency="RUB",
        description=description,
        difficulty=difficulty,
    )


class ProductRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp_directory.name) / "catalog.sqlite3")
        database.initialize()
        self.repository = ProductRepository(database)

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_creates_product(self) -> None:
        self.assertEqual(self.repository.upsert_many([product()]), (1, 0))
        saved = self.repository.list_products()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].price, Decimal("280.00"))

    def test_repeated_upsert_updates_without_duplicate(self) -> None:
        self.repository.upsert_many([product()])

        result = self.repository.upsert_many([product(price="199")])

        self.assertEqual(result, (0, 1))
        saved = self.repository.list_products()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].price, Decimal("199.00"))

    def test_saves_telegram_photo_cache_without_reimport(self) -> None:
        self.repository.upsert_many([product()])
        saved = self.repository.list_products()[0]

        self.repository.set_photo_file_id(saved.id, "telegram-file-id")
        cached = self.repository.get_product(saved.id)

        self.assertEqual(cached.telegram_file_id, "telegram-file-id")
        self.assertEqual(cached.image_status, "telegram_file_id")

    def test_reimport_keeps_telegram_photo_cache(self) -> None:
        self.repository.upsert_many([product()])
        saved = self.repository.list_products()[0]
        self.repository.set_photo_file_id(saved.id, "telegram-file-id")

        self.repository.upsert_many([product(price="199")])
        updated = self.repository.list_products()[0]

        self.assertEqual(updated.telegram_file_id, "telegram-file-id")

    def test_url_is_fallback_unique_key(self) -> None:
        first = product(source_product_id=None)
        second = product(source_product_id=None, price="150")

        self.repository.upsert_many([first])
        self.assertEqual(self.repository.upsert_many([second]), (0, 1))
        self.assertEqual(self.repository.stats().products, 1)

    def test_source_product_id_is_unique_only_inside_source(self) -> None:
        self.repository.upsert_many([product()])
        other_source = product(
            source="grasser",
            url="https://grasser.ru/vykrojki/item/",
        )

        self.assertEqual(self.repository.upsert_many([other_source]), (1, 0))
        self.assertEqual(self.repository.stats().products, 2)

    def test_filters_by_audience_and_category(self) -> None:
        self.repository.upsert_many(
            [
                product(source_product_id="1", audience="women", category="Платья"),
                product(
                    source_product_id="2",
                    audience="men",
                    category="Брюки и шорты",
                    url="https://vikisews.com/vykrojki/muzhskie/item/",
                ),
            ]
        )

        from app.models.product import ProductFilter

        saved = self.repository.list_products(filters=ProductFilter(audience="men"))

        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].audience, "men")

    def test_lists_brands(self) -> None:
        self.repository.upsert_many(
            [
                product(source_product_id="1", brand="VikiSews"),
                product(
                    source="grasser",
                    source_product_id="2",
                    brand="Grasser",
                    url="https://grasser.ru/vykrojki/item/",
                ),
            ]
        )

        brands = self.repository.list_brands()

        self.assertEqual(
            [(brand.source, brand.name, brand.products) for brand in brands],
            [("grasser", "Grasser", 1), ("vikisews", "VikiSews", 1)],
        )

    def test_filters_beginner_and_knit_products(self) -> None:
        self.repository.upsert_many(
            [
                product(
                    source_product_id="1",
                    category="Платья",
                    difficulty="Для начинающих",
                    description="Плотная ткань",
                ),
                product(
                    source_product_id="2",
                    category="Худи, футболки и лонгсливы",
                    description="Выкройка из трикотажа",
                    url="https://vikisews.com/vykrojki/knit/item/",
                ),
            ]
        )

        from app.models.product import ProductFilter

        beginner = self.repository.list_products(filters=ProductFilter(is_beginner=True))
        knit = self.repository.list_products(filters=ProductFilter(is_knit=True))

        self.assertEqual([item.source_product_id for item in beginner], ["1"])
        self.assertEqual([item.source_product_id for item in knit], ["2"])


if __name__ == "__main__":
    unittest.main()
