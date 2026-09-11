from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup

from app.models.categories import normalize_category
from app.models.product import ParsedProduct
from app.providers.base import BaseProvider, ProviderResult


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SewItNowCategoryContext:
    id: str
    name: str
    slug: str
    parent_name: str | None = None

    @property
    def is_special(self) -> bool:
        text = " ".join((self.name, self.parent_name or "")).casefold()
        return any(marker in text for marker in ("скид", "коллекц", "бесплат"))


class SewItNowProvider(BaseProvider):
    source = "sewitnow"
    base_url = "https://sewitnow.ru"
    brand = "SewItNow"

    _category_overrides = {
        "Блузы": "Рубашки, блузки и топы",
        "Боди": "Рубашки, блузки и топы",
        "Бомберы": "Верхняя одежда",
        "Брюки": "Брюки и шорты",
        "Брюки из трикотажа": "Брюки и шорты",
        "Верхняя одежда": "Верхняя одежда",
        "Джемперы": "Худи, футболки и лонгсливы",
        "Джинсы": "Брюки и шорты",
        "Жакеты": "Жакеты и жилеты",
        "Жилеты": "Жакеты и жилеты",
        "Кардиганы": "Худи, футболки и лонгсливы",
        "Комбинезоны": "Комбинезоны",
        "Куртки Весна/Лето": "Верхняя одежда",
        "Куртки Осень/Зима": "Верхняя одежда",
        "Легинсы": "Брюки и шорты",
        "Лифы": "Бельё и домашняя одежда",
        "Лонгсливы": "Худи, футболки и лонгсливы",
        "Пальто": "Верхняя одежда",
        "Платья": "Платья",
        "Платья Весна/Осень": "Платья",
        "Платья Лето": "Платья",
        "Платья из трикотажа": "Платья",
        "Платья нарядные": "Платья",
        "Прочее": "Аксессуары",
        "Пуховики": "Верхняя одежда",
        "Рубашки": "Рубашки, блузки и топы",
        "Свитшоты": "Худи, футболки и лонгсливы",
        "Свитшоты/лонгсливы/футболки": "Худи, футболки и лонгсливы",
        "Топы": "Рубашки, блузки и топы",
        "Тренчкоты": "Верхняя одежда",
        "Трусы": "Бельё и домашняя одежда",
        "Футболки": "Худи, футболки и лонгсливы",
        "Худи": "Худи, футболки и лонгсливы",
        "Шорты": "Брюки и шорты",
        "Юбки из трикотажа": "Юбки",
        "Юбки миди/макси": "Юбки",
        "Юбки мини": "Юбки",
    }
    _ignored_category_names = {
        "Бесплатные выкройки",
        "Капсула недели",
        "Капсула недели скидка -20%",
    }

    def __init__(
        self,
        *,
        timeout: float = 40.0,
        retries: int = 3,
        max_groups: int | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.max_groups = max_groups
        self.requests_made = 0
        self.retries_made = 0
        self.incomplete_pages: list[str] = []
        self.total_pages = 0
        self.last_skipped = 0

    async def fetch_products(self) -> ProviderResult:
        errors = 0
        skipped = 0
        products_by_key: dict[str, ParsedProduct] = {}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; PatternHubBot/0.7; "
                "+https://github.com/local/patternhub-bot)"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Accept": "application/json,text/html;q=0.9",
            "Connection": "close",
        }
        timeout = httpx.Timeout(self.timeout, connect=min(20.0, self.timeout))

        async with httpx.AsyncClient(
            headers=headers, timeout=timeout, follow_redirects=True, trust_env=False
        ) as client:
            home_html = await self._get_text(client, self.base_url)
            if home_html is None:
                return ProviderResult([], errors=1, complete=False)
            try:
                home_data = self.parse_next_data(home_html)
            except (ValueError, json.JSONDecodeError) as error:
                logger.error("Could not parse SewItNow homepage Next data: %s", error)
                return ProviderResult([], errors=1, complete=False)

            build_id = str(home_data.get("buildId") or "")
            groups = self._groups(home_data)
            category_index = self.category_index(groups)
            pages = self.catalog_pages(groups)
            if self.max_groups is not None:
                pages = pages[: self.max_groups]

            for page_context in pages:
                page_url = self.catalog_data_url(build_id, page_context.slug)
                payload = await self._get_json(client, page_url)
                if not isinstance(payload, dict):
                    errors += 1
                    continue
                try:
                    page_products, page_skipped = self.parse_catalog_payload(
                        payload,
                        category_index,
                        page_context,
                    )
                except Exception as error:  # noqa: BLE001
                    errors += 1
                    logger.exception("Could not parse SewItNow page %s: %s", page_url, error)
                    continue

                skipped += page_skipped
                for product in page_products:
                    products_by_key[product.source_product_id or product.product_url] = product
                logger.info(
                    "SewItNow page %s: parsed=%d skipped=%d",
                    page_context.slug,
                    len(page_products),
                    page_skipped,
                )

        complete = errors == 0 and not self.incomplete_pages and self.max_groups is None
        if self.incomplete_pages:
            logger.warning(
                "SewItNow import is partial because additional pages need query-string pagination: %s",
                ", ".join(self.incomplete_pages),
            )
        self.last_skipped = skipped
        return ProviderResult(
            list(products_by_key.values()),
            errors=errors,
            skipped=skipped,
            complete=complete,
        )

    async def _get_text(self, client: httpx.AsyncClient, url: str) -> str | None:
        for attempt in range(1, self.retries + 1):
            self.requests_made += 1
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.text
            except httpx.HTTPError as error:
                logger.warning(
                    "SewItNow HTTP error (%d/%d) for %s: %s",
                    attempt,
                    self.retries,
                    url,
                    error,
                )
                if attempt < self.retries:
                    self.retries_made += 1
                    await asyncio.sleep(float(attempt))
        return None

    async def _get_json(self, client: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
        text = await self._get_text(client, url)
        if text is None:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            logger.warning("SewItNow JSON decode error for %s: %s", url, error)
            return None

    def catalog_data_url(self, build_id: str, slug: str) -> str:
        safe_slug = quote(slug.strip("/"), safe="")
        return f"{self.base_url}/_next/data/{build_id}/catalog/{safe_slug}.json"

    @classmethod
    def parse_next_data(cls, html: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        node = soup.select_one("script#__NEXT_DATA__")
        if node is None:
            raise ValueError("missing __NEXT_DATA__")
        return json.loads(node.string or node.get_text())

    @staticmethod
    def _groups(next_data: dict[str, Any]) -> list[dict[str, Any]]:
        props = next_data.get("props") or {}
        page_props = props.get("pageProps") or next_data.get("pageProps") or {}
        seller = page_props.get("initSeller") or {}
        groups = seller.get("groups") or []
        return [group for group in groups if isinstance(group, dict)]

    @staticmethod
    def catalog_pages(groups: list[dict[str, Any]]) -> list[SewItNowCategoryContext]:
        pages: list[SewItNowCategoryContext] = []
        for group in groups:
            group_id = str(group.get("id") or "")
            group_slug = str(group.get("slug") or group_id)
            group_name = str(group.get("name") or "")
            if not group_id or not group_slug or not group_name:
                continue
            pages.append(
                SewItNowCategoryContext(
                    id=group_id,
                    name=group_name,
                    slug=group_slug,
                    parent_name=None,
                )
            )
        return pages

    @staticmethod
    def category_index(
        groups: list[dict[str, Any]]
    ) -> dict[str, SewItNowCategoryContext]:
        index: dict[str, SewItNowCategoryContext] = {}
        for group in groups:
            group_id = str(group.get("id") or "")
            group_name = str(group.get("name") or "")
            group_slug = str(group.get("slug") or group_id)
            if group_id and group_name:
                index[group_id] = SewItNowCategoryContext(
                    id=group_id,
                    name=group_name,
                    slug=group_slug,
                    parent_name=None,
                )
            for category in group.get("categories") or []:
                if not isinstance(category, dict):
                    continue
                category_id = str(category.get("id") or "")
                category_name = str(category.get("name") or "")
                category_slug = str(category.get("slug") or category_id)
                if category_id and category_name:
                    index[category_id] = SewItNowCategoryContext(
                        id=category_id,
                        name=category_name,
                        slug=category_slug,
                        parent_name=group_name,
                    )
        return index

    def parse_catalog_payload(
        self,
        payload: dict[str, Any],
        category_index: dict[str, SewItNowCategoryContext],
        page_context: SewItNowCategoryContext,
    ) -> tuple[list[ParsedProduct], int]:
        page_props = payload.get("pageProps") or {}
        products_data = page_props.get("initGetProducts") or {}
        pages = self._int(products_data.get("pages")) or 0
        elements = self._int(products_data.get("elements")) or 0
        if pages > 1:
            marker = f"{page_context.slug} ({pages} pages, {elements} products)"
            if marker not in self.incomplete_pages:
                self.incomplete_pages.append(marker)
        self.total_pages += max(pages, 1)

        parsed: list[ParsedProduct] = []
        skipped = 0
        seen: set[str] = set()
        for item in products_data.get("list") or []:
            if not isinstance(item, dict):
                continue
            try:
                product = self._parse_product(item, category_index, page_context)
            except (KeyError, TypeError, ValueError) as error:
                logger.warning("Could not parse SewItNow product: %s", error)
                continue
            key = product.source_product_id or product.product_url
            if key in seen:
                continue
            seen.add(key)
            if self._should_skip_product(product):
                skipped += 1
                continue
            parsed.append(product)
        return parsed, skipped

    def _parse_product(
        self,
        item: dict[str, Any],
        category_index: dict[str, SewItNowCategoryContext],
        page_context: SewItNowCategoryContext,
    ) -> ParsedProduct:
        product_id = str(item["id"])
        name = self._clean(str(item.get("name") or ""))
        slug = str(item.get("slug") or "")
        if not product_id or not name or not slug:
            raise ValueError("missing id, name or slug")

        context = self._context_for_product(item, category_index, page_context)
        audience = self._audience(context)
        price = self._decimal(item.get("price"))
        old_price = self._old_price(item, price)
        sizes, heights = self._sizes_heights(item, audience)

        return ParsedProduct(
            source=self.source,
            source_product_id=product_id,
            name=name,
            brand=self.brand,
            audience=audience,
            category=self._category(name, context),
            subcategory=context.name if not context.is_special else None,
            price=price,
            old_price=old_price,
            currency="RUB",
            is_sale=old_price is not None and price is not None and old_price > price,
            is_free=price == Decimal("0"),
            is_new=False,
            sizes=sizes,
            heights=heights,
            product_url=urljoin(self.base_url, f"/product/{slug}/"),
            image_url=self._image_url(item),
            is_available=bool(item.get("status", True)),
        ).normalized()

    @staticmethod
    def _context_for_product(
        item: dict[str, Any],
        category_index: dict[str, SewItNowCategoryContext],
        page_context: SewItNowCategoryContext,
    ) -> SewItNowCategoryContext:
        category = item.get("category") or {}
        category_id = str(category.get("id") or "")
        return category_index.get(category_id) or page_context

    @classmethod
    def _audience(cls, context: SewItNowCategoryContext) -> str | None:
        names = " ".join((context.parent_name or "", context.name)).casefold()
        if "детск" in names:
            return "kids"
        if context.is_special:
            return None
        return "women"

    @classmethod
    def _category(cls, name: str, context: SewItNowCategoryContext) -> str | None:
        if context.name in cls._category_overrides:
            return cls._category_overrides[context.name]
        if context.name not in cls._ignored_category_names:
            normalized = normalize_category(context.name)
            if normalized:
                return normalized
        return normalize_category(name)

    @classmethod
    def _old_price(cls, item: dict[str, Any], price: Decimal | None) -> Decimal | None:
        candidates = [cls._decimal(item.get("real_price"))]
        for price_item in item.get("price_list") or []:
            if isinstance(price_item, dict):
                candidates.append(cls._decimal(price_item.get("price")))
        old_prices = [value for value in candidates if value is not None]
        if price is None:
            return max(old_prices) if old_prices else None
        higher = [value for value in old_prices if value > price]
        return max(higher) if higher else None

    @classmethod
    def _sizes_heights(
        cls, item: dict[str, Any], audience: str | None
    ) -> tuple[tuple[str, ...] | None, tuple[str, ...] | None]:
        sizes: list[str] = []
        heights: list[str] = []
        for attribute in item.get("product_attributes") or []:
            if not isinstance(attribute, dict):
                continue
            attribute_value = attribute.get("attribute_value") or {}
            value = str(attribute_value.get("value") or "")
            parts = [part.strip() for part in re.split(r"[,/;]", value) if part.strip()]
            if len(parts) >= 2:
                first, second = parts[0], parts[1]
                if cls._looks_like_height(first):
                    heights.append(first)
                    sizes.append(second)
                else:
                    sizes.extend(parts)
                continue
            if not parts:
                continue
            part = parts[0]
            if cls._looks_like_height(part) and audience == "kids":
                heights.append(part)
            elif cls._looks_like_height(part) and not sizes:
                heights.append(part)
            else:
                sizes.append(part)
        return cls._unique(sizes), cls._unique(heights)

    @staticmethod
    def _looks_like_height(value: str) -> bool:
        number = re.search(r"\d{2,3}", value)
        return bool(number and int(number.group(0)) >= 80)

    @staticmethod
    def _image_url(item: dict[str, Any]) -> str | None:
        for image in item.get("images") or []:
            if not isinstance(image, dict):
                continue
            storage_object = image.get("storage_object") or {}
            url = storage_object.get("url")
            if url:
                return str(url)
        return None

    @staticmethod
    def _should_skip_product(product: ParsedProduct) -> bool:
        text = " ".join(
            value.casefold()
            for value in (product.name, product.category or "", product.product_url)
        )
        markers = ("игрушк", "гусь", "сертификат", "подарочная карта")
        return any(marker in text for marker in markers)

    @staticmethod
    def _unique(values: list[str]) -> tuple[str, ...] | None:
        cleaned = tuple(dict.fromkeys(value for value in values if value))
        return cleaned or None

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _int(value: object) -> int | None:
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _decimal(value: object) -> Decimal | None:
        if value is None:
            return None
        text = str(value).replace("\u00a0", " ")
        match = re.search(r"-?\d+(?:[\s ]\d{3})*(?:[.,]\d+)?", text)
        if not match:
            return None
        normalized = match.group(0).replace(" ", "").replace(",", ".")
        try:
            return Decimal(normalized)
        except InvalidOperation:
            return None
