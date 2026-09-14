from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Iterable
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from time import monotonic
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from app.models.product import ParsedProduct, Product
from app.providers.base import BaseProvider, ProviderResult


logger = logging.getLogger(__name__)


class VikiSewsProvider(BaseProvider):
    source = "vikisews"
    base_url = "https://vikisews.com"
    catalog_url = f"{base_url}/vykrojki/vse-vykrojki/"

    _category_by_slug = {
        "platja-i-sarafany": "Платья",
        "bryuki-dzhinsy-shorty": "Брюки и шорты",
        "jubki": "Юбки",
        "zhakety-kardigany-zhilety": "Жакеты и жилеты",
        "verhnjaja-odezhda": "Верхняя одежда",
        "rubashki-bluzki-korsazhi": "Рубашки, блузки и топы",
        "khudi-futbolki-longslivy": "Худи, футболки и лонгсливы",
        "kombinezony": "Комбинезоны",
        "detskie-vykrojki": "Детские",
        "muzhskie-vykrojki": "Мужские",
        "aksessuary": "Аксессуары",
        "belye-domashnyaya-odezhda": "Бельё и домашняя одежда",
    }

    def __init__(
        self,
        *,
        request_delay: float = 10.0,
        timeout: float = 150.0,
        max_pages: int = 200,
        retries: int = 3,
        page_size: int = 24,
        enrich_details: bool = False,
        detail_limit: int | None = None,
    ) -> None:
        self.request_delay = request_delay
        self.timeout = timeout
        self.max_pages = max_pages
        self.retries = retries
        self.page_size = page_size
        self.enrich_details = enrich_details
        self.detail_limit = detail_limit
        self._last_request_started: float | None = None

    async def fetch_products(self) -> ProviderResult:
        products_by_key: dict[str, ParsedProduct] = {}
        errors = 0
        consecutive_errors = 0
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; PatternHubBot/0.2; "
                "+https://github.com/local/patternhub-bot)"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Connection": "close",
        }
        timeout = httpx.Timeout(self.timeout, connect=min(20.0, self.timeout))

        async with httpx.AsyncClient(
            headers=headers,
            cookies={"django_language": "ru"},
            timeout=timeout,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            for page_number in range(1, self.max_pages + 1):
                page_url = (
                    f"{self.catalog_url}?page={page_number}"
                    f"&page_size={self.page_size}"
                )
                html = await self._get_page(client, page_url)
                if html is None:
                    errors += 1
                    consecutive_errors += 1
                    if consecutive_errors >= 3:
                        logger.error("Stopping after 3 consecutive failed catalog pages")
                        break
                    continue
                consecutive_errors = 0

                page_products = self.parse_catalog_page(html, page_url)
                new_count = 0
                for product in page_products:
                    key = product.source_product_id or product.product_url
                    if key not in products_by_key:
                        new_count += 1
                    products_by_key[key] = product

                logger.info(
                    "VikiSews catalog page %d: parsed=%d new=%d",
                    page_number,
                    len(page_products),
                    new_count,
                )
                if not page_products or new_count == 0:
                    break
                if not self.has_next_page(html):
                    logger.info("VikiSews catalog ended on page %d", page_number)
                    break
            else:
                logger.warning("VikiSews parser reached max_pages=%d", self.max_pages)
                errors += 1

            if self.enrich_details and errors == 0:
                enriched_result = await self._enrich_parsed_products(
                    client,
                    list(products_by_key.values()),
                )
                errors += enriched_result.errors
                for product in enriched_result.products:
                    products_by_key[product.source_product_id or product.product_url] = product

        return ProviderResult(list(products_by_key.values()), errors, complete=errors == 0)

    async def enrich_products(self, products: Iterable[Product]) -> ProviderResult:
        seed_products = [self._seed_from_product(product) for product in products]
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; PatternHubBot/0.2; "
                "+https://github.com/local/patternhub-bot)"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Connection": "close",
        }
        timeout = httpx.Timeout(self.timeout, connect=min(20.0, self.timeout))
        async with httpx.AsyncClient(
            headers=headers,
            cookies={"django_language": "ru"},
            timeout=timeout,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            return await self._enrich_parsed_products(client, seed_products)

    @staticmethod
    def _seed_from_product(product: Product) -> ParsedProduct:
        return ParsedProduct(
            source=product.source,
            source_product_id=product.source_product_id,
            name=product.name,
            brand=product.brand,
            audience=product.audience,
            category=product.category,
            subcategory=product.subcategory,
            price=product.price,
            old_price=product.old_price,
            currency=product.currency,
            is_sale=product.is_sale,
            is_free=product.is_free,
            is_new=product.is_new,
            is_beginner=False,
            is_knit=False,
            sizes=product.sizes,
            heights=product.heights,
            difficulty=product.difficulty,
            description=product.description,
            product_url=product.product_url,
            image_url=product.image_url,
            is_available=product.is_available,
            source_updated_at=product.source_updated_at,
        ).normalized()

    async def _enrich_parsed_products(
        self,
        client: httpx.AsyncClient,
        products: list[ParsedProduct],
    ) -> ProviderResult:
        detail_products = products
        if self.detail_limit is not None:
            detail_products = detail_products[: self.detail_limit]
        enriched: list[ParsedProduct] = []
        errors = 0
        for index, product in enumerate(detail_products, start=1):
            html = await self._get_page(client, product.product_url)
            if html is None:
                errors += 1
                logger.warning("Could not fetch VikiSews detail page %s", product.product_url)
                continue
            try:
                detailed = self.parse_product_page(html, product.product_url, product)
            except Exception as error:  # noqa: BLE001
                errors += 1
                logger.warning(
                    "Could not parse VikiSews detail page %s: %s",
                    product.product_url,
                    error,
                )
                continue
            merged = self._merge_product(product, detailed)
            enriched.append(merged)
            logger.info(
                "VikiSews detail page %d/%d: %s beginner=%s knit=%s",
                index,
                len(detail_products),
                product.product_url,
                merged.is_beginner,
                merged.is_knit,
            )
        return ProviderResult(enriched, errors, complete=errors == 0)

    async def _get_page(
        self, client: httpx.AsyncClient, url: str
    ) -> str | None:
        for attempt in range(1, self.retries + 1):
            if self._last_request_started is not None:
                elapsed = monotonic() - self._last_request_started
                await asyncio.sleep(max(0.0, self.request_delay - elapsed))
            self._last_request_started = monotonic()
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.text
            except httpx.HTTPError as error:
                logger.warning(
                    "VikiSews HTTP error (%d/%d) for %s: %s",
                    attempt,
                    self.retries,
                    url,
                    error,
                )
                if attempt < self.retries:
                    await asyncio.sleep(float(attempt * 2))
        return None

    def parse_catalog_page(self, html: str, page_url: str) -> list[ParsedProduct]:
        soup = BeautifulSoup(html, "html.parser")
        products: list[ParsedProduct] = []
        seen: set[str] = set()

        for name_node in soup.select(".popular-product-name"):
            card = name_node.find_parent("a", href=True)
            if card is None:
                card = name_node.find_parent(class_=self._has_slide_link_class)
            if not isinstance(card, Tag):
                continue

            link = card.get("href")
            if not link:
                link_node = card.select_one("a[href*='/vykrojki/']")
                link = link_node.get("href") if link_node else None
            if not link:
                continue

            product_url = urljoin(page_url, str(link))
            source_product_id = str(name_node.get("data-obj-id") or "").strip() or None
            key = source_product_id or product_url
            if key in seen:
                continue
            seen.add(key)

            price, old_price, sale_marker = self._extract_prices(card)
            image_url = self._extract_image_url(card, page_url)
            category = self._category_from_url(product_url)
            audience = self._audience_from_url(product_url)
            if audience in {"men", "kids"}:
                category = self._category_from_name(name_node.get_text(" ", strip=True))
            products.append(
                ParsedProduct(
                    source=self.source,
                    source_product_id=source_product_id,
                    name=name_node.get_text(" ", strip=True),
                    brand="VikiSews",
                    audience=audience,
                    category=category,
                    subcategory=category,
                    price=price,
                    old_price=old_price,
                    currency="RUB",
                    is_sale=sale_marker,
                    is_free=price == Decimal("0.00"),
                    product_url=product_url,
                    image_url=image_url,
                ).normalized()
            )
        return products

    @staticmethod
    def has_next_page(html: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")
        return soup.select_one("#infinite-upload-more[data-link]") is not None

    def parse_product_page(
        self, html: str, product_url: str, seed: ParsedProduct | None = None
    ) -> ParsedProduct:
        """Parse optional detail fields without coupling them to catalog storage."""
        soup = BeautifulSoup(html, "html.parser")
        structured = self._product_json_ld(soup)
        name = str(structured.get("name") or (seed.name if seed else "")).strip()
        images = structured.get("image")
        image_url = images[0] if isinstance(images, list) and images else images
        offers = structured.get("offers") if isinstance(structured.get("offers"), dict) else {}
        price = self._decimal(offers.get("price"))
        if price is None:
            price = self._decimal(structured.get("price"))

        sizes = tuple(
            node.get_text(" ", strip=True)
            for node in soup.select("#sizeRow .sizes")
            if node.get_text(" ", strip=True)
        ) or None
        heights = tuple(
            node.get_text(" ", strip=True)
            for node in soup.select("#growthRow .growth")
            if node.get_text(" ", strip=True)
        ) or None
        breadcrumb = soup.select(".breadcrumb a")
        category = (
            breadcrumb[-1].get_text(" ", strip=True)
            if breadcrumb
            else self._category_from_url(product_url)
        )
        difficulty_node = soup.find(
            "a", string=re.compile(r"уровень|beginner|advanced", re.IGNORECASE)
        )
        description_node = soup.select_one('meta[name="description"]')
        materials_text = self._recommended_materials_text(soup)
        detail_tags = self._detail_tags(soup)
        is_knit = self._is_knit_product(materials_text, detail_tags)

        base = seed or ParsedProduct(
            source=self.source,
            name=name,
            product_url=product_url,
        )
        audience = self._audience_from_url(product_url) or base.audience
        if audience in {"men", "kids"}:
            category = self._category_from_name(name) or category
        return ParsedProduct(
            source=base.source,
            source_product_id=base.source_product_id,
            name=name or base.name,
            brand=base.brand or "VikiSews",
            audience=audience,
            category=category or base.category,
            subcategory=base.subcategory,
            price=price if price is not None else base.price,
            old_price=base.old_price,
            currency=str(offers.get("priceCurrency") or base.currency or "RUB"),
            is_sale=base.is_sale,
            is_free=base.is_free,
            is_new=base.is_new,
            is_beginner=base.is_beginner,
            is_knit=is_knit,
            sizes=sizes or base.sizes,
            heights=heights or base.heights,
            difficulty=(
                difficulty_node.get_text(" ", strip=True)
                if difficulty_node
                else base.difficulty
            ),
            description=(
                str(description_node.get("content"))
                if description_node and description_node.get("content")
                else base.description
            ),
            product_url=product_url,
            image_url=str(image_url) if image_url else base.image_url,
            is_available=base.is_available,
            source_updated_at=base.source_updated_at,
        ).normalized()

    @staticmethod
    def _merge_product(existing: ParsedProduct, product: ParsedProduct) -> ParsedProduct:
        return replace(
            product,
            is_sale=existing.is_sale or product.is_sale,
            is_free=existing.is_free or product.is_free,
            is_new=existing.is_new or product.is_new,
            is_beginner=existing.is_beginner or product.is_beginner,
            is_knit=product.is_knit,
            image_url=product.image_url or existing.image_url,
            is_available=existing.is_available or product.is_available,
        ).normalized()

    @staticmethod
    def _has_slide_link_class(value: object) -> bool:
        if isinstance(value, str):
            return "slide-link" in value.split()
        if isinstance(value, list):
            return "slide-link" in value
        return False

    @classmethod
    def _extract_prices(cls, card: Tag) -> tuple[Decimal | None, Decimal | None, bool]:
        values: list[Decimal] = []
        for node in card.select("[data-product-price], [data-price]"):
            raw = node.get("data-product-price") or node.get("data-price")
            value = cls._decimal(raw)
            if value is not None and value not in values:
                values.append(value)
        for node in card.select("[class*='price']"):
            value = cls._decimal(node.get_text(" ", strip=True))
            if value is not None and value not in values:
                values.append(value)

        is_sale = "SALE" in card.get_text(" ", strip=True).upper() or len(values) > 1
        if not values:
            return None, None, is_sale
        if is_sale and len(values) > 1:
            return min(values), max(values), True
        return values[-1], None, is_sale

    @staticmethod
    def _extract_image_url(card: Tag, page_url: str) -> str | None:
        node = card.select_one("img[data-src], img[src], source[srcset]")
        if not node:
            return None
        value = node.get("data-src") or node.get("src") or node.get("srcset")
        if not value:
            return None
        return urljoin(page_url, str(value).split(",")[0].split()[0])

    @classmethod
    def _category_from_url(cls, product_url: str) -> str | None:
        match = re.search(r"/vykrojki/([^/]+)/[^/]+/?$", product_url)
        return cls._category_by_slug.get(match.group(1)) if match else None

    @staticmethod
    def _audience_from_url(product_url: str) -> str | None:
        if "/muzhskie-vykrojki/" in product_url:
            return "men"
        if "/detskie-vykrojki/" in product_url:
            return "kids"
        if "/vykrojki/" in product_url:
            return "women"
        return None

    @staticmethod
    def _category_from_name(name: str) -> str | None:
        text = name.casefold().replace("ё", "е")
        checks: tuple[tuple[tuple[str, ...], str], ...] = (
            (("сарафан", "плать"), "Платья"),
            (("брюк", "шорт", "джинс", "лосин", "леггинс"), "Брюки и шорты"),
            (("юбк",), "Юбки"),
            (("жакет", "жилет", "пиджак"), "Жакеты и жилеты"),
            (("пальто", "куртк", "плащ", "тренч", "бомбер", "парка"), "Верхняя одежда"),
            (("рубашк", "блузк", "топ", "майк", "водолазк", "боди"), "Рубашки, блузки и топы"),
            (("худи", "свитшот", "футболк", "лонгслив", "джемпер", "свитер", "толстовк", "кардиган"), "Худи, футболки и лонгсливы"),
            (("комбинезон", "полукомбинезон"), "Комбинезоны"),
            (("халат", "пижам", "купальник", "бель", "трус"), "Бельё и домашняя одежда"),
            (("панам", "шапк", "кепк", "сумк", "галстук", "тапк"), "Аксессуары"),
        )
        for markers, category in checks:
            if any(marker in text for marker in markers):
                return category
        return "Другое"

    @staticmethod
    def _recommended_materials_text(soup: BeautifulSoup) -> str | None:
        for button in soup.select("button.accordion"):
            header = button.get_text(" ", strip=True)
            if "рекомендуемые материалы" not in header.casefold():
                continue
            target = str(button.get("data-target") or "").lstrip("#")
            panel = soup.select_one(f"#{target} .panel") if target else None
            if panel is None:
                wrapper = button.find_parent()
                panel = wrapper.find_next(class_="panel") if wrapper else None
            if panel:
                return panel.get_text(" ", strip=True)
        return None

    @staticmethod
    def _detail_tags(soup: BeautifulSoup) -> tuple[str, ...]:
        tags: list[str] = []
        for node in soup.select(".tags a, .subtext .tags a"):
            text = node.get_text(" ", strip=True)
            if text:
                tags.append(text)
        return tuple(tags)

    @staticmethod
    def _is_knit_product(materials_text: str | None, tags: tuple[str, ...]) -> bool:
        tag_text = " ".join(tags).casefold().replace("ё", "е")
        if "трикотаж" in tag_text:
            return True
        text = (materials_text or "").casefold().replace("ё", "е")
        if not text or "трикотаж" not in text:
            return False
        negative_patterns = (
            "не рекомендуются",
            "не рекомендуется",
            "нерастяжимые",
            "нерастяжимый",
            "нерастяжимая",
        )
        positive_patterns = (
            "подойдут трикотажные",
            "подойдет трикотаж",
            "рекомендуются трикотажные",
            "рекомендуется трикотаж",
            "трикотажные полотна",
            "трикотажное полотно",
            "кулирная гладь",
            "кашкорсе",
            "рибана",
            "футер",
            "интерлок",
            "бифлекс",
            "джерси",
        )
        sentences = re.split(r"(?<=[.!?])\s+|;", text)
        for sentence in sentences:
            if "трикотаж" not in sentence and not any(
                marker in sentence for marker in positive_patterns[5:]
            ):
                continue
            if any(marker in sentence for marker in negative_patterns):
                continue
            if any(marker in sentence for marker in positive_patterns):
                return True
        return False

    @staticmethod
    def _decimal(value: object) -> Decimal | None:
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
    def _product_json_ld(soup: BeautifulSoup) -> dict[str, object]:
        for node in soup.select('script[type="application/ld+json"]'):
            try:
                value = json.loads(node.string or node.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            candidates = value if isinstance(value, list) else [value]
            for candidate in candidates:
                if isinstance(candidate, dict) and candidate.get("@type") == "Product":
                    return candidate
        return {}
