from __future__ import annotations

import html
import logging
import re
from decimal import Decimal
from urllib.parse import quote, urlsplit, urlunsplit

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.models.product import CatalogCategory, Product, ProductFilter
from app.services.catalog import (
    FREE_SECTION,
    KIDS_SECTION,
    MEN_SECTION,
    NEW_SECTION,
    SALE_SECTION,
    UNISEX_SECTION,
    WOMEN_SECTION,
    CatalogService,
)


logger = logging.getLogger(__name__)

HOME_TEXT = "🏠 Главное меню"
DETAILS_DESCRIPTION_LIMIT = 420
SECTION_BY_TEXT = {
    "👗 Женские": WOMEN_SECTION,
    "👔 Мужские": MEN_SECTION,
    "🧒 Детские": KIDS_SECTION,
    "👕 Унисекс": UNISEX_SECTION,
    "🔥 Скидки": SALE_SECTION,
    "🆓 Бесплатные": FREE_SECTION,
    "🆕 Новинки": NEW_SECTION,
}
SECTION_TITLES = {value: key for key, value in SECTION_BY_TEXT.items()}


class SectionCallback(CallbackData, prefix="sec"):
    section: str


class CategoryCallback(CallbackData, prefix="cat"):
    section: str
    category: str


class ProductCallback(CallbackData, prefix="prd"):
    action: str
    section: str
    category: str
    index: int


def create_main_keyboard(sections: list[str] | None = None) -> ReplyKeyboardMarkup:
    section_titles = sections or list(SECTION_BY_TEXT)
    rows = [
        [KeyboardButton(text=title) for title in section_titles[index : index + 2]]
        for index in range(0, len(section_titles), 2)
    ]
    rows.append([KeyboardButton(text=HOME_TEXT)])
    return ReplyKeyboardMarkup(
        keyboard=[row for row in rows if row],
        resize_keyboard=True,
        input_field_placeholder="Выберите раздел",
    )


async def show_main_menu(message: Message, catalog_service: CatalogService) -> None:
    sections = await catalog_service.get_sections()
    visible_titles = [
        section.title
        for section in sections
        if section.code in {WOMEN_SECTION, MEN_SECTION, KIDS_SECTION, UNISEX_SECTION}
        and section.available
    ]
    visible_titles.extend(["🔥 Скидки", "🆓 Бесплатные", "🆕 Новинки"])
    await message.answer(
        "Каталог выкроек\n\nВыберите раздел:",
        reply_markup=create_main_keyboard(visible_titles),
    )


async def show_section(
    message: Message, catalog_service: CatalogService, section: str
) -> None:
    categories = await catalog_service.get_categories(section=section)
    if not categories:
        await message.answer("Сейчас товаров в этом разделе нет.")
        return

    title = SECTION_TITLES.get(section, "Каталог")
    await message.answer(
        f"{title}\n\nВыберите категорию:",
        reply_markup=categories_keyboard(section, categories),
    )


def categories_keyboard(
    section: str, categories: list[CatalogCategory]
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{category.name} ({category.products})",
                    callback_data=CategoryCallback(
                        section=section,
                        category=category.code,
                    ).pack(),
                )
            ]
            for category in categories
        ]
        + [[InlineKeyboardButton(text="Назад", callback_data=SectionCallback(section="home").pack())]]
    )


async def show_category_callback(
    callback: CallbackQuery,
    catalog_service: CatalogService,
    callback_data: CategoryCallback,
) -> None:
    await callback.answer()
    await send_product_card(
        callback.message,
        catalog_service,
        callback_data.section,
        callback_data.category,
        0,
        replace=True,
    )


async def handle_product_callback(
    callback: CallbackQuery,
    catalog_service: CatalogService,
    callback_data: ProductCallback,
) -> None:
    if callback_data.action == "back":
        await callback.answer()
        categories = await catalog_service.get_categories(section=callback_data.section)
        if callback.message:
            await callback.message.answer(
                "Выберите категорию:",
                reply_markup=categories_keyboard(callback_data.section, categories),
            )
        return

    category = await catalog_service.get_category_by_code(
        callback_data.category, section=callback_data.section
    )
    if category is None:
        await callback.answer("Категория больше недоступна.", show_alert=True)
        return

    filters = product_filters(callback_data.section, category.name)
    total = await catalog_service.count_products(filters)
    if total == 0:
        await callback.answer("Сейчас товаров в этом разделе нет.", show_alert=True)
        return

    if callback_data.action == "details":
        product = await product_at(catalog_service, filters, callback_data.index)
        if product is None:
            await callback.answer("Товар больше недоступен.", show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await callback.message.answer(format_product_details(product), parse_mode="HTML")
        return

    next_index = callback_data.index
    if callback_data.action == "next":
        next_index = (callback_data.index + 1) % total
    elif callback_data.action == "prev":
        next_index = (callback_data.index - 1) % total

    await callback.answer()
    if callback.message:
        await send_product_card(
            callback.message,
            catalog_service,
            callback_data.section,
            callback_data.category,
            next_index,
            replace=True,
        )


async def send_product_card(
    message: Message | None,
    catalog_service: CatalogService,
    section: str,
    category_code: str,
    index: int,
    *,
    replace: bool = False,
) -> None:
    if message is None:
        return
    category = await catalog_service.get_category_by_code(category_code, section=section)
    if category is None:
        await message.answer("Категория больше недоступна.")
        return

    filters = product_filters(section, category.name)
    total = await catalog_service.count_products(filters)
    if total == 0:
        await message.answer("Сейчас товаров в этом разделе нет.")
        return

    safe_index = index % total
    product = await product_at(catalog_service, filters, safe_index)
    if product is None:
        await message.answer("Сейчас товаров в этом разделе нет.")
        return

    if replace:
        try:
            await message.delete()
        except TelegramAPIError:
            logger.debug("Could not delete previous catalog message", exc_info=True)

    text = format_product_card(product)
    keyboard = product_keyboard(section, category_code, safe_index, total, product.product_url)
    if product.image_url:
        try:
            await message.answer_photo(
                photo=telegram_photo_url(product.image_url),
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            return
        except TelegramAPIError:
            logger.info("Telegram could not send product image: product_id=%s", product.id)

    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


async def product_at(
    catalog_service: CatalogService, filters: ProductFilter, index: int
) -> Product | None:
    products = await catalog_service.get_products(limit=1, offset=index, filters=filters)
    return products[0] if products else None


def product_filters(section: str, category: str) -> ProductFilter:
    return ProductFilter(
        audience=section_audience(section),
        category=category,
        is_sale=True if section == SALE_SECTION else None,
        is_free=True if section == FREE_SECTION else None,
        is_new=True if section == NEW_SECTION else None,
    )


def section_audience(section: str) -> str | None:
    if section == WOMEN_SECTION:
        return "women"
    if section == MEN_SECTION:
        return "men"
    if section == KIDS_SECTION:
        return "kids"
    if section == UNISEX_SECTION:
        return "unisex"
    return None


def product_keyboard(
    section: str, category_code: str, index: int, total: int, product_url: str
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="◀️",
                    callback_data=ProductCallback(
                        action="prev",
                        section=section,
                        category=category_code,
                        index=index,
                    ).pack(),
                ),
                InlineKeyboardButton(text=f"{index + 1} / {total}", callback_data="noop"),
                InlineKeyboardButton(
                    text="▶️",
                    callback_data=ProductCallback(
                        action="next",
                        section=section,
                        category=category_code,
                        index=index,
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Подробнее",
                    callback_data=ProductCallback(
                        action="details",
                        section=section,
                        category=category_code,
                        index=index,
                    ).pack(),
                ),
                InlineKeyboardButton(text="Открыть на сайте", url=product_url),
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data=ProductCallback(
                        action="back",
                        section=section,
                        category=category_code,
                        index=index,
                    ).pack(),
                )
            ],
        ]
    )


def format_product_card(product: Product) -> str:
    lines = [
        f"👗 <b>{html.escape(product.name)}</b>",
        html.escape(product.brand or product.source),
        "",
        format_price(product),
        f"📂 {html.escape(product.category)}" if product.category else None,
        format_values("📐 Размеры", product.sizes),
        format_values("📏 Рост", product.heights),
    ]
    if product.is_sale:
        lines.append("🔥 Скидка")
    if product.is_new:
        lines.append("🆕 Новинка")
    return "\n".join(line for line in lines if line)


def format_product_details(product: Product) -> str:
    description = short_description(product.description)
    lines = [
        f"<b>{html.escape(product.name)}</b>",
        f"Производитель: {html.escape(product.brand or product.source)}",
        f"Категория: {html.escape(product.category)}" if product.category else None,
        format_price(product),
        format_values("Размеры", product.sizes),
        format_values("Рост", product.heights),
        f"Сложность: {html.escape(product.difficulty)}" if product.difficulty else None,
        f"\n<b>Описание</b>\n{html.escape(description)}" if description else None,
    ]
    return "\n".join(line for line in lines if line)


def format_price(product: Product) -> str:
    if product.is_free:
        return "🆓 Бесплатно"
    if product.price is None:
        return "💰 Цена не указана"

    current = f"💰 {format_money(product.price, product.currency)}"
    if product.old_price is not None and product.old_price > product.price:
        return f"{current}\n<s>{format_money(product.old_price, product.currency)}</s>"
    return current


def format_money(value: Decimal, currency: str | None) -> str:
    formatted = f"{value:.0f}" if value == value.to_integral() else f"{value:.2f}"
    if currency == "RUB":
        return f"{formatted} ₽"
    return f"{formatted} {currency or ''}".strip()


def format_values(label: str, values: tuple[str, ...] | None) -> str | None:
    if not values:
        return None
    return f"{label}: {html.escape(compact_range(values))}"


def short_description(description: str | None) -> str | None:
    if not description:
        return None
    cleaned = re.sub(r"\s+", " ", description).strip()
    if not cleaned:
        return None
    if len(cleaned) <= DETAILS_DESCRIPTION_LIMIT:
        return cleaned
    preview = cleaned[:DETAILS_DESCRIPTION_LIMIT].rsplit(" ", 1)[0].rstrip(".,;: ")
    return f"{preview}…"


def telegram_photo_url(image_url: str) -> str:
    parts = urlsplit(image_url)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            quote(parts.path, safe="/%:@"),
            quote(parts.query, safe="=&%:@/?"),
            "",
        )
    )


def compact_range(values: tuple[str, ...]) -> str:
    numbers: list[int] = []
    for value in values:
        numbers.extend(int(match) for match in re.findall(r"\d+", value))
    if len(numbers) >= 2 and len(numbers) >= len(values):
        return f"{min(numbers)}–{max(numbers)}"
    return ", ".join(values)


def create_catalog_router(catalog_service: CatalogService) -> Router:
    router = Router(name=__name__)

    @router.message(F.text == HOME_TEXT)
    async def bound_home(message: Message) -> None:
        await show_main_menu(message, catalog_service)

    @router.message(F.text.in_(set(SECTION_BY_TEXT)))
    async def bound_section_message(message: Message) -> None:
        await show_section(message, catalog_service, SECTION_BY_TEXT[message.text])

    @router.callback_query(SectionCallback.filter(F.section == "home"))
    async def bound_home_callback(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.message:
            await show_main_menu(callback.message, catalog_service)

    @router.callback_query(CategoryCallback.filter())
    async def bound_category(
        callback: CallbackQuery, callback_data: CategoryCallback
    ) -> None:
        await show_category_callback(callback, catalog_service, callback_data)

    @router.callback_query(ProductCallback.filter())
    async def bound_product(callback: CallbackQuery, callback_data: ProductCallback) -> None:
        await handle_product_callback(callback, catalog_service, callback_data)

    @router.callback_query(F.data == "noop")
    async def bound_noop(callback: CallbackQuery) -> None:
        await callback.answer()

    return router
