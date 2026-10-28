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
        from app.providers.opencart import OpenCartProvider
        from app.providers.bitrix_catalog import BitrixCatalogProvider
        from app.providers.insales_catalog import OctoberCatalogProvider, AnsewsCatalogProvider, ShapeCatalogProvider, LokoCatalogProvider
        from app.providers.wordpress_catalog import WordPressSitemapProvider
        from app.providers.wordpress_posts import WordPressPostsProvider
        from app.providers.tilda_extended import ExtendedTildaProvider
        from app.providers.tilda_api import TildaAPIProvider
        from app.providers.independent_catalogs import PatternEasyProvider, IndependentListingProvider
        from app.providers.lekala_legacy import LekalaLegacyProvider
        from app.providers.shkatulka import ShkatulkaProvider
        from app.providers.taplink import TaplinkProvider
        from app.providers.virtuemart import VirtueMartProvider
        from app.providers.marymake import MarymakeProvider
        from app.providers.burda import BurdaProvider
        from app.providers.easysew import EasySewProvider
        adapters.update(opencart=OpenCartProvider, bitrix_catalog=BitrixCatalogProvider,
            october=OctoberCatalogProvider, ansews=AnsewsCatalogProvider, shape=ShapeCatalogProvider,
            loko=LokoCatalogProvider, wordpress_sitemap=WordPressSitemapProvider,
            wordpress_posts=WordPressPostsProvider, tilda_extended=ExtendedTildaProvider,
            tilda_api=TildaAPIProvider, patterneasy=PatternEasyProvider,
            independent_html=IndependentListingProvider, lekala_legacy=LekalaLegacyProvider,
            shkatulka=ShkatulkaProvider, taplink=TaplinkProvider, virtuemart=VirtueMartProvider,
            marymake=MarymakeProvider, burda=BurdaProvider, easysew=EasySewProvider)
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
