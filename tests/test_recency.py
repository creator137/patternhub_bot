import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from app.database import Database
from app.models.product import ParsedProduct
from app.models.recency import RecencySnapshot
from app.providers.grasser import GrasserProvider
from app.providers.base import ProviderResult
from app.providers.helpersew import HelperSewProvider
from app.providers.studio_yusupova import StudioYusupovaProvider
from app.providers.vikisews import VikiSewsProvider
from app.repositories.products import ProductRepository
from app.services.catalog import CatalogService
from app.web.catalog import WebCatalogRepository


FIXTURES = Path(__file__).parent / 'fixtures'


class RecencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'catalog.sqlite3')
        self.db.initialize()
        self.repo = ProductRepository(self.db)
        self.web = WebCatalogRepository(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def product(self, key, *, source='grasser', name=None, **facts):
        return ParsedProduct(source=source, source_product_id=str(key),
            name=name or str(key), product_url=f'https://example.com/{source}/{key}/',
            audience='women', category='Брюки и шорты', **facts)

    def order(self, products, *, complete=True):
        return RecencySnapshot.from_products(products[0].source, products,
            basis='source_catalog_order', complete=complete)

    def test_customer_combination_keeps_all_knit_pants_and_orders_old_items_too(self):
        products = [self.product(3, name='Я новая', is_knit=True),
                    self.product(2, name='Б старая', is_knit=True),
                    self.product(1, name='А самая старая', is_knit=True),
                    self.product(4, name='Не трикотаж', is_knit=False)]
        self.repo.upsert_many(products)
        self.repo.apply_recency_snapshot('grasser', self.order(products))
        query = {'source':'grasser', 'category':'Брюки и шорты', 'is_knit':True, 'sort':'new_first'}
        result = self.web.page(query)
        self.assertEqual(result['total'], 3)
        self.assertEqual([p['source_product_id'] for p in result['items']], ['3','2','1'])
        self.assertTrue(all(not p['is_new'] for p in result['items']))
        self.assertEqual(self.web.page(query | {'sort':'name'})['total'], result['total'])
        self.assertEqual(self.web.page(query | {'is_new':True})['total'], 0)

    def test_rank_survives_upsert_and_incomplete_or_truncated_snapshots(self):
        products = [self.product(i) for i in range(20)]
        self.repo.upsert_many(products)
        self.repo.apply_recency_snapshot('grasser', self.order(products[::-1]))
        self.repo.upsert_many(products)
        self.assertEqual(self.repo.apply_recency_snapshot('grasser', self.order(products, complete=False)), 0)
        self.assertEqual(self.repo.apply_recency_snapshot('grasser', self.order(products[:2])), 0)
        result = self.web.page({'sort':'new_first'})
        self.assertEqual(result['items'][0]['source_product_id'], '19')

    def test_reordered_snapshot_is_atomic_and_does_not_change_availability(self):
        products = [self.product(i) for i in range(4)]
        self.repo.upsert_many(products)
        self.repo.apply_recency_snapshot('grasser', self.order(products))
        self.repo.apply_recency_snapshot('grasser', self.order(products[::-1]))
        self.assertEqual([p['source_product_id'] for p in self.web.page({'sort':'new_first'})['items']], ['3','2','1','0'])
        self.assertEqual(self.repo.stats().available, 4)
        self.assertEqual(self.web.coverage()['recency_ordered'], 4)

    def test_mixed_sources_interleave_without_using_import_dates_or_raw_id_magnitudes(self):
        products = [self.product(i, source=source, is_knit=True)
                    for source in ['vikisews','grasser','helpersew','studio_yusupova','sewitnow'] for i in [1,2]]
        self.repo.upsert_many(products)
        for source in {p.source for p in products}:
            subset = [p for p in products if p.source == source]
            self.repo.apply_recency_snapshot(source, self.order(subset[::-1]))
        result = self.web.page({'sort':'new_first', 'limit':10})
        self.assertEqual(len({p['source'] for p in result['items'][:5]}), 5)
        self.assertEqual([p['source_recency_rank'] for p in result['items']], [0]*5+[1]*5)
        first = self.web.page({'sort':'new_first', 'limit':3})['items']
        second = self.web.page({'sort':'new_first', 'limit':3, 'offset':3})['items']
        self.assertEqual([p['id'] for p in first+second], [p['id'] for p in result['items'][:6]])

    def test_unavailable_products_are_not_visible_and_other_source_cannot_be_overwritten(self):
        products = [self.product(1), self.product(2, is_available=False)]
        self.repo.upsert_many(products)
        self.repo.apply_recency_snapshot('grasser', self.order(products))
        self.assertEqual(self.web.page({'sort':'new_first'})['total'], 1)
        with self.assertRaises(ValueError):
            self.repo.apply_recency_snapshot('helpersew', self.order(products))

    def test_helper_uses_its_own_numeric_id_sort_not_names(self):
        products = [self.product(9, source='helpersew'), self.product(100, source='helpersew')]
        snapshot = asyncio.run(HelperSewProvider().fetch_recency_snapshot(products))
        self.assertEqual(snapshot.keys, ('100','9'))
        self.assertTrue(snapshot.complete)
        self.assertFalse(asyncio.run(HelperSewProvider().fetch_recency_snapshot(
            [self.product('invalid', source='helpersew')])).complete)

    def test_date_sort_includes_old_publications_and_rejects_missing_dates(self):
        now = datetime.now(timezone.utc)
        products = [self.product(1, source='studio_yusupova', source_published_at=now-timedelta(days=900)),
                    self.product(2, source='studio_yusupova', source_published_at=now-timedelta(days=180))]
        snapshot = asyncio.run(StudioYusupovaProvider().fetch_recency_snapshot(products))
        self.assertEqual(snapshot.keys, ('2','1'))
        self.assertTrue(snapshot.complete)
        self.assertFalse(asyncio.run(StudioYusupovaProvider().fetch_recency_snapshot(
            [products[0], replace(products[1], source_published_at=None)])).complete)

    def test_grasser_crawls_every_page_with_explicit_sort_and_preserves_order(self):
        provider = GrasserProvider()
        header = '<a class="sort__one active desc">Новизне</a>'
        first = header + (FIXTURES/'grasser_catalog.html').read_text()
        second = header + (FIXTURES/'grasser_catalog.html').read_text().split('<span class="full-button')[0]
        second = second.replace('153947','150000').replace('153787','140000')
        provider._get_page = AsyncMock(side_effect=[first, second])
        snapshot = asyncio.run(provider.fetch_recency_snapshot([]))
        self.assertTrue(snapshot.complete)
        self.assertEqual(snapshot.keys, ('153947','153787','150000','140000'))
        second_url = provider._get_page.call_args_list[1].args[1]
        self.assertIn('SORT=SORT', second_url)
        self.assertIn('ORDER_BY=DESC', second_url)
        self.assertIn('PAGEN_3=2', second_url)

    def test_grasser_repeated_pages_or_wrong_sort_are_incomplete(self):
        html = (FIXTURES/'grasser_catalog.html').read_text()
        provider = GrasserProvider()
        provider._get_page = AsyncMock(return_value='<a class="sort__one active desc">Новизне</a>'+html)
        self.assertFalse(asyncio.run(provider.fetch_recency_snapshot([])).complete)
        provider = GrasserProvider()
        provider._get_page = AsyncMock(return_value=html.split('<span class="full-button')[0])
        self.assertFalse(asyncio.run(provider.fetch_recency_snapshot([])).complete)

    def test_grasser_bad_card_does_not_claim_a_complete_order(self):
        html = (FIXTURES/'grasser_catalog.html').read_text().split('<span class="full-button')[0]
        html = html.replace('<div class="catalog vykrojki">',
                            '<a class="sort__one active desc">Новизне</a><div class="catalog vykrojki"><div class="catalog-block">broken</div>')
        provider = GrasserProvider()
        provider._get_page = AsyncMock(return_value=html)
        self.assertFalse(asyncio.run(provider.fetch_recency_snapshot([])).complete)

    def test_viki_uses_entire_catalog_and_never_overwrites_order_after_failed_page(self):
        provider = VikiSewsProvider(request_delay=0)
        html = (FIXTURES/'vikisews_catalog.html').read_text()
        second = html.split('<div id="infinite-upload-more"')[0].replace('7153','7000').replace('7152','6000')
        provider._get_page = AsyncMock(side_effect=[html, second])
        snapshot = asyncio.run(provider.fetch_recency_snapshot([]))
        self.assertTrue(snapshot.complete)
        self.assertEqual(snapshot.keys, ('7153','7152','7000','6000'))
        provider = VikiSewsProvider(request_delay=0)
        provider._get_page = AsyncMock(side_effect=[html, None])
        self.assertFalse(asyncio.run(provider.fetch_recency_snapshot([])).complete)

    def test_service_refresh_only_reorders_existing_records(self):
        products = [self.product(9, source='helpersew'),self.product(100, source='helpersew')]
        self.repo.upsert_many(products)
        result = asyncio.run(CatalogService(self.repo).refresh_recency(HelperSewProvider()))
        self.assertEqual(result['ranked'], 2)
        self.assertEqual(self.repo.stats().total, 2)
        self.assertEqual(self.repo.stats().available, 2)

    def test_complete_import_updates_order_automatically_but_partial_import_keeps_last_order(self):
        provider = HelperSewProvider()
        products = [self.product(1, source='helpersew'), self.product(2, source='helpersew')]
        provider.fetch_products = AsyncMock(return_value=ProviderResult(products, complete=True))
        service = CatalogService(self.repo)
        asyncio.run(service.synchronize(provider))
        newest = self.product(100, source='helpersew')
        provider.fetch_products = AsyncMock(return_value=ProviderResult(products+[newest], complete=True))
        asyncio.run(service.synchronize(provider))
        self.assertEqual([p['source_product_id'] for p in self.web.page({'sort':'new_first'})['items']], ['100','2','1'])
        provider.fetch_products = AsyncMock(return_value=ProviderResult([newest], complete=False))
        asyncio.run(service.synchronize(provider))
        self.assertEqual([p['source_product_id'] for p in self.web.page({'sort':'new_first'})['items']], ['100','2','1'])
