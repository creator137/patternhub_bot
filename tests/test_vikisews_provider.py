from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from app.providers.vikisews import VikiSewsProvider


FIXTURES = Path(__file__).parent / "fixtures"


class VikiSewsProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = VikiSewsProvider(request_delay=0)

    def test_parses_catalog_html_into_shared_products(self) -> None:
        html = (FIXTURES / "vikisews_catalog.html").read_text(encoding="utf-8")

        products = self.provider.parse_catalog_page(html, self.provider.catalog_url)

        self.assertEqual(len(products), 2)
        self.assertTrue(self.provider.has_next_page(html))
        sale, free = products
        self.assertEqual(sale.source_product_id, "7153")
        self.assertEqual(sale.name, "Милетта жакет")
        self.assertEqual(sale.price, Decimal("220.00"))
        self.assertEqual(sale.old_price, Decimal("440.00"))
        self.assertEqual(sale.category, "Жакеты и жилеты")
        self.assertTrue(sale.is_sale)
        self.assertEqual(free.price, Decimal("0.00"))
        self.assertTrue(free.is_free)

    def test_parses_optional_detail_fields_from_json_ld_and_html(self) -> None:
        html = (FIXTURES / "vikisews_product.html").read_text(encoding="utf-8")

        product = self.provider.parse_product_page(
            html,
            "https://vikisews.com/vykrojki/platja-i-sarafany/plate-glorija/",
        )

        self.assertEqual(product.name, "Платье Глория")
        self.assertEqual(product.price, Decimal("280.00"))
        self.assertEqual(product.sizes, ("34", "36"))
        self.assertEqual(product.heights, ("154-160", "162-168"))
        self.assertEqual(product.difficulty, "Средний уровень")
        self.assertEqual(product.image_url, "https://cdn.example/gloria.jpg")


if __name__ == "__main__":
    unittest.main()
