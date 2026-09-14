from __future__ import annotations

import asyncio
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from app.database import Database
from app.handlers.catalog import (
    CategoryCallback,
    ProductCallback,
    SectionCallback,
    SectionFilterCallback,
    create_catalog_router,
    compact_range,
    format_product_details,
    format_product_card,
    handle_product_callback,
    product_keyboard,
    product_filters,
    product_photo_file_id,
    quick_filter_button_text,
    safe_callback_answer,
    send_product_card,
    send_message_with_retry,
    show_brands,
    show_main_menu,
    show_section,
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
    description: str | None = None,
    difficulty: str | None = None,
    subcategory: str | None = None,
) -> ParsedProduct:
    return ParsedProduct(
        source="vikisews",
        source_product_id=source_product_id,
        name=name,
        brand="VikiSews",
        audience=audience,
        category=category,
        subcategory=subcategory,
        price=Decimal(price) if price is not None else None,
        currency="RUB",
        sizes=("38", "54"),
        heights=("162-168", "170-176"),
        is_new=is_new,
        difficulty=difficulty,
        description=description,
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
                product(
                    "Лёгкая футболка",
                    "Худи, футболки и лонгсливы",
                    source_product_id="6",
                    audience="women",
                    difficulty="Для начинающих",
                    subcategory="Футболки из трикотажа",
                ),
                ParsedProduct(
                    source="grasser",
                    source_product_id="g1",
                    name="Платье бренда",
                    brand="Grasser",
                    audience="women",
                    category="Платья",
                    price=Decimal("500"),
                    currency="RUB",
                    product_url="https://grasser.ru/vykrojki/plate/",
                    image_url="https://example.com/grasser.jpg",
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
        self.assertEqual(parsed.quick_filter, "all")

    async def test_filter_callback_parsing(self) -> None:
        packed = SectionFilterCallback(section="women", quick_filter="knit").pack()

        parsed = SectionFilterCallback.unpack(packed)

        self.assertEqual(parsed.section, "women")
        self.assertEqual(parsed.quick_filter, "knit")

    async def test_pagination_sends_single_product_card(self) -> None:
        category = (await self.service.get_categories(section="women"))[0]
        message = SimpleNamespace(
            answer_photo=AsyncMock(),
            answer=AsyncMock(),
            delete=AsyncMock(),
        )

        await send_product_card(message, self.service, "women", category.code, 0)

        message.answer_photo.assert_awaited_once()
        self.assertIn("1 / 4", str(message.answer_photo.await_args.kwargs["reply_markup"]))

    async def test_switch_next_wraps_at_end(self) -> None:
        category = (await self.service.get_categories(section="women"))[0]
        message = SimpleNamespace(
            answer_photo=AsyncMock(),
            answer=AsyncMock(),
            delete=AsyncMock(),
        )
        callback = SimpleNamespace(message=message, answer=AsyncMock())
        data = ProductCallback(
            action="next", section="women", category=category.code, index=3
        )

        await handle_product_callback(callback, self.service, data)

        callback.answer.assert_awaited_once()
        message.delete.assert_not_called()
        self.assertIn("1 / 4", str(message.answer_photo.await_args.kwargs["reply_markup"]))

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

        message.delete.assert_not_called()
        self.assertIn("4 / 4", str(message.answer_photo.await_args.kwargs["reply_markup"]))

    async def test_repeated_next_click_is_ignored_while_card_is_loading(self) -> None:
        category = (await self.service.get_categories(section="women"))[0]
        message = SimpleNamespace(
            answer_photo=AsyncMock(),
            answer=AsyncMock(),
            delete=AsyncMock(),
            chat=SimpleNamespace(id=100),
            message_id=200,
        )
        first_callback = SimpleNamespace(
            message=message,
            answer=AsyncMock(),
            from_user=SimpleNamespace(id=300),
        )
        second_callback = SimpleNamespace(
            message=message,
            answer=AsyncMock(),
            from_user=SimpleNamespace(id=300),
        )
        data = ProductCallback(
            action="next", section="women", category=category.code, index=0
        )
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_send(*args, **kwargs):
            started.set()
            await release.wait()

        with patch("app.handlers.catalog.send_product_card", new=slow_send):
            first_task = asyncio.create_task(
                handle_product_callback(first_callback, self.service, data)
            )
            await started.wait()
            await handle_product_callback(second_callback, self.service, data)
            release.set()
            await first_task

        first_callback.answer.assert_awaited_once_with()
        second_callback.answer.assert_awaited_once_with("Загружаю карточку...")

    async def test_expired_callback_answer_does_not_crash_handler(self) -> None:
        callback = SimpleNamespace(
            answer=AsyncMock(
                side_effect=TelegramAPIError(
                    method=SimpleNamespace(),
                    message="query is too old and response timeout expired",
                )
            )
        )

        await safe_callback_answer(callback)

        callback.answer.assert_awaited_once_with()

    async def test_message_send_retries_after_network_error(self) -> None:
        sent = SimpleNamespace(message_id=1)
        message = SimpleNamespace(
            answer=AsyncMock(
                side_effect=[
                    TelegramNetworkError(
                        method=SimpleNamespace(),
                        message="connection reset by peer",
                    ),
                    sent,
                ]
            )
        )

        result = await send_message_with_retry(message, "Каталог")

        self.assertIs(result, sent)
        self.assertEqual(message.answer.await_count, 2)

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

    async def test_product_image_falls_back_to_downloaded_file(self) -> None:
        category = (await self.service.get_categories(section="women"))[0]
        error = TelegramAPIError(method=SimpleNamespace(), message="failed")
        sent_message = SimpleNamespace(
            photo=[
                SimpleNamespace(file_id="small-file", file_size=100),
                SimpleNamespace(file_id="large-file", file_size=200),
            ]
        )
        message = SimpleNamespace(
            answer_photo=AsyncMock(side_effect=[error, sent_message]),
            answer=AsyncMock(),
            delete=AsyncMock(),
        )
        photo_file = object()

        with patch(
            "app.handlers.catalog.download_product_photo",
            new=AsyncMock(return_value=photo_file),
        ) as download:
            await send_product_card(message, self.service, "women", category.code, 0)

        download.assert_awaited_once()
        self.assertEqual(message.answer_photo.await_count, 2)
        self.assertIs(message.answer_photo.await_args.kwargs["photo"], photo_file)
        message.answer.assert_not_awaited()
        saved = self.repository.get_product(1)
        self.assertEqual(saved.telegram_file_id, "large-file")

    async def test_product_image_falls_back_to_text_after_download_failure(self) -> None:
        category = (await self.service.get_categories(section="women"))[0]
        error = TelegramAPIError(method=SimpleNamespace(), message="failed")
        message = SimpleNamespace(
            answer_photo=AsyncMock(side_effect=error),
            answer=AsyncMock(),
            delete=AsyncMock(),
        )

        with patch(
            "app.handlers.catalog.download_product_photo",
            new=AsyncMock(return_value=None),
        ):
            await send_product_card(message, self.service, "women", category.code, 0)

        message.answer_photo.assert_awaited_once()
        message.answer.assert_awaited_once()
        saved = self.repository.get_product(1)
        self.assertEqual(saved.image_status, "failed")

    async def test_product_image_uses_cached_telegram_file_id_first(self) -> None:
        self.repository.set_photo_file_id(1, "cached-file-id")
        category = (await self.service.get_categories(section="women"))[0]
        message = SimpleNamespace(
            answer_photo=AsyncMock(return_value=SimpleNamespace(photo=[])),
            answer=AsyncMock(),
            delete=AsyncMock(),
        )

        with patch(
            "app.handlers.catalog.download_product_photo",
            new=AsyncMock(return_value=object()),
        ) as download:
            await send_product_card(message, self.service, "women", category.code, 0)

        message.answer_photo.assert_awaited_once()
        self.assertEqual(message.answer_photo.await_args.kwargs["photo"], "cached-file-id")
        download.assert_not_awaited()
        message.answer.assert_not_awaited()

    def test_product_photo_file_id_uses_largest_photo(self) -> None:
        sent_message = SimpleNamespace(
            photo=[
                SimpleNamespace(file_id="small", file_size=10),
                SimpleNamespace(file_id="large", file_size=99),
                SimpleNamespace(file_id="unknown", file_size=None),
            ]
        )

        self.assertEqual(product_photo_file_id(sent_message), "large")

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

    def test_product_filters_for_fast_filters(self) -> None:
        beginner = product_filters("women", "Платья", "beg")
        knit = product_filters("women", "Платья", "knit")

        self.assertTrue(beginner.is_beginner)
        self.assertTrue(knit.is_knit)

    def test_product_keyboard_has_no_details_button(self) -> None:
        keyboard = product_keyboard(
            "women",
            "c123",
            0,
            10,
            "https://example.com/product/",
        )

        self.assertNotIn("Подробнее", str(keyboard))
        self.assertIn("Открыть на сайте", str(keyboard))

    async def test_main_menu_replaces_unisex_with_all_brands(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())

        await show_main_menu(message, self.service)

        keyboard_text = str(message.answer.await_args.kwargs["reply_markup"])
        self.assertIn("🏷 Все бренды", keyboard_text)
        self.assertNotIn("👕 Унисекс", keyboard_text)

    async def test_show_brands_lists_sources(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())

        await show_brands(message, self.service)

        keyboard_text = str(message.answer.await_args.kwargs["reply_markup"])
        self.assertIn("VikiSews", keyboard_text)
        self.assertIn("Grasser", keyboard_text)

    async def test_women_section_shows_fast_filter_buttons(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())

        await show_section(message, self.service, "women")

        keyboard_text = str(message.answer.await_args.kwargs["reply_markup"])
        self.assertIn("Для начинающих (1)", keyboard_text)
        self.assertIn("Из трикотажа (1)", keyboard_text)

    async def test_knit_filter_limits_categories(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())

        await show_section(message, self.service, "women", "knit")

        text = str(message.answer.await_args.kwargs["reply_markup"])
        self.assertIn("Худи, футболки и лонгсливы", text)

    async def test_empty_fast_filter_keeps_navigation_buttons(self) -> None:
        message = SimpleNamespace(answer=AsyncMock())

        await show_section(message, self.service, "kids", "beg")

        text = message.answer.await_args.args[0]
        keyboard_text = str(message.answer.await_args.kwargs["reply_markup"])
        self.assertIn("Сейчас товаров в этом фильтре нет.", text)
        self.assertIn("✓ Для начинающих (0)", keyboard_text)
        self.assertIn("Все (1)", keyboard_text)
        self.assertIn("Назад", keyboard_text)

    async def test_empty_fast_filter_callback_shows_alert(self) -> None:
        router = create_catalog_router(self.service)
        handler = next(
            item
            for item in router.callback_query.handlers
            if getattr(item.callback, "__name__", "") == "bound_section_filter"
        )
        callback = SimpleNamespace(message=SimpleNamespace(answer=AsyncMock()), answer=AsyncMock())
        data = SectionFilterCallback(section="kids", quick_filter="beg")

        await handler.callback(callback, data)

        callback.answer.assert_awaited_once_with(
            "Пока нет товаров по этому фильтру.",
            show_alert=True,
        )
        callback.message.answer.assert_not_awaited()

    def test_quick_filter_button_text_shows_count(self) -> None:
        self.assertEqual(
            quick_filter_button_text("beg", "Для начинающих", "beg", {"beg": 7}),
            "✓ Для начинающих (7)",
        )

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
