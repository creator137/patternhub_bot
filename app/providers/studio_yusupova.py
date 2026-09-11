from __future__ import annotations

import asyncio
import html
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.models.categories import normalize_category
from app.models.product import ParsedProduct
from app.providers.base import BaseProvider, ProviderResult


logger = logging.getLogger(__name__)


class StudioYusupovaProvider(BaseProvider):
    source = "studio_yusupova"
    base_url = "https://studio-yusupova.ru"
    products_url = f"{base_url}/wp-json/wc/store/v1/products"
    categories_url = f"{base_url}/wp-json/wc/store/v1/products/categories"

    _audience_categories = {
        "Женская одежда": "women",
        "Мужская одежда": "men",
    }
    _broad_product_categories = {"Трикотаж"}
    _ignored_categories = {"Женская одежда", "Мужская одежда", "Uncategorized"}

    def __init__(
        self,
        *,
        timeout: float = 40.0,
        retries: int = 3,
        per_page: int = 100,
        max_pages: int = 20,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.per_page = per_page
        self.max_pages = max_pages
        self.requests_made = 0
        self.retries_made = 0
        self.total_pages = 0

    async def fetch_products(self) -> ProviderResult:
        errors = 0
        complete = False
        products_by_key: dict[str, ParsedProduct] = {}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; PatternHubBot/0.5; "
                "+https://github.com/local/patternhub-bot)"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Accept": "application/json",
            "Connection": "close",
        }
        timeout = httpx.Timeout(self.timeout, connect=min(20.0, self.timeout))

        async with httpx.AsyncClient(
            headers=headers, timeout=timeout, follow_redirects=True, trust_env=False
        ) as client:
            categories_payload, _ = await self._get_json(client, self.categories_url)
            if not isinstance(categories_payload, list):
                logger.error("Studio Yusupova categories endpoint returned unexpected payload")
                return ProviderResult([], errors=1, complete=False)
            categories = self._category_index(categories_payload)

            first_page_url = self._products_page_url(1)
            first_payload, first_headers = await self._get_json(client, first_page_url)
            if not isinstance(first_payload, list):
                logger.error("Studio Yusupova products endpoint returned unexpected payload")
                return ProviderResult([], errors=1, complete=False)

            total_pages = self._total_pages(first_headers) or 1
            self.total_pages = total_pages
            if total_pages > self.max_pages:
                logger.error(
                    "Studio Yusupova total_pages=%d exceeds max_pages=%d",
                    total_pages,
                    self.max_pages,
                )
                return ProviderResult([], errors=1, complete=False)

            for product in self.parse_products_payload(first_payload, categories):
                products_by_key[product.source_product_id or product.product_url] = product
            logger.info(
                "Studio Yusupova page %d/%d: parsed=%d",
                1,
                total_pages,
                len(first_payload),
            )

            for page in range(2, total_pages + 1):
                payload, _headers = await self._get_json(
                    client, self._products_page_url(page)
                )
                if not isinstance(payload, list):
                    errors += 1
                    logger.error("Could not fetch Studio Yusupova products page %d", page)
                    break
                for product in self.parse_products_payload(payload, categories):
                    products_by_key[product.source_product_id or product.product_url] = product
                logger.info(
                    "Studio Yusupova page %d/%d: parsed=%d",
                    page,
                    total_pages,
                    len(payload),
                )
            else:
                complete = errors == 0

        return ProviderResult(
            list(products_by_key.values()),
            errors=errors,
            complete=complete,
        )

    def _products_page_url(self, page: int) -> str:
        return f"{self.products_url}?per_page={self.per_page}&page={page}"

    async def _get_json(
        self, client: httpx.AsyncClient, url: str
    ) -> tuple[Any, httpx.Headers]:
        for attempt in range(1, self.retries + 1):
            self.requests_made += 1
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.json(), response.headers
            except (httpx.HTTPError, ValueError) as error:
                logger.warning(
                    "Studio Yusupova HTTP/JSON error (%d/%d) for %s: %s",
                    attempt,
                    self.retries,
                    url,
                    error,
                )
                if attempt < self.retries:
                    self.retries_made += 1
                    await asyncio.sleep(float(attempt))
        return None, httpx.Headers()

    @staticmethod
    def _total_pages(headers: httpx.Headers) -> int | None:
        value = headers.get("x-wp-totalpages")
        try:
            return int(value) if value else None
        except ValueError:
            return None

    @staticmethod
    def _category_index(payload: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        return {
            int(category["id"]): category
            for category in payload
            if isinstance(category, dict) and str(category.get("id", "")).isdigit()
        }

    def parse_products_payload(
        self,
        payload: list[dict[str, Any]],
        categories: dict[int, dict[str, Any]] | None = None,
    ) -> list[ParsedProduct]:
        products: list[ParsedProduct] = []
        category_index = categories or {}
        for item in payload:
            try:
                products.append(self._parse_product(item, category_index))
            except (KeyError, TypeError, ValueError) as error:
                logger.warning("Could not parse Studio Yusupova product: %s", error)
        return products

    def _parse_product(
        self, item: dict[str, Any], category_index: dict[int, dict[str, Any]]
    ) -> ParsedProduct:
        product_id = str(item["id"])
        name = self._clean_html(str(item.get("name") or ""))
        product_url = str(item.get("permalink") or "")
        if not name or not product_url:
            raise ValueError("missing product name or permalink")

        category_names = self._category_names(item, category_index)
        price, old_price = self._prices(item.get("prices") or {})
        sizes, heights = self._attributes(item.get("attributes") or [])

        return ParsedProduct(
            source=self.source,
            source_product_id=product_id,
            name=name,
            brand="Studio Yusupova",
            audience=self._audience(category_names),
            category=self._product_category(name, product_url, category_names),
            subcategory=self._subcategory(category_names),
            price=price,
            old_price=old_price,
            currency=str((item.get("prices") or {}).get("currency_code") or "RUB"),
            is_sale=bool(item.get("on_sale")),
            is_free=price == Decimal("0.00"),
            is_new=False,
            sizes=sizes,
            heights=heights,
            description=self._description(item),
            product_url=product_url,
            image_url=self._image_url(item),
            is_available=bool(item.get("is_purchasable", True))
            and bool(item.get("is_in_stock", True))
            and not bool(item.get("is_password_protected", False)),
        ).normalized()

    def _category_names(
        self, item: dict[str, Any], category_index: dict[int, dict[str, Any]]
    ) -> tuple[str, ...]:
        names: list[str] = []
        seen: set[str] = set()
        for category in item.get("categories") or []:
            if not isinstance(category, dict):
                continue
            category_id = self._int(category.get("id"))
            chain = self._category_chain(category_id, category_index)
            if not chain:
                chain = [str(category.get("name") or "")]
            for name in chain:
                clean_name = self._clean_html(name)
                if clean_name and clean_name not in seen:
                    names.append(clean_name)
                    seen.add(clean_name)
        return tuple(names)

    def _category_chain(
        self, category_id: int | None, category_index: dict[int, dict[str, Any]]
    ) -> list[str]:
        if category_id is None:
            return []
        category = category_index.get(category_id)
        if not category:
            return []
        parent_id = self._int(category.get("parent"))
        parents = self._category_chain(parent_id, category_index) if parent_id else []
        return [*parents, str(category.get("name") or "")]

    @classmethod
    def _audience(cls, categories: tuple[str, ...]) -> str | None:
        audiences = {
            audience
            for category in categories
            if (audience := cls._audience_categories.get(category))
        }
        if audiences == {"women", "men"}:
            return "unisex"
        if len(audiences) == 1:
            return next(iter(audiences))
        return None

    @classmethod
    def _product_category(
        cls, name: str, product_url: str, categories: tuple[str, ...]
    ) -> str | None:
        name_category = cls._category_from_name(f"{name} {product_url}")
        category_candidates = [
            category
            for category in categories
            if category not in cls._ignored_categories
            and category not in cls._broad_product_categories
        ]
        if (
            name_category is not None
            and any(category in {"Платья и юбки", "Трикотаж"} for category in categories)
        ):
            return name_category
        for category in category_candidates:
            normalized = normalize_category(category)
            if normalized:
                return normalized
        return name_category

    @classmethod
    def _subcategory(cls, categories: tuple[str, ...]) -> str | None:
        for category in categories:
            if category not in cls._ignored_categories:
                return category
        return None

    @staticmethod
    def _category_from_name(name: str) -> str | None:
        text = name.casefold()
        slug_checks: tuple[tuple[tuple[str, ...], str], ...] = (
            (("dress",), "Платья"),
            (("skirt",), "Юбки"),
            (("bruki", "pants", "jeans", "short"), "Брюки и шорты"),
            (("jacket", "coat", "anorak", "peacoat", "furcoat"), "Верхняя одежда"),
            (("sweatshirt", "hoodie", "pullover", "t-short"), "Худи, футболки и лонгсливы"),
            (("blouse", "shirt", "sorochka", "top"), "Рубашки, блузки и топы"),
            (("vest", "jilet"), "Жакеты и жилеты"),
            (("hat", "bag", "basque"), "Аксессуары"),
        )
        for markers, category in slug_checks:
            if any(marker in text for marker in markers):
                return category
        normalized = normalize_category(name)
        return normalized if normalized != name.strip() else None

    @classmethod
    def _prices(cls, prices: dict[str, Any]) -> tuple[Decimal | None, Decimal | None]:
        price = cls._decimal(prices.get("price"))
        regular_price = cls._decimal(prices.get("regular_price"))
        sale_price = cls._decimal(prices.get("sale_price"))
        current = price if price is not None else sale_price
        old_price = (
            regular_price
            if regular_price is not None and current is not None and regular_price > current
            else None
        )
        return current, old_price

    @staticmethod
    def _attributes(
        attributes: list[dict[str, Any]],
    ) -> tuple[tuple[str, ...] | None, tuple[str, ...] | None]:
        sizes: tuple[str, ...] | None = None
        heights: tuple[str, ...] | None = None
        for attribute in attributes:
            name = str(attribute.get("name") or "").casefold().replace("ё", "е")
            terms = tuple(
                StudioYusupovaProvider._clean_html(str(term.get("name") or ""))
                for term in attribute.get("terms") or []
                if isinstance(term, dict) and term.get("name")
            )
            if not terms:
                continue
            if "размер" in name:
                sizes = terms
            elif "рост" in name:
                heights = terms
        return sizes, heights

    @classmethod
    def _description(cls, item: dict[str, Any]) -> str | None:
        value = item.get("short_description") or item.get("description")
        description = cls._clean_html(str(value or ""))
        return description or None

    @staticmethod
    def _image_url(item: dict[str, Any]) -> str | None:
        for image in item.get("images") or []:
            if isinstance(image, dict):
                value = image.get("src") or image.get("thumbnail")
                if value:
                    return str(value)
        return None

    @staticmethod
    def _clean_html(value: str) -> str:
        unescaped = html.unescape(value)
        if "<" in unescaped and ">" in unescaped:
            text = BeautifulSoup(unescaped, "html.parser").get_text(" ", strip=True)
        else:
            text = unescaped
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        match = re.search(r"-?\d+(?:[\s\u00a0]\d{3})*(?:[.,]\d+)?", str(value))
        if not match:
            return None
        normalized = match.group(0).replace(" ", "").replace("\u00a0", "").replace(",", ".")
        try:
            return Decimal(normalized)
        except InvalidOperation:
            return None

    @staticmethod
    def _int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
