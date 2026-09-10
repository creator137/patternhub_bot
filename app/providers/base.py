from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.product import ParsedProduct


@dataclass(frozen=True, slots=True)
class ProviderResult:
    products: list[ParsedProduct]
    errors: int = 0


class BaseProvider(ABC):
    source: str

    @abstractmethod
    async def fetch_products(self) -> ProviderResult:
        """Fetch source data and return products in the shared catalog format."""
        raise NotImplementedError
