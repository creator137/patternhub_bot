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
) -> ParsedProduct:
    return ParsedProduct(
        source=source,
        source_product_id=source_product_id,
        name="Платье Тест",
        brand="VikiSews",
        product_url=url,
        price=Decimal(price),
        currency="RUB",
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


if __name__ == "__main__":
    unittest.main()
