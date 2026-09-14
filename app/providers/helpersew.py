from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from time import monotonic
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from app.models.product import ParsedProduct
from app.providers.base import BaseProvider, ProviderResult


logger = logging.getLogger(__name__)


class HelperSewProvider(BaseProvider):
    source = "helpersew"
    base_url = "https://helpersew.com"

    category_pages: tuple[
        tuple[str, str, str | None] | tuple[str, str, str | None, bool, bool],
        ...,
    ] = (
        ("/catalog/zhenskie/", "women", None),
        (
            "/catalog/zhenskie/zhenskie-vykroyki-dlya-nachinayushchikh/",
            "women",
            None,
            True,
            False,
        ),
        ("/catalog/zhenskie/vykroyki-iz-trikotazha/", "women", None, False, True),
        ("/catalog/zhenskie/bryuki/", "women", "Брюки"),
        ("/catalog/zhenskie/palto-i-zhakety/", "women", "Верхняя одежда"),
        ("/catalog/zhenskie/vodolazki-i-longslivy/", "women", "Водолазки и лонгсливы"),
        ("/catalog/zhenskie/domashnyaya-odezhda/", "women", "Домашняя одежда"),
        ("/catalog/zhenskie/zhakety-i-kardigany/", "women", "Жакеты и кардиганы"),
        ("/catalog/zhenskie/kombinezon/", "women", "Комбинезоны"),
        ("/catalog/zhenskie/kupalniki/", "women", "Купальники"),
        ("/catalog/zhenskie/legginsy-i-velosipedki/", "women", "Легинсы и велосипедки"),
        ("/catalog/zhenskie/mayki-i-topy/", "women", "Майки и топы"),
        ("/catalog/zhenskie/platya-i-sarafany/", "women", "Платья и сарафаны"),
        ("/catalog/zhenskie/rubashki/", "women", "Рубашки и блузы"),
        ("/catalog/zhenskie/svitshoty-khudi-i-svitery/", "women", "Свитшоты, худи и свитеры"),
        ("/catalog/zhenskie/futbolki/", "women", "Футболки"),
        ("/catalog/zhenskie/shorty/", "women", "Шорты"),
        ("/catalog/zhenskie/yubki/", "women", "Юбки"),
        ("/catalog/muzhskie/", "men", None),
        (
            "/catalog/muzhskie/muzhskie-vykroyki-dlya-nachinayushchikh/",
            "men",
            None,
            True,
            False,
        ),
        ("/catalog/muzhskie/verkhnyaya-odezhda-dlya-muzhchin/", "men", "Верхняя одежда"),
        (
            "/catalog/muzhskie/vykroyki-iz-trikotazha-men/",
            "men",
            None,
            False,
            True,
        ),
        ("/catalog/muzhskie/bryukimen/", "men", "Брюки"),
        ("/catalog/muzhskie/rubashki-/", "men", "Рубашки"),
        ("/catalog/muzhskie/svitshoty-tolstovki-khudi/", "men", "Свитшоты, толстовки, худи"),
        ("/catalog/muzhskie/futbolki-men/", "men", "Футболки"),
        ("/catalog/muzhskie/shorty-men/", "men", "Шорты"),
        ("/catalog/podrostki/", "kids", None),
        ("/catalog/podrostki/dlya-nachinayushchikh/", "kids", None, True, False),
        (
            "/catalog/podrostki/vykroyki-iz-trikotazha-teenager/",
            "kids",
            None,
            False,
            True,
        ),
        ("/catalog/podrostki/bryuki-teenager/", "kids", "Брюки"),
        ("/catalog/podrostki/verkhnyaya-odezhda/", "kids", "Верхняя одежда"),
        ("/catalog/podrostki/platya-teenager/", "kids", "Платья"),
        ("/catalog/podrostki/rubashki-teenager/", "kids", "Рубашки"),
        ("/catalog/podrostki/futbolki-teenager/", "kids", "Футболки и лонгсливы"),
        ("/catalog/podrostki/svitshoty-tolstovki-khudi-teenager/", "kids", "Свитшоты, толстовки, худи"),
        ("/catalog/podrostki/yubki-teenager/", "kids", "Юбки"),
        ("/catalog/detskie/", "kids", None),
        (
            "/catalog/detskie/detskie-vykroyki-dlya-nachinayushchikh/",
            "kids",
            None,
            True,
            False,
        ),
        ("/catalog/detskie/vykroyki-iz-trikotazha-deti/", "kids", None, False, True),
        ("/catalog/detskie/detskie-bryuki/", "kids", "Брюки"),
        ("/catalog/detskie/detskie-zhilety/", "kids", "Жилеты"),
        ("/catalog/detskie/kombinezony/", "kids", "Комбинезоны"),
        ("/catalog/detskie/kurtki/", "kids", "Куртки"),
        ("/catalog/detskie/platya-i-sarafanydeti/", "kids", "Платья и сарафаны"),
        ("/catalog/detskie/rubashki-deti/", "kids", "Рубашки"),
        ("/catalog/detskie/futbolki-deti/", "kids", "Футболки и топы"),
        ("/catalog/detskie/khudi-i-svitshoty/", "kids", "Худи и свитшоты"),
        ("/catalog/detskie/shorty-deti/", "kids", "Шорты"),
        ("/catalog/detskie/yubki-deti/", "kids", "Юбки"),
    )

    def __init__(
        self,
        *,
        timeout: float = 40.0,
        retries: int = 3,
        request_delay: float = 0.8,
        max_categories: int | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.request_delay = request_delay
        self.max_categories = max_categories
        self.requests_made = 0
        self.retries_made = 0
        self.last_skipped = 0
        self._last_request_started: float | None = None

    async def fetch_products(self) -> ProviderResult:
        products_by_key: dict[str, ParsedProduct] = {}
        errors = 0
        skipped = 0
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; PatternHubBot/0.4; "
                "+https://github.com/local/patternhub-bot)"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Connection": "close",
        }
        timeout = httpx.Timeout(self.timeout, connect=min(20.0, self.timeout))

        pages = self.category_pages[: self.max_categories]
        async with httpx.AsyncClient(
            headers=headers, timeout=timeout, follow_redirects=True, trust_env=False
        ) as client:
            for page_config in pages:
                path, audience, category, is_beginner, is_knit = self._page_config(
                    page_config
                )
                page_url = urljoin(self.base_url, path)
                html = await self._get_page(client, page_url)
                if html is None:
                    errors += 1
                    continue
                try:
                    page_products = self.parse_catalog_page(
                        html,
                        page_url,
                        page_audience=audience,
                        page_category=category,
                        page_is_beginner=is_beginner,
                        page_is_knit=is_knit,
                    )
                    skipped += self.last_skipped
                except Exception as error:  # noqa: BLE001
                    errors += 1
                    logger.exception(
                        "Could not parse HelperSew catalog page %s: %s", page_url, error
                    )
                    continue

                new_count = 0
                for product in page_products:
                    key = product.source_product_id or product.product_url
                    if key not in products_by_key:
                        new_count += 1
                        products_by_key[key] = product
                    else:
                        products_by_key[key] = self._merge_product(
                            products_by_key[key],
                            product,
                        )
                logger.info(
                    "HelperSew page %s: parsed=%d new=%d",
                    page_url,
                    len(page_products),
                    new_count,
                )

        return ProviderResult(
            list(products_by_key.values()),
            errors,
            skipped=skipped,
            complete=errors == 0 and self.max_categories is None,
        )

    async def _get_page(self, client: httpx.AsyncClient, url: str) -> str | None:
        for attempt in range(1, self.retries + 1):
            if self._last_request_started is not None:
                elapsed = monotonic() - self._last_request_started
                await asyncio.sleep(max(0.0, self.request_delay - elapsed))
            self._last_request_started = monotonic()
            self.requests_made += 1
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.text
            except httpx.HTTPError as error:
                logger.warning(
                    "HelperSew HTTP error (%d/%d) for %s: %s",
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
        page_audience: str | None = None,
        page_category: str | None = None,
        page_is_beginner: bool = False,
        page_is_knit: bool = False,
    ) -> list[ParsedProduct]:
        soup = BeautifulSoup(html, "html.parser")
        products: list[ParsedProduct] = []
        seen: set[str] = set()
        self.last_skipped = 0

        for card in soup.select(".cat-card"):
            try:
                product = self._parse_card(
                    card,
                    page_url,
                    page_audience,
                    page_category,
                    page_is_beginner,
                    page_is_knit,
                )
            except (ValueError, TypeError, AttributeError) as error:
                logger.warning("Could not parse HelperSew product card on %s: %s", page_url, error)
                continue
            if self._should_skip_product(product):
                self.last_skipped += 1
                continue
            key = product.source_product_id or product.product_url
            if key in seen:
                continue
            seen.add(key)
            products.append(product)
        return products

    def parse_product_page(
        self, html: str, product_url: str, seed: ParsedProduct | None = None
    ) -> ParsedProduct:
        soup = BeautifulSoup(html, "html.parser")
        structured = self._product_json_ld(soup)
        name_node = soup.select_one("h1")
        name = (
            name_node.get_text(" ", strip=True)
            if name_node
            else str(structured.get("name") or (seed.name if seed else "")).strip()
        )
        price = self._decimal_text(soup.select_one(".cat-detail-price"))
        description_node = soup.select_one(".cat-detail-list-content")
        meta_description = soup.select_one('meta[name="description"]')
        difficulty_node = soup.select_one(".cat-detail-dificult")
        tags_text = soup.select_one(".cat-detail-tags_wrap")
        image_node = soup.select_one(".cat-detail__pic img[src], .cat-detail__pic source[srcset]")
        sizes, heights = self._extract_detail_sizes(soup)

        base = seed or ParsedProduct(source=self.source, name=name, product_url=product_url)
        return ParsedProduct(
            source=base.source,
            source_product_id=base.source_product_id,
            name=name or base.name,
            brand=base.brand or "HelperSew",
            audience=base.audience or self._audience_from_url(product_url),
            category=base.category or self._category_from_url(product_url),
            subcategory=base.subcategory,
            price=price if price is not None else base.price,
            old_price=base.old_price,
            currency=base.currency or "RUB",
            is_sale=base.is_sale,
            is_free=base.is_free,
            is_new=base.is_new or (
                tags_text is not None
                and "new" in tags_text.get_text(" ", strip=True).casefold()
            ),
            sizes=sizes or base.sizes,
            heights=heights or base.heights,
            difficulty=(
                difficulty_node.get_text(" ", strip=True) if difficulty_node else base.difficulty
            ),
            description=(
                description_node.get_text(" ", strip=True)
                if description_node
                else str(meta_description.get("content"))
                if meta_description and meta_description.get("content")
                else base.description
            ),
            product_url=product_url,
            image_url=(
                urljoin(product_url, str(image_node.get("src") or image_node.get("srcset")).split()[0])
                if image_node
                else base.image_url
            ),
            is_available=base.is_available,
            source_updated_at=base.source_updated_at,
        ).normalized()

    def _parse_card(
        self,
        card: Tag,
        page_url: str,
        page_audience: str | None,
        page_category: str | None,
        page_is_beginner: bool,
        page_is_knit: bool,
    ) -> ParsedProduct:
        name_node = card.select_one(".cat-card__name[href]")
        if not isinstance(name_node, Tag):
            raise ValueError("missing product title")
        name = name_node.get_text(" ", strip=True)
        product_url = urljoin(page_url, str(name_node.get("href")))
        source_product_id = self._source_product_id(card)
        price, old_price = self._extract_prices(card)
        labels = self._labels(card)

        return ParsedProduct(
            source=self.source,
            source_product_id=source_product_id,
            name=name,
            brand="HelperSew",
            audience="unisex" if "unisex" in labels else page_audience,
            category=page_category or self._category_from_url(product_url),
            subcategory=page_category or self._category_from_url(product_url),
            price=price,
            old_price=old_price,
            currency="RUB",
            is_sale="sale" in labels,
            is_free=price == Decimal("0.00"),
            is_new="new" in labels,
            is_beginner=page_is_beginner,
            is_knit=page_is_knit,
            product_url=product_url,
            image_url=self._extract_image_url(card, page_url),
            is_available="скоро" not in card.get_text(" ", strip=True).casefold(),
        ).normalized()

    @staticmethod
    def _page_config(
        config: tuple[str, str, str | None] | tuple[str, str, str | None, bool, bool],
    ) -> tuple[str, str, str | None, bool, bool]:
        if len(config) == 3:
            path, audience, category = config
            return path, audience, category, False, False
        return config

    @staticmethod
    def _merge_product(existing: ParsedProduct, product: ParsedProduct) -> ParsedProduct:
        return replace(
            product,
            is_sale=existing.is_sale or product.is_sale,
            is_free=existing.is_free or product.is_free,
            is_new=existing.is_new or product.is_new,
            is_beginner=existing.is_beginner or product.is_beginner,
            is_knit=existing.is_knit or product.is_knit,
        ).normalized()

    @classmethod
    def _extract_prices(cls, card: Tag) -> tuple[Decimal | None, Decimal | None]:
        price_node = card.select_one(".cat-card__price")
        if not price_node:
            return None, None
        old_price = cls._decimal_text(price_node.select_one(".card__price-old"))
        prices = [
            value
            for value in (
                cls._decimal(match)
                for match in re.findall(
                    r"\d[\d\s\u00a0]*[.,]?\d*", price_node.get_text(" ", strip=True)
                )
            )
            if value is not None
        ]
        current_price = prices[-1] if prices else None
        if current_price is None and "бесплат" in price_node.get_text(" ", strip=True).casefold():
            current_price = Decimal("0")
        return current_price, old_price

    @staticmethod
    def _extract_image_url(card: Tag, page_url: str) -> str | None:
        node = card.select_one(".cat-card__pic-link picture:not(.onhover) img, .cat-card__pic-link img")
        if not node:
            node = card.select_one(".cat-card__pic-link picture:not(.onhover) source[srcset]")
        if not node:
            return None
        value = node.get("src") or node.get("srcset") or node.get("data-src")
        if not value:
            return None
        return urljoin(page_url, str(value).split(",")[0].split()[0])

    @staticmethod
    def _source_product_id(card: Tag) -> str | None:
        node = card.select_one("[data-comp], button[popup*='prodform']")
        if node:
            value = node.get("data-comp")
            if value:
                return str(value).strip()
            popup = str(node.get("popup") or "")
            match = re.search(r"prodform=['\"]?(\d+)", popup)
            if match:
                return match.group(1)
        match = re.search(r"_(\d+)$", str(card.get("id") or ""))
        return match.group(1) if match else None

    @staticmethod
    def _labels(card: Tag) -> set[str]:
        labels: set[str] = set()
        for node in card.select(".cat-card__sticks span"):
            classes = {str(item).casefold() for item in node.get("class", [])}
            text = node.get_text(" ", strip=True).casefold()
            if "new" in classes or text == "new" or "новин" in text:
                labels.add("new")
            if "sale" in classes or "скид" in text or text == "sale":
                labels.add("sale")
            if "бесплат" in text:
                labels.add("free")
            if "unisex" in text or "унисекс" in text:
                labels.add("unisex")
        return labels

    @staticmethod
    def _category_from_url(product_url: str) -> str | None:
        path = urlsplit(product_url).path
        slug_map = {
            "bryuki": "Брюки",
            "bryukimen": "Брюки",
            "detskie-bryuki": "Брюки",
            "palto-i-zhakety": "Верхняя одежда",
            "verkhnyaya-odezhda": "Верхняя одежда",
            "verkhnyaya-odezhda-dlya-muzhchin": "Верхняя одежда",
            "vodolazki-i-longslivy": "Водолазки и лонгсливы",
            "domashnyaya-odezhda": "Домашняя одежда",
            "zhakety-i-kardigany": "Жакеты и кардиганы",
            "kombinezon": "Комбинезоны",
            "kombinezony": "Комбинезоны",
            "kupalniki": "Купальники",
            "legginsy-i-velosipedki": "Легинсы и велосипедки",
            "mayki-i-topy": "Майки и топы",
            "platya-i-sarafany": "Платья и сарафаны",
            "platya-i-sarafanydeti": "Платья и сарафаны",
            "platya-teenager": "Платья",
            "rubashki": "Рубашки и блузы",
            "rubashki-": "Рубашки",
            "rubashki-deti": "Рубашки",
            "rubashki-teenager": "Рубашки",
            "svitshoty-khudi-i-svitery": "Свитшоты, худи и свитеры",
            "svitshoty-tolstovki-khudi": "Свитшоты, толстовки, худи",
            "svitshoty-tolstovki-khudi-teenager": "Свитшоты, толстовки, худи",
            "futbolki": "Футболки",
            "futbolki-men": "Футболки",
            "futbolki-deti": "Футболки и топы",
            "futbolki-teenager": "Футболки и лонгсливы",
            "khudi-i-svitshoty": "Худи и свитшоты",
            "shorty": "Шорты",
            "shorty-men": "Шорты",
            "shorty-deti": "Шорты",
            "yubki": "Юбки",
            "yubki-deti": "Юбки",
            "yubki-teenager": "Юбки",
        }
        parts = [part for part in path.strip("/").split("/") if part]
        for part in reversed(parts[:-1]):
            if part in slug_map:
                return slug_map[part]
        return None

    @staticmethod
    def _audience_from_url(product_url: str) -> str | None:
        path = urlsplit(product_url).path
        if "/catalog/muzhskie/" in path:
            return "men"
        if "/catalog/detskie/" in path or "/catalog/podrostki/" in path:
            return "kids"
        if "/catalog/zhenskie/" in path:
            return "women"
        return None

    @staticmethod
    def _should_skip_product(product: ParsedProduct) -> bool:
        text = " ".join(
            value.casefold()
            for value in (product.name, product.category or "", product.product_url)
        )
        markers = ("сертификат", "подарочная карта", "gift-card")
        return any(marker in text for marker in markers)

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
    def _extract_detail_sizes(
        soup: BeautifulSoup,
    ) -> tuple[tuple[str, ...] | None, tuple[str, ...] | None]:
        text = " ".join(
            node.get_text(" ", strip=True) for node in soup.select(".cat-detail-list-content")
        )
        sizes_match = re.search(r"Размер\s+RU\s+([0-9–\-]+)", text)
        heights_match = re.search(r"Рост\s+от\s+(\d+)\s*см\s+до\s+(\d+)\s*см", text)
        sizes = (sizes_match.group(1),) if sizes_match else None
        heights = (
            (f"{heights_match.group(1)}-{heights_match.group(2)}",)
            if heights_match
            else None
        )
        return sizes, heights

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
