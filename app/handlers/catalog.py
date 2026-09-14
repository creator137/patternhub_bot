from __future__ import annotations

import asyncio
import html
import logging
import re
from decimal import Decimal
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.models.product import CatalogCategory, Product, ProductFilter
from app.services.catalog import (
    BRANDS_SECTION,
    FREE_SECTION,
    KIDS_SECTION,
    MEN_SECTION,
    NEW_SECTION,
    SALE_SECTION,
    SOURCE_SECTION_PREFIX,
    UNISEX_SECTION,
    WOMEN_SECTION,
    CatalogService,
)


logger = logging.getLogger(__name__)

HOME_TEXT = "🏠 Главное меню"
DETAILS_DESCRIPTION_LIMIT = 420
IMAGE_DOWNLOAD_TIMEOUT = 15.0
MAX_IMAGE_DOWNLOAD_BYTES = 10 * 1024 * 1024
TELEGRAM_SEND_RETRIES = 3
FILTER_ALL = "all"
FILTER_BEGINNER = "beg"
FILTER_KNIT = "knit"
AUDIENCE_SECTIONS = {WOMEN_SECTION, MEN_SECTION, KIDS_SECTION}
QUICK_FILTER_TITLES = {
    FILTER_ALL: "Все",
    FILTER_BEGINNER: "Для начинающих",
    FILTER_KNIT: "Из трикотажа",
}
SECTION_BY_TEXT = {
    "👗 Женские": WOMEN_SECTION,
    "👔 Мужские": MEN_SECTION,
    "🧒 Детские": KIDS_SECTION,
    "🏷 Все бренды": BRANDS_SECTION,
    "🔥 Скидки": SALE_SECTION,
    "🆓 Бесплатные": FREE_SECTION,
    "🆕 Новинки": NEW_SECTION,
}
SECTION_TITLES = {value: key for key, value in SECTION_BY_TEXT.items()}
ACTIVE_PRODUCT_CALLBACKS: set[tuple[object, ...]] = set()
ACTIVE_PRODUCT_CALLBACKS_LOCK = asyncio.Lock()


class SectionCallback(CallbackData, prefix="sec"):
    section: str


class CategoryCallback(CallbackData, prefix="cat"):
    section: str
    category: str
    quick_filter: str = FILTER_ALL


class ProductCallback(CallbackData, prefix="prd"):
    action: str
    section: str
    category: str
    index: int
    quick_filter: str = FILTER_ALL


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
        if section.code in AUDIENCE_SECTIONS and section.available
    ]
    visible_titles.extend(["🏷 Все бренды", "🔥 Скидки", "🆓 Бесплатные", "🆕 Новинки"])
    await send_message_with_retry(
        message,
        "Каталог выкроек\n\nВыберите раздел:",
        reply_markup=create_main_keyboard(visible_titles),
    )


async def show_section(
    message: Message,
    catalog_service: CatalogService,
    section: str,
    quick_filter: str = FILTER_ALL,
) -> None:
    if section == BRANDS_SECTION:
        await show_brands(message, catalog_service)
        return

    filters = section_filters(section, quick_filter)
    categories = await catalog_service.get_categories(filters=filters)
    title = await section_title(catalog_service, section)
    filter_title = (
        f"\nФильтр: {QUICK_FILTER_TITLES[quick_filter]}"
        if section in AUDIENCE_SECTIONS and quick_filter != FILTER_ALL
        else ""
    )
    quick_counts = await quick_filter_counts(catalog_service, section)
    text = (
        f"{title}{filter_title}\n\nВыберите категорию:"
        if categories
        else f"{title}{filter_title}\n\nСейчас товаров в этом фильтре нет."
    )
    await send_message_with_retry(
        message,
        text,
        reply_markup=categories_keyboard(section, categories, quick_filter, quick_counts),
    )


async def show_brands(message: Message, catalog_service: CatalogService) -> None:
    brands = await catalog_service.get_brands()
    if not brands:
        await send_message_with_retry(message, "Сейчас товаров в этом разделе нет.")
        return
    await send_message_with_retry(
        message,
        "Все бренды\n\nВыберите бренд:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{brand.name} ({brand.products})",
                        callback_data=SectionCallback(
                            section=f"{SOURCE_SECTION_PREFIX}{brand.source}"
                        ).pack(),
                    )
                ]
                for brand in brands
            ]
            + [[InlineKeyboardButton(text="Назад", callback_data=SectionCallback(section="home").pack())]]
        ),
    )


def categories_keyboard(
    section: str,
    categories: list[CatalogCategory],
    quick_filter: str = FILTER_ALL,
    quick_counts: dict[str, int] | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if section in AUDIENCE_SECTIONS:
        rows.extend(
            [
                InlineKeyboardButton(
                    text=quick_filter_button_text(code, title, quick_filter, quick_counts),
                    callback_data=SectionFilterCallback(
                        section=section,
                        quick_filter=code,
                    ).pack(),
                )
            ]
            for code, title in QUICK_FILTER_TITLES.items()
        )
    rows.extend(
        [
            InlineKeyboardButton(
                text=f"{category.name} ({category.products})",
                callback_data=CategoryCallback(
                    section=section,
                    category=category.code,
                    quick_filter=quick_filter,
                ).pack(),
            )
        ]
        for category in categories
    )
    rows.append([InlineKeyboardButton(text="Назад", callback_data=SectionCallback(section="home").pack())])
    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


async def quick_filter_counts(
    catalog_service: CatalogService,
    section: str,
) -> dict[str, int]:
    if section not in AUDIENCE_SECTIONS:
        return {}
    return {
        code: await catalog_service.count_products(section_filters(section, code))
        for code in QUICK_FILTER_TITLES
    }


def quick_filter_button_text(
    code: str,
    title: str,
    selected: str,
    counts: dict[str, int] | None = None,
) -> str:
    prefix = "✓ " if selected == code else ""
    suffix = f" ({counts[code]})" if counts and code in counts else ""
    return f"{prefix}{title}{suffix}"


class SectionFilterCallback(CallbackData, prefix="flt"):
    section: str
    quick_filter: str = FILTER_ALL


async def show_category_callback(
    callback: CallbackQuery,
    catalog_service: CatalogService,
    callback_data: CategoryCallback,
) -> None:
    await safe_callback_answer(callback)
    await send_product_card(
        callback.message,
        catalog_service,
        callback_data.section,
        callback_data.category,
        0,
        quick_filter=callback_data.quick_filter,
    )


async def handle_product_callback(
    callback: CallbackQuery,
    catalog_service: CatalogService,
    callback_data: ProductCallback,
) -> None:
    busy_key = product_callback_busy_key(callback, callback_data)
    if callback_data.action in {"next", "prev"}:
        async with ACTIVE_PRODUCT_CALLBACKS_LOCK:
            if busy_key in ACTIVE_PRODUCT_CALLBACKS:
                await safe_callback_answer(callback, "Загружаю карточку...")
                return
            ACTIVE_PRODUCT_CALLBACKS.add(busy_key)
        try:
            await handle_product_callback_once(callback, catalog_service, callback_data)
        finally:
            async with ACTIVE_PRODUCT_CALLBACKS_LOCK:
                ACTIVE_PRODUCT_CALLBACKS.discard(busy_key)
        return

    await handle_product_callback_once(callback, catalog_service, callback_data)


async def handle_product_callback_once(
    callback: CallbackQuery,
    catalog_service: CatalogService,
    callback_data: ProductCallback,
) -> None:
    if callback_data.action == "back":
        await safe_callback_answer(callback)
        filters = section_filters(callback_data.section, callback_data.quick_filter)
        categories = await catalog_service.get_categories(filters=filters)
        if callback.message:
            await send_message_with_retry(
                callback.message,
                "Выберите категорию:",
                reply_markup=categories_keyboard(
                    callback_data.section,
                    categories,
                    callback_data.quick_filter,
                ),
            )
        return

    section_filter = section_filters(callback_data.section, callback_data.quick_filter)
    category = await catalog_service.get_category_by_code(
        callback_data.category,
        filters=section_filter,
    )
    if category is None:
        await safe_callback_answer(callback, "Категория больше недоступна.", show_alert=True)
        return

    filters = product_filters(
        callback_data.section,
        category.name,
        callback_data.quick_filter,
    )
    total = await catalog_service.count_products(filters)
    if total == 0:
        await safe_callback_answer(callback, "Сейчас товаров в этом разделе нет.", show_alert=True)
        return

    if callback_data.action == "details":
        product = await product_at(catalog_service, filters, callback_data.index)
        if product is None:
            await safe_callback_answer(callback, "Товар больше недоступен.", show_alert=True)
            return
        await safe_callback_answer(callback)
        if callback.message:
            await send_message_with_retry(
                callback.message,
                format_product_details(product),
                parse_mode="HTML",
            )
        return

    next_index = callback_data.index
    if callback_data.action == "next":
        next_index = (callback_data.index + 1) % total
    elif callback_data.action == "prev":
        next_index = (callback_data.index - 1) % total

    await safe_callback_answer(callback)
    if callback.message:
        await send_product_card(
            callback.message,
            catalog_service,
            callback_data.section,
            callback_data.category,
            next_index,
            quick_filter=callback_data.quick_filter,
        )


def product_callback_busy_key(
    callback: CallbackQuery,
    callback_data: ProductCallback,
) -> tuple[object, ...]:
    user_id = getattr(getattr(callback, "from_user", None), "id", None)
    message = getattr(callback, "message", None)
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    message_id = getattr(message, "message_id", None)
    if user_id is None:
        user_id = "unknown-user"
    if chat_id is None:
        chat_id = id(message)
    return (
        user_id,
        chat_id,
        message_id,
        callback_data.section,
        callback_data.category,
        callback_data.quick_filter,
    )


async def send_product_card(
    message: Message | None,
    catalog_service: CatalogService,
    section: str,
    category_code: str,
    index: int,
    *,
    replace: bool = False,
    quick_filter: str = FILTER_ALL,
) -> None:
    if message is None:
        return
    section_filter = section_filters(section, quick_filter)
    category = await catalog_service.get_category_by_code(
        category_code,
        filters=section_filter,
    )
    if category is None:
        await send_message_with_retry(message, "Категория больше недоступна.")
        return

    filters = product_filters(section, category.name, quick_filter)
    total = await catalog_service.count_products(filters)
    if total == 0:
        await send_message_with_retry(message, "Сейчас товаров в этом разделе нет.")
        return

    safe_index = index % total
    product = await product_at(catalog_service, filters, safe_index)
    if product is None:
        await send_message_with_retry(message, "Сейчас товаров в этом разделе нет.")
        return

    if replace:
        try:
            await message.delete()
        except TelegramAPIError:
            logger.debug("Could not delete previous catalog message", exc_info=True)

    text = format_product_card(product)
    keyboard = product_keyboard(
        section,
        category_code,
        safe_index,
        total,
        product.product_url,
        quick_filter,
    )
    if product.telegram_file_id:
        try:
            sent_message = await send_photo_with_retry(
                message,
                photo=product.telegram_file_id,
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            await remember_photo_file_id(catalog_service, product.id, sent_message)
            return
        except TelegramAPIError:
            logger.info(
                "Telegram could not send product image by file_id: product_id=%s",
                product.id,
            )

    if product.image_url:
        try:
            sent_message = await send_photo_with_retry(
                message,
                photo=telegram_photo_url(product.image_url),
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            await remember_photo_file_id(catalog_service, product.id, sent_message)
            return
        except TelegramAPIError:
            logger.info(
                "Telegram could not send product image by URL: product_id=%s",
                product.id,
            )

        photo_file = await download_product_photo(product.image_url, product.id)
        if photo_file is not None:
            try:
                sent_message = await send_photo_with_retry(
                    message,
                    photo=photo_file,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
                await remember_photo_file_id(catalog_service, product.id, sent_message)
                return
            except TelegramAPIError:
                logger.info(
                    "Telegram could not send downloaded product image: product_id=%s",
                    product.id,
                )

        await catalog_service.save_product_image_status(product.id, "failed")

    await send_message_with_retry(message, text, parse_mode="HTML", reply_markup=keyboard)


async def product_at(
    catalog_service: CatalogService, filters: ProductFilter, index: int
) -> Product | None:
    products = await catalog_service.get_products(limit=1, offset=index, filters=filters)
    return products[0] if products else None


async def safe_callback_answer(
    callback: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool | None = None,
) -> None:
    try:
        if text is None and show_alert is None:
            await callback.answer()
        elif show_alert is None:
            await callback.answer(text)
        else:
            await callback.answer(text, show_alert=show_alert)
    except TelegramAPIError:
        logger.debug("Could not answer Telegram callback", exc_info=True)


async def send_message_with_retry(
    message: Message,
    *args: object,
    **kwargs: object,
) -> Message | None:
    return await telegram_call_with_retry(message.answer, *args, **kwargs)


async def send_photo_with_retry(
    message: Message,
    *args: object,
    **kwargs: object,
) -> Message | None:
    return await telegram_call_with_retry(message.answer_photo, *args, **kwargs)


async def telegram_call_with_retry(method, *args: object, **kwargs: object) -> Message | None:
    for attempt in range(1, TELEGRAM_SEND_RETRIES + 1):
        try:
            return await method(*args, **kwargs)
        except TelegramNetworkError:
            if attempt >= TELEGRAM_SEND_RETRIES:
                logger.warning(
                    "Telegram send failed after %d attempts",
                    TELEGRAM_SEND_RETRIES,
                    exc_info=True,
                )
                return None
            await asyncio.sleep(0.3 * attempt)
    return None


def section_filters(section: str, quick_filter: str = FILTER_ALL) -> ProductFilter:
    source = source_from_section(section)
    filters = ProductFilter(
        source=source,
        audience=section_audience(section),
        is_sale=True if section == SALE_SECTION else None,
        is_free=True if section == FREE_SECTION else None,
        is_new=True if section == NEW_SECTION else None,
        is_beginner=True if quick_filter == FILTER_BEGINNER else None,
        is_knit=True if quick_filter == FILTER_KNIT else None,
    )
    return filters


def product_filters(
    section: str,
    category: str,
    quick_filter: str = FILTER_ALL,
) -> ProductFilter:
    filters = section_filters(section, quick_filter)
    return ProductFilter(
        source=filters.source,
        audience=filters.audience,
        category=category,
        is_sale=filters.is_sale,
        is_free=filters.is_free,
        is_new=filters.is_new,
        is_beginner=filters.is_beginner,
        is_knit=filters.is_knit,
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


def source_from_section(section: str) -> str | None:
    if section.startswith(SOURCE_SECTION_PREFIX):
        return section.removeprefix(SOURCE_SECTION_PREFIX)
    return None


async def section_title(catalog_service: CatalogService, section: str) -> str:
    if section.startswith(SOURCE_SECTION_PREFIX):
        source = section.removeprefix(SOURCE_SECTION_PREFIX)
        for brand in await catalog_service.get_brands():
            if brand.source == source:
                return brand.name
        return source
    return SECTION_TITLES.get(section, "Каталог")


def product_keyboard(
    section: str,
    category_code: str,
    index: int,
    total: int,
    product_url: str,
    quick_filter: str = FILTER_ALL,
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
                        quick_filter=quick_filter,
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
                        quick_filter=quick_filter,
                    ).pack(),
                ),
            ],
            [
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
                        quick_filter=quick_filter,
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


async def download_product_photo(
    image_url: str,
    product_id: int | None = None,
) -> BufferedInputFile | None:
    url = telegram_photo_url(image_url)
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=IMAGE_DOWNLOAD_TIMEOUT,
            trust_env=False,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPError:
        logger.info("Could not download product image: product_id=%s", product_id)
        return None

    content = response.content
    if not content or len(content) > MAX_IMAGE_DOWNLOAD_BYTES:
        logger.info(
            "Downloaded product image has unsupported size: product_id=%s size=%s",
            product_id,
            len(content),
        )
        return None

    content_type = response.headers.get("content-type", "").lower()
    if "image" not in content_type and content_type != "application/octet-stream":
        logger.info(
            "Downloaded product image has unsupported content type: product_id=%s type=%s",
            product_id,
            content_type,
        )
        return None

    filename = urlsplit(url).path.rsplit("/", 1)[-1] or "product-image.jpg"
    if "." not in filename:
        filename = f"{filename}.jpg"
    return BufferedInputFile(content, filename=filename)


async def remember_photo_file_id(
    catalog_service: CatalogService,
    product_id: int,
    sent_message: Message | None,
) -> None:
    file_id = product_photo_file_id(sent_message)
    if file_id:
        await catalog_service.save_product_photo_file_id(product_id, file_id)


def product_photo_file_id(sent_message: Message | None) -> str | None:
    photos = getattr(sent_message, "photo", None)
    if not isinstance(photos, (list, tuple)) or not photos:
        return None
    photo = max(photos, key=lambda item: item.file_size or 0)
    return photo.file_id


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
        await safe_callback_answer(callback)
        if callback.message:
            await show_main_menu(callback.message, catalog_service)

    @router.callback_query(SectionCallback.filter())
    async def bound_section_callback(
        callback: CallbackQuery, callback_data: SectionCallback
    ) -> None:
        await safe_callback_answer(callback)
        if callback.message:
            await show_section(callback.message, catalog_service, callback_data.section)

    @router.callback_query(SectionFilterCallback.filter())
    async def bound_section_filter(
        callback: CallbackQuery, callback_data: SectionFilterCallback
    ) -> None:
        await safe_callback_answer(callback)
        if callback.message:
            await show_section(
                callback.message,
                catalog_service,
                callback_data.section,
                callback_data.quick_filter,
            )

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
        await safe_callback_answer(callback)

    return router
