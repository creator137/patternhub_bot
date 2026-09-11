from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

from app.models.audience import normalize_audience
from app.models.categories import normalize_category


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def _clean_values(values: tuple[str, ...] | list[str] | None) -> tuple[str, ...] | None:
    if not values:
        return None
    cleaned = tuple(dict.fromkeys(filter(None, (_clean_text(value) for value in values))))
    return cleaned or None


def _clean_url(value: str) -> str:
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"Product URL must be an absolute HTTP URL: {value!r}")
    path = re.sub(r"/{2,}", "/", parts.path)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


@dataclass(frozen=True, slots=True)
class ParsedProduct:
    source: str
    name: str
    product_url: str
    source_product_id: str | None = None
    brand: str | None = None
    audience: str | None = None
    category: str | None = None
    subcategory: str | None = None
    price: Decimal | None = None
    old_price: Decimal | None = None
    currency: str | None = None
    is_sale: bool = False
    is_free: bool = False
    is_new: bool = False
    sizes: tuple[str, ...] | None = None
    heights: tuple[str, ...] | None = None
    difficulty: str | None = None
    description: str | None = None
    image_url: str | None = None
    is_available: bool = True
    source_updated_at: datetime | None = None

    def normalized(self) -> "ParsedProduct":
        source = (_clean_text(self.source) or "").lower()
        name = _clean_text(self.name) or ""
        if not source or not name:
            raise ValueError("Product source and name are required")

        price = self.price.quantize(Decimal("0.01")) if self.price is not None else None
        old_price = (
            self.old_price.quantize(Decimal("0.01"))
            if self.old_price is not None
            else None
        )
        is_free = self.is_free or price == Decimal("0.00")
        is_sale = price is not None and old_price is not None and old_price > price
        return replace(
            self,
            source=source,
            source_product_id=_clean_text(self.source_product_id),
            name=name,
            brand=_clean_text(self.brand),
            audience=normalize_audience(self.audience),
            category=normalize_category(self.category),
            subcategory=_clean_text(self.subcategory),
            price=price,
            old_price=old_price,
            currency=(_clean_text(self.currency) or "").upper() or None,
            is_sale=is_sale,
            is_free=is_free,
            is_new=bool(self.is_new),
            sizes=_clean_values(self.sizes),
            heights=_clean_values(self.heights),
            difficulty=_clean_text(self.difficulty),
            description=_clean_text(self.description),
            product_url=_clean_url(self.product_url),
            image_url=_clean_url(self.image_url) if self.image_url else None,
        )


@dataclass(frozen=True, slots=True)
class Product:
    id: int
    source: str
    source_product_id: str | None
    name: str
    brand: str | None
    audience: str | None
    category: str | None
    subcategory: str | None
    price: Decimal | None
    old_price: Decimal | None
    currency: str | None
    is_sale: bool
    is_free: bool
    is_new: bool
    sizes: tuple[str, ...] | None
    heights: tuple[str, ...] | None
    difficulty: str | None
    description: str | None
    product_url: str
    image_url: str | None
    is_available: bool
    created_at: datetime
    updated_at: datetime
    source_updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class CatalogCategory:
    code: str
    name: str
    products: int


@dataclass(frozen=True, slots=True)
class ProductFilter:
    source: str | None = None
    audience: str | tuple[str, ...] | None = None
    category: str | None = None
    is_sale: bool | None = None
    is_free: bool | None = None
    is_new: bool | None = None


@dataclass(frozen=True, slots=True)
class SyncStats:
    source: str
    found: int
    added: int
    updated: int
    skipped: int
    unavailable: int
    errors: int
    complete: bool
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class CatalogStats:
    products: int
    total: int
    available: int
    unavailable: int
    by_source: dict[str, int]
    unavailable_by_source: dict[str, int]
    on_sale: int
    new: int
    free: int
    categories: int
    no_price: int
    no_image: int
    by_audience: dict[str, int]
