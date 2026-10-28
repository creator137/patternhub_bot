from __future__ import annotations

import inspect

from app.providers.base import BaseProvider
from app.providers.grasser import GrasserProvider
from app.providers.helpersew import HelperSewProvider
from app.providers.sewitnow import SewItNowProvider
from app.providers.studio_yusupova import StudioYusupovaProvider
from app.providers.vikisews import VikiSewsProvider
from app.suppliers import supplier_definition, supplier_definitions


def create_provider(source: str, **kwargs: object) -> BaseProvider:
    providers: dict[str, type[BaseProvider]] = {
        "vikisews": VikiSewsProvider,
        "grasser": GrasserProvider,
        "helpersew": HelperSewProvider,
        "studio_yusupova": StudioYusupovaProvider,
        "sewitnow": SewItNowProvider,
    }
    if source not in providers:
        from app.providers.public_stores import WooStoreProvider, WooHTMLProvider, TildaSitemapProvider, VigboProvider
        definition = supplier_definition(source)
        adapters = {'woo_store':WooStoreProvider, 'woo_html':WooHTMLProvider, 'tilda_sitemap':TildaSitemapProvider,'vigbo':VigboProvider}
        if not definition or definition.get('adapter') not in adapters:
            raise ValueError(f"Unknown or not implemented source: {source}")
        return adapters[definition['adapter']](definition,
            **{key:value for key,value in kwargs.items() if key in {'max_pages','transport'}})
    provider_class = providers[source]
    signature = inspect.signature(provider_class)
    supported_kwargs = {
        key: value for key, value in kwargs.items() if key in signature.parameters
    }
    return provider_class(**supported_kwargs)


def available_providers() -> tuple[str, ...]:
    original = ("vikisews", "grasser", "helpersew", "studio_yusupova", "sewitnow")
    return original + tuple(item['source'] for item in supplier_definitions()
                            if item.get('adapter') not in {None,'existing'} and item['enabled'])
