from __future__ import annotations

from app.providers.base import BaseProvider
from app.providers.vikisews import VikiSewsProvider


def create_provider(source: str) -> BaseProvider:
    providers: dict[str, type[BaseProvider]] = {
        "vikisews": VikiSewsProvider,
    }
    try:
        return providers[source]()
    except KeyError as error:
        raise ValueError(f"Unknown or not implemented source: {source}") from error


def available_providers() -> tuple[str, ...]:
    return ("vikisews",)
