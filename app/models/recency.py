"""A complete manufacturer ordering; ranks are never publication dates."""
from dataclasses import dataclass
from collections.abc import Iterable


def product_order_key(product) -> str:
    return product.source_product_id or product.product_url


@dataclass(frozen=True, slots=True)
class RecencySnapshot:
    source: str
    keys: tuple[str, ...]
    basis: str
    complete: bool

    @classmethod
    def from_products(cls, source: str, products: Iterable, *, basis: str, complete: bool):
        products = list(products)
        if any(product.source != source for product in products):
            raise ValueError("Recency snapshot contains another source")
        keys = tuple(dict.fromkeys(product_order_key(product) for product in products))
        return cls(source, keys, basis, complete and bool(keys))
