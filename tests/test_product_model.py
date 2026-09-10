from __future__ import annotations

import unittest
from decimal import Decimal

from app.models.product import ParsedProduct


class ParsedProductTests(unittest.TestCase):
    def test_normalizes_shared_catalog_fields(self) -> None:
        product = ParsedProduct(
            source=" VIKIsews ",
            source_product_id=" 42 ",
            name="  Платье   Глория ",
            product_url="HTTPS://VIKISEWS.COM//vykrojki/item/#details",
            price=Decimal("100"),
            old_price=Decimal("200"),
            currency=" rub ",
            sizes=(" 42 ", "42", " 44"),
        ).normalized()

        self.assertEqual(product.source, "vikisews")
        self.assertEqual(product.name, "Платье Глория")
        self.assertEqual(product.product_url, "https://vikisews.com/vykrojki/item/")
        self.assertEqual(product.price, Decimal("100.00"))
        self.assertEqual(product.currency, "RUB")
        self.assertEqual(product.sizes, ("42", "44"))
        self.assertTrue(product.is_sale)

    def test_zero_price_is_normalized_as_free(self) -> None:
        product = ParsedProduct(
            source="grasser",
            name="Free pattern",
            product_url="https://grasser.ru/item/1",
            price=Decimal("0"),
        ).normalized()

        self.assertTrue(product.is_free)


if __name__ == "__main__":
    unittest.main()
