from __future__ import annotations

import inspect

from app.providers.base import BaseProvider
from app.providers.grasser import GrasserProvider
from app.providers.helpersew import HelperSewProvider
from app.providers.sewitnow import SewItNowProvider
from app.providers.studio_yusupova import StudioYusupovaProvider
from app.providers.vikisews import VikiSewsProvider


def create_provider(source: str, **kwargs: object) -> BaseProvider:
    providers: dict[str, type[BaseProvider]] = {
        "vikisews": VikiSewsProvider,
        "grasser": GrasserProvider,
        "helpersew": HelperSewProvider,
        "studio_yusupova": StudioYusupovaProvider,
        "sewitnow": SewItNowProvider,
    }
    try:
        provider_class = providers[source]
    except KeyError as error:
        raise ValueError(f"Unknown or not implemented source: {source}") from error
    signature = inspect.signature(provider_class)
    supported_kwargs = {
        key: value for key, value in kwargs.items() if key in signature.parameters
    }
    return provider_class(**supported_kwargs)


def available_providers() -> tuple[str, ...]:
    return ("vikisews", "grasser", "helpersew", "studio_yusupova", "sewitnow")
