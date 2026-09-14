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
        self.assertEqual(sale.audience, "women")
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

    def test_detail_materials_mark_knit_only_when_recommended(self) -> None:
        html = """
        <html><body>
          <script type="application/ld+json">
            {"@type": "Product", "name": "Гелла футболка", "offers": {"price": "300"}}
          </script>
          <div id="headingOne">
            <button class="accordion" data-target="#collapseOne">Рекомендуемые материалы</button>
          </div>
          <div id="collapseOne"><div class="panel">
            Для пошива футболки подойдут трикотажные полотна: кулирная гладь.
          </div></div>
        </body></html>
        """

        product = self.provider.parse_product_page(
            html,
            "https://vikisews.com/vykrojki/khudi-futbolki-longslivy/gella-futbolka/",
        )

        self.assertTrue(product.is_knit)

    def test_detail_materials_do_not_mark_negative_knit_mentions(self) -> None:
        html = """
        <html><body>
          <script type="application/ld+json">
            {"@type": "Product", "name": "Аглая платье", "offers": {"price": "300"}}
          </script>
          <div id="headingOne">
            <button class="accordion" data-target="#collapseOne">Рекомендуемые материалы</button>
          </div>
          <div id="collapseOne"><div class="panel">
            Для пошива подойдут нерастяжимые плательные ткани.
            Внимание! Не рекомендуются трикотажные полотна.
          </div></div>
        </body></html>
        """

        product = self.provider.parse_product_page(
            html,
            "https://vikisews.com/vykrojki/platja-i-sarafany/aglaja-plate/",
        )

        self.assertFalse(product.is_knit)

    def test_vikisews_men_and_kids_keep_product_category(self) -> None:
        men = ParsedProductLike(
            audience=self.provider._audience_from_url(
                "https://vikisews.com/vykrojki/muzhskie-vykrojki/muzhskie-brjuki/"
            ),
            category=self.provider._category_from_name("Мужские брюки"),
        ).product
        kids = ParsedProductLike(
            audience=self.provider._audience_from_url(
                "https://vikisews.com/vykrojki/detskie-vykrojki/detskoe-plate/"
            ),
            category=self.provider._category_from_name("Детское платье"),
        ).product

        self.assertEqual((men.audience, men.category), ("men", "Брюки и шорты"))
        self.assertEqual((kids.audience, kids.category), ("kids", "Платья"))


class ParsedProductLike:
    def __init__(self, *, audience: str | None, category: str | None) -> None:
        from app.models.product import ParsedProduct

        self.product = ParsedProduct(
            source="vikisews",
            name="Тест",
            brand="VikiSews",
            audience=audience,
            category=category,
            product_url="https://vikisews.com/vykrojki/test/",
        ).normalized()


if __name__ == "__main__":
    unittest.main()
