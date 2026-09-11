from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.database import Database
from app.handlers.catalog import (
    CategoryCallback,
    ProductCallback,
    compact_range,
    format_product_details,
    format_product_card,
    handle_product_callback,
    product_filters,
    send_product_card,
    telegram_photo_url,
)
from app.models.product import ParsedProduct, ProductFilter
from app.repositories.products import ProductRepository
from app.services.catalog import CatalogService


def product(
    name: str,
    category: str,
    *,
    source_product_id: str,
    price: str | None = "280",
    image_url: str | None = "https://example.com/item.jpg",
    is_new: bool = False,
    audience: str | None = "women",
) -> ParsedProduct:
    return ParsedProduct(
        source="vikisews",
        source_product_id=source_product_id,
        name=name,
        brand="VikiSews",
        audience=audience,
        category=category,
        price=Decimal(price) if price is not None else None,
        currency="RUB",
        sizes=("38", "54"),
        heights=("162-168", "170-176"),
        is_new=is_new,
        product_url=f"https://vikisews.com/vykrojki/{source_product_id}/",
        image_url=image_url,
    )


class CatalogHandlerTests(unittest.IsolatedAsyncioTestCase):
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
                product("Клара платье", "Платья", source_product_id="3", image_url=None),
                product(
                    "Мужская рубашка",
                    "Рубашки, блузки и топы",
                    source_product_id="4",
                    audience="men",
                ),
                product(
                    "Детские брюки",
                    "Брюки и шорты",
                    source_product_id="5",
                    audience="kids",
                ),
            ]
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    async def test_callback_parsing(self) -> None:
        packed = ProductCallback(
            action="next", section="women", category="c123", index=7
        ).pack()

        parsed = ProductCallback.unpack(packed)

        self.assertEqual(parsed.action, "next")
        self.assertEqual(parsed.section, "women")
        self.assertEqual(parsed.category, "c123")
        self.assertEqual(parsed.index, 7)

    async def test_pagination_sends_single_product_card(self) -> None:
        category = (await self.service.get_categories(section="women"))[0]
        message = SimpleNamespace(
            answer_photo=AsyncMock(),
            answer=AsyncMock(),
            delete=AsyncMock(),
        )

        await send_product_card(message, self.service, "women", category.code, 0)

        message.answer_photo.assert_awaited_once()
        self.assertIn("1 / 3", str(message.answer_photo.await_args.kwargs["reply_markup"]))

    async def test_switch_next_wraps_at_end(self) -> None:
        category = (await self.service.get_categories(section="women"))[0]
        message = SimpleNamespace(
            answer_photo=AsyncMock(),
            answer=AsyncMock(),
            delete=AsyncMock(),
        )
        callback = SimpleNamespace(message=message, answer=AsyncMock())
        data = ProductCallback(
            action="next", section="women", category=category.code, index=2
        )

        await handle_product_callback(callback, self.service, data)

        callback.answer.assert_awaited_once()
        self.assertIn("1 / 3", str(message.answer_photo.await_args.kwargs["reply_markup"]))

    async def test_switch_prev_wraps_to_end(self) -> None:
        category = (await self.service.get_categories(section="women"))[0]
        message = SimpleNamespace(
            answer_photo=AsyncMock(),
            answer=AsyncMock(),
            delete=AsyncMock(),
        )
        callback = SimpleNamespace(message=message, answer=AsyncMock())
        data = ProductCallback(
            action="prev", section="women", category=category.code, index=0
        )

        await handle_product_callback(callback, self.service, data)

        self.assertIn("3 / 3", str(message.answer.await_args.kwargs["reply_markup"]))

    async def test_product_without_image_uses_text_message(self) -> None:
        category = (await self.service.get_categories(section="women"))[0]
        message = SimpleNamespace(
            answer_photo=AsyncMock(),
            answer=AsyncMock(),
            delete=AsyncMock(),
        )

        await send_product_card(message, self.service, "women", category.code, 2)

        message.answer_photo.assert_not_awaited()
        message.answer.assert_awaited_once()

    async def test_product_without_price_has_consistent_text(self) -> None:
        products = await self.service.get_products(
            limit=1,
            offset=1,
            filters=ProductFilter(category="Платья"),
        )

        text = format_product_card(products[0])

        self.assertIn("💰 Цена не указана", text)

    def test_compact_range(self) -> None:
        self.assertEqual(compact_range(("162-168", "170-176")), "162–176")

    def test_telegram_photo_url_encodes_cyrillic_path(self) -> None:
        url = (
            "https://studio-yusupova.ru/wp-content/uploads/2026/05/"
            "Заглавные-фотографии.jpg"
        )

        encoded = telegram_photo_url(url)

        self.assertEqual(
            encoded,
            "https://studio-yusupova.ru/wp-content/uploads/2026/05/"
            "%D0%97%D0%B0%D0%B3%D0%BB%D0%B0%D0%B2%D0%BD%D1%8B%D0%B5-"
            "%D1%84%D0%BE%D1%82%D0%BE%D0%B3%D1%80%D0%B0%D1%84%D0%B8%D0%B8.jpg",
        )

    def test_product_filters_for_sale_section(self) -> None:
        self.assertTrue(product_filters("sale", "Платья").is_sale)

    def test_product_filters_for_new_section(self) -> None:
        self.assertTrue(product_filters("new", "Платья").is_new)

    async def test_product_card_shows_new_badge(self) -> None:
        self.repository.upsert_many(
            [product("Новая выкройка", "Юбки", source_product_id="new", is_new=True)]
        )
        saved = await self.service.get_products(filters=ProductFilter(category="Юбки"))

        text = format_product_card(saved[0])

        self.assertIn("🆕 Новинка", text)

    async def test_product_details_truncates_long_description(self) -> None:
        self.repository.upsert_many(
            [
                ParsedProduct(
                    source="studio_yusupova",
                    source_product_id="details",
                    name="Баска Дора Н",
                    brand="Studio Yusupova",
                    audience="women",
                    category="Аксессуары",
                    price=Decimal("270"),
                    currency="RUB",
                    sizes=("40", "54"),
                    heights=("156", "178"),
                    description=" ".join(["Описание модели"] * 80),
                    product_url="https://studio-yusupova.ru/shop/dora/",
                )
            ]
        )
        saved = await self.service.get_products(
            filters=ProductFilter(source="studio_yusupova")
        )

        text = format_product_details(saved[0])

        self.assertLess(len(text), 700)
        self.assertIn("<b>Описание</b>", text)
        self.assertTrue(text.endswith("…"))

    async def test_men_section_uses_audience_filter(self) -> None:
        categories = await self.service.get_categories(section="men")

        self.assertEqual([(category.name, category.products) for category in categories], [("Рубашки, блузки и топы", 1)])

    async def test_kids_section_uses_audience_filter(self) -> None:
        categories = await self.service.get_categories(section="kids")

        self.assertEqual([(category.name, category.products) for category in categories], [("Брюки и шорты", 1)])


if __name__ == "__main__":
    unittest.main()
