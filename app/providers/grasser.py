from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from time import monotonic
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from app.models.product import ParsedProduct
from app.providers.base import BaseProvider, ProviderResult


logger = logging.getLogger(__name__)


class GrasserProvider(BaseProvider):
    source = "grasser"
    base_url = "https://grasser.ru"
    catalog_url = f"{base_url}/vykrojki/"
    quick_filter_pages = (
        ("vykroyki-dlya-nachinayushchikh", True, False),
        ("zhenskie-vykroyki-dlya-nachinayushchikh", True, False),
        ("muzhskie-vykroyki-dlya-nachinayushchikh", True, False),
        ("detskie-vykroyki-dlya-nachinayushchikh", True, False),
        ("shem-iz-trikotazha", False, True),
    )

    def __init__(
        self,
        *,
        timeout: float = 60.0,
        max_pages: int = 100,
        retries: int = 3,
    ) -> None:
        self.timeout = timeout
        self.max_pages = max_pages
        self.retries = retries
        self.requests_made = 0
        self.retries_made = 0
        self.last_skipped = 0

    async def fetch_products(self) -> ProviderResult:
        products_by_key: dict[str, ParsedProduct] = {}
        errors = 0
        skipped = 0
        skipped_product_ids: set[str] = set()
        skipped_product_urls: set[str] = set()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; PatternHubBot/0.3; "
                "+https://github.com/local/patternhub-bot)"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Connection": "close",
        }
        timeout = httpx.Timeout(self.timeout, connect=min(20.0, self.timeout))

        async with httpx.AsyncClient(
            headers=headers, timeout=timeout, follow_redirects=True, trust_env=False
        ) as client:
            (
                catalog_errors,
                catalog_skipped,
                catalog_skipped_ids,
                catalog_skipped_urls,
            ) = await self._fetch_catalog_section(
                client,
                self.catalog_url,
                products_by_key,
                page_is_beginner=False,
                page_is_knit=False,
                stop_on_duplicates=True,
            )
            errors += catalog_errors
            skipped += catalog_skipped
            skipped_product_ids.update(catalog_skipped_ids)
            skipped_product_urls.update(catalog_skipped_urls)

            if catalog_errors == 0:
                for slug, is_beginner, is_knit in self.quick_filter_pages:
                    section_url = urljoin(self.catalog_url, f"{slug}/")
                    (
                        section_errors,
                        section_skipped,
                        section_skipped_ids,
                        section_skipped_urls,
                    ) = await self._fetch_catalog_section(
                        client,
                        section_url,
                        products_by_key,
                        page_is_beginner=is_beginner,
                        page_is_knit=is_knit,
                        stop_on_duplicates=False,
                    )
                    errors += section_errors
                    skipped += section_skipped
                    skipped_product_ids.update(section_skipped_ids)
                    skipped_product_urls.update(section_skipped_urls)

        return ProviderResult(
            list(products_by_key.values()),
            errors,
            skipped=skipped,
            skipped_product_ids=tuple(skipped_product_ids),
            skipped_product_urls=tuple(skipped_product_urls),
            complete=errors == 0,
        )

    async def _fetch_catalog_section(
        self,
        client: httpx.AsyncClient,
        section_url: str,
        products_by_key: dict[str, ParsedProduct],
        *,
        page_is_beginner: bool,
        page_is_knit: bool,
        stop_on_duplicates: bool,
    ) -> tuple[int, int, set[str], set[str]]:
        errors = 0
        skipped = 0
        skipped_product_ids: set[str] = set()
        skipped_product_urls: set[str] = set()
        page_number = 1
        while page_number <= self.max_pages:
            page_url = self.page_url(page_number, section_url)
            html = await self._get_page(client, page_url)
            if html is None:
                errors += 1
                break

            try:
                page_products = self.parse_catalog_page(
                    html,
                    page_url,
                    page_is_beginner=page_is_beginner,
                    page_is_knit=page_is_knit,
                )
                skipped += self.last_skipped
                skipped_product_ids.update(self.last_skipped_product_ids)
                skipped_product_urls.update(self.last_skipped_product_urls)
            except Exception as error:  # noqa: BLE001 - keep one bad page isolated
                errors += 1
                logger.exception("Could not parse Grasser catalog page %s: %s", page_url, error)
                break

            new_count = 0
            for product in page_products:
                key = product.source_product_id or product.product_url
                existing = products_by_key.get(key)
                if existing is None:
                    new_count += 1
                    products_by_key[key] = product
                else:
                    products_by_key[key] = self._merge_product(existing, product)

            logger.info(
                "Grasser catalog section %s page %d: parsed=%d new=%d beginner=%s knit=%s",
                section_url,
                page_number,
                len(page_products),
                new_count,
                page_is_beginner,
                page_is_knit,
            )
            if not page_products or (stop_on_duplicates and new_count == 0):
                break

            next_page = self.next_page_number(html, page_number)
            if next_page is None:
                break
            page_number = next_page
        else:
            logger.warning(
                "Grasser parser reached max_pages=%d for %s",
                self.max_pages,
                section_url,
            )
            errors += 1
        return errors, skipped, skipped_product_ids, skipped_product_urls

    def page_url(self, page_number: int, section_url: str | None = None) -> str:
        base_url = section_url or self.catalog_url
        if page_number <= 1:
            return base_url
        return f"{base_url}?PAGEN_3={page_number}"

    async def _get_page(
        self, client: httpx.AsyncClient, url: str
    ) -> str | None:
        for attempt in range(1, self.retries + 1):
            self.requests_made += 1
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.text
            except httpx.HTTPError as error:
                logger.warning(
                    "Grasser HTTP error (%d/%d) for %s: %s",
                    attempt,
                    self.retries,
                    url,
                    error,
                )
                if attempt < self.retries:
                    self.retries_made += 1
                    await asyncio.sleep(float(attempt))
        return None

    def parse_catalog_page(
        self,
        html: str,
        page_url: str,
        *,
        page_is_beginner: bool = False,
        page_is_knit: bool = False,
    ) -> list[ParsedProduct]:
        soup = BeautifulSoup(html, "html.parser")
        products: list[ParsedProduct] = []
        seen: set[str] = set()
        self.last_skipped = 0
        self.last_skipped_product_ids: set[str] = set()
        self.last_skipped_product_urls: set[str] = set()

        for card in soup.select(".catalog.vykrojki > .catalog-block"):
            try:
                product = self._parse_card(card, page_url)
            except (ValueError, TypeError, AttributeError) as error:
                logger.warning("Could not parse Grasser product card on %s: %s", page_url, error)
                continue
            if self._should_skip_product(product):
                self.last_skipped += 1
                if product.source_product_id:
                    self.last_skipped_product_ids.add(product.source_product_id)
                self.last_skipped_product_urls.add(product.product_url)
                continue
            key = product.source_product_id or product.product_url
            if key in seen:
                continue
            seen.add(key)
            product = replace(
                product,
                is_beginner=product.is_beginner or page_is_beginner,
                is_knit=product.is_knit or page_is_knit,
            ).normalized()
            products.append(product)
        return products

    @staticmethod
    def _merge_product(existing: ParsedProduct, product: ParsedProduct) -> ParsedProduct:
        return replace(
            existing,
            old_price=product.old_price or existing.old_price,
            is_sale=existing.is_sale or product.is_sale,
            is_free=existing.is_free or product.is_free,
            is_new=existing.is_new or product.is_new,
            is_beginner=existing.is_beginner or product.is_beginner,
            is_knit=existing.is_knit or product.is_knit,
            image_url=existing.image_url or product.image_url,
            is_available=existing.is_available or product.is_available,
        ).normalized()

    def _parse_card(self, card: Tag, page_url: str) -> ParsedProduct:
        title_node = card.select_one(".catalog-block__title[href]")
        if not isinstance(title_node, Tag):
            raise ValueError("missing product title")

        product_url = urljoin(page_url, str(title_node.get("href")))
        name = title_node.find(string=True, recursive=False) or title_node.get_text(" ", strip=True)
        name = re.sub(r"\s+", " ", str(name)).strip()
        source_product_id = self._source_product_id(card, name)
        raw_category = self._category_from_url(product_url) or self._category_from_name(name)
        audience = self._audience_from_url(product_url)
        if audience in {"men", "kids"}:
            raw_category = self._category_from_name(name)
        price, old_price = self._extract_prices(card)
        text = card.get_text(" ", strip=True).casefold()
        is_new = any(
            "новин" in node.get_text(" ", strip=True).casefold()
            for node in card.select(".catalog-block__label, .product-features__item")
        )

        return ParsedProduct(
            source=self.source,
            source_product_id=source_product_id,
            name=name,
            brand="Grasser",
            audience=audience,
            category=raw_category,
            subcategory=raw_category,
            price=price,
            old_price=old_price,
            currency="RUB",
            is_sale=old_price is not None and price is not None and old_price > price,
            is_free=price == Decimal("0.00"),
            is_new=is_new,
            product_url=product_url,
            image_url=self._extract_image_url(card, page_url),
            is_available="нет в наличии" not in text,
        ).normalized()

    @staticmethod
    def next_page_number(html: str, current_page: int = 1) -> int | None:
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[int] = []
        for link in soup.select(".pagination a[href*='PAGEN_3='], .js-show-more[data-url*='PAGEN_3=']"):
            value = link.get("href") or link.get("data-url")
            match = re.search(r"[?&]PAGEN_3=(\d+)", str(value))
            if match:
                candidates.append(int(match.group(1)))
        next_pages = [page for page in candidates if page > current_page]
        return min(next_pages) if next_pages else None

    def parse_product_page(
        self, html: str, product_url: str, seed: ParsedProduct | None = None
    ) -> ParsedProduct:
        soup = BeautifulSoup(html, "html.parser")
        structured = self._product_json_ld(soup)
        canonical = self._canonical_url(soup) or product_url
        name_node = soup.select_one(".product__info h1")
        name = (
            name_node.get_text(" ", strip=True)
            if name_node
            else str(structured.get("name") or (seed.name if seed else "")).strip()
        )
        offers = structured.get("offers") if isinstance(structured.get("offers"), dict) else {}
        price = self._decimal(offers.get("price"))
        old_price = self._decimal_text(soup.select_one(".product__old-price"))
        current_price = self._decimal_text(soup.select_one(".product__current-price"))
        if current_price is not None:
            price = current_price

        sizes = tuple(
            node.get_text(" ", strip=True)
            for node in soup.select(".product__size .product__digit")
            if node.get_text(" ", strip=True)
        ) or None
        heights = tuple(
            node.get_text(" ", strip=True)
            for node in soup.select(".product__length .product__digit")
            if node.get_text(" ", strip=True)
        ) or None
        difficulty = None
        for tag in soup.select(".product-meta .tag"):
            text = tag.get_text(" ", strip=True)
            if "сложность" in text.casefold():
                difficulty = text
                break
        description_node = soup.select_one(".product__info-subtitle")
        description = description_node.get_text(" ", strip=True) if description_node else None
        image = structured.get("image")

        base = seed or ParsedProduct(
            source=self.source,
            name=name,
            product_url=canonical,
        )
        audience = base.audience or self._audience_from_url(canonical)
        category = base.category or self._category_from_url(canonical) or self._category_from_name(name)
        if audience in {"men", "kids"}:
            category = self._category_from_name(name) or category
        return ParsedProduct(
            source=base.source,
            source_product_id=self._detail_id(soup) or base.source_product_id,
            name=name or base.name,
            brand=base.brand or "Grasser",
            audience=audience,
            category=category,
            subcategory=base.subcategory,
            price=price if price is not None else base.price,
            old_price=old_price if old_price is not None else base.old_price,
            currency="RUB",
            is_sale=base.is_sale,
            is_free=base.is_free,
            is_new=base.is_new,
            sizes=sizes or base.sizes,
            heights=heights or base.heights,
            difficulty=difficulty or base.difficulty,
            description=description or base.description,
            product_url=canonical,
            image_url=str(image) if image else base.image_url,
            is_available=base.is_available,
            source_updated_at=base.source_updated_at,
        ).normalized()

    @classmethod
    def _extract_prices(cls, card: Tag) -> tuple[Decimal | None, Decimal | None]:
        price_node = card.select_one(".catalog-block__price")
        if not price_node:
            return None, None
        old_price = cls._decimal_text(price_node.select_one(".catalog-block__price-old"))
        prices = [
            value
            for value in (cls._decimal(item) for item in re.findall(r"\d[\d\s\u00a0]*[.,]?\d*", price_node.get_text(" ", strip=True)))
            if value is not None
        ]
        current_price = prices[-1] if prices else None
        if old_price is not None and current_price == old_price and len(prices) > 1:
            current_price = prices[-1]
        return current_price, old_price

    @staticmethod
    def _extract_image_url(card: Tag, page_url: str) -> str | None:
        node = card.select_one(".catalog-block__image img[src], .catalog-block__image source[srcset]")
        if not node:
            return None
        value = node.get("src") or node.get("srcset")
        if not value:
            return None
        return urljoin(page_url, str(value).split(",")[0].split()[0])

    @staticmethod
    def _source_product_id(card: Tag, name: str) -> str | None:
        node = card.select_one("[data-elid], button[data-id]")
        if node:
            value = node.get("data-elid") or node.get("data-id")
            if value:
                return str(value).strip()
        match = re.search(r"№\s*(\d+)", name)
        return match.group(1) if match else None

    @staticmethod
    def _detail_id(soup: BeautifulSoup) -> str | None:
        node = soup.select_one("#id_element[value]")
        return str(node.get("value")).strip() if node else None

    @staticmethod
    def _category_from_url(product_url: str) -> str | None:
        slug_map = {
            "platya-i-sarafany": "Платья и сарафаны",
            "zhakety-i-zhilety": "Жакеты и жилеты",
            "bluzki-i-rubashki": "Блузки и рубашки",
            "bryuki-shorty-kombinezony": "Брюки, шорты, комбинезоны",
            "vykrojki-bryuk-short": "Брюки, шорты",
            "vykroyki-verkhney-odezhdy": "Верхняя одежда",
            "vykrojki-kurtok": "Верхняя одежда",
            "yubki": "Юбки",
            "vykrojki-futbolok-bodi-topov": "Водолазки, лонгсливы, боди, футболки, топы, майки",
            "svitshoty": "Свитшоты, худи, толстовки, свитеры, джемперы, кардиганы",
            "nizhnee-bele-i-kupalniki": "Нижнее белье и купальники",
            "muzhskie-vykrojki": "Мужские",
            "detskie-vykrojki": "Детские",
            "vykroyki-golovnykh-uborov": "Выкройки аксессуаров",
        }
        match = re.search(r"/vykrojki/([^/]+)/", product_url)
        return slug_map.get(match.group(1)) if match else None

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
        match = re.match(r"\s*([^,№]+)", name)
        return match.group(1).strip() if match else None

    @staticmethod
    def _should_skip_product(product: ParsedProduct) -> bool:
        text = " ".join(
            value.casefold()
            for value in (product.name, product.category or "", product.product_url)
        )
        markers = (
            "подарочный сертификат",
            "podarochnye-sertifikaty",
            "кукла-раскраска",
            "кукла с моделями одежды",
            "kukla-raskraska",
            "kukla-s-modelyami-odezhdy",
            "лежанка для животных",
            "lezhanka-dlya-zhivotnykh",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _canonical_url(soup: BeautifulSoup) -> str | None:
        node = soup.select_one("link[rel='canonical'][href]")
        return str(node.get("href")).strip() if node else None

    @classmethod
    def _decimal_text(cls, node: Tag | None) -> Decimal | None:
        return cls._decimal(node.get_text(" ", strip=True) if node else None)

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
