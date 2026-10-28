import asyncio
from datetime import datetime, timezone, timedelta
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from contextlib import contextmanager
import sqlite3
import httpx

from app.database import Database
from app.models.product import ParsedProduct, ProductFilter
from app.models.catalog_policy import is_recent_publication, publication_datetime
from app.providers.publication import product_publication_date
from app.providers.studio_yusupova import StudioYusupovaProvider
from app.providers.sewitnow import SewItNowProvider
from app.repositories.products import ProductRepository
from app.web.catalog import WebCatalogRepository
from app.handlers.catalog import format_price


class CatalogPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name)/'catalog.db')
        self.db.initialize()
        self.repo = ProductRepository(self.db)
        self.web = WebCatalogRepository(self.db)
        self.p = ParsedProduct(source='grasser',source_product_id='1',name='Модель',category='Платья',
            currency='RUB',product_url='https://grasser.ru/product/1/')

    def tearDown(self):
        self.temp.cleanup()

    def test_free_selection_includes_one_ruble_without_claiming_it_is_zero(self):
        prices = [Decimal('0'),Decimal('1'),Decimal('2'),None,Decimal('1')]
        self.repo.upsert_many([replace(self.p,source_product_id=str(i),product_url=f'https://grasser.ru/product/{i}/',
            price=price,currency='USD' if i==4 else 'RUB') for i,price in enumerate(prices)])
        items = self.repo.list_products(filters=ProductFilter(is_free=True))
        self.assertEqual({p.source_product_id for p in items},{'0','1'})
        one = next(p for p in items if p.price == 1)
        self.assertFalse(one.is_free)
        self.assertEqual(format_price(one),'💰 1 ₽')
        self.assertEqual(self.web.page({'is_free':True})['total'],2)
        self.assertEqual(self.repo.count_products(ProductFilter(is_free=False)),3)
        self.assertEqual(self.web.coverage()['counts']['is_free'],2)
        self.assertEqual(self.repo.stats().free,1)  # Actual zero-price count remains precise.

    def test_publication_window_boundaries_timezone_invalid_and_future_dates(self):
        now = datetime(2026,10,28,12,tzinfo=timezone.utc)
        self.assertTrue(is_recent_publication(now-timedelta(days=60),now=now))
        self.assertFalse(is_recent_publication(now-timedelta(days=60,seconds=1),now=now))
        self.assertFalse(is_recent_publication(now+timedelta(seconds=1),now=now))
        self.assertFalse(is_recent_publication(None,now=now))
        self.assertIsNone(publication_datetime('not-a-date'))
        self.assertEqual(publication_datetime('2026-10-28T15:00:00+03:00'),now)

    def test_newness_uses_publication_not_badge_import_or_updated_date(self):
        now = datetime.now(timezone.utc)
        cases = [('new',now-timedelta(days=30),False),('old',now-timedelta(days=61),True),
                 ('unknown',None,True),('future',now+timedelta(days=1),True)]
        self.repo.upsert_many([replace(self.p,source_product_id=key,product_url=f'https://grasser.ru/{key}/',
            source_published_at=date,is_new=badge,source_updated_at=now) for key,date,badge in cases])
        items = self.repo.list_products(filters=ProductFilter(is_new=True))
        self.assertEqual([p.source_product_id for p in items],['new'])
        self.assertTrue(items[0].is_new)
        unknown = next(p for p in self.repo.list_products() if p.source_product_id=='unknown')
        self.assertFalse(unknown.is_new)
        self.assertTrue(unknown.source_new_badge)
        self.assertEqual(self.web.page({'is_new':True})['total'],1)
        self.assertEqual(self.web.coverage()['counts']['is_new'],1)
        self.assertEqual(self.repo.stats().new,1)

    def test_date_is_preserved_on_listing_upsert_and_expires_without_import(self):
        self.repo.upsert_many([replace(self.p,source_published_at=datetime.now(timezone.utc)-timedelta(days=1))])
        self.repo.upsert_many([self.p])
        self.assertTrue(self.repo.list_products()[0].is_new)
        with self.db.connect() as db:
            db.execute("UPDATE products SET source_published_at=datetime('now','-61 day')")
        self.assertFalse(self.repo.list_products()[0].is_new)
        self.assertEqual(self.repo.count_products(ProductFilter(is_new=True)),0)

    def test_product_date_metadata_excludes_reviews_modified_and_other_products(self):
        url='https://example.com/product/one/'
        data={'@graph':[{'@type':'Review','datePublished':'2026-10-28'},
            {'@type':'Product','url':'https://another.example/product/one/','datePublished':'2026-10-28'},
            {'@type':'Product','url':'https://example.com/product/other/','datePublished':'2026-10-28'},
            {'@type':'Product','url':url,'dateModified':'2026-10-28'}]}
        html='<script type="application/ld+json">'+json.dumps(data)+'</script>'
        self.assertIsNone(product_publication_date(html,url))
        data['@graph'][-1]['datePublished']='2020-01-02T10:00:00Z'
        html='<script type="application/ld+json">'+json.dumps(data)+'</script>'
        self.assertEqual(product_publication_date(html,url).year,2020)

    def test_bulk_date_update_does_not_mark_detail_filters_as_checked(self):
        self.repo.upsert_many([self.p])
        product = self.repo.list_products()[0]
        self.repo.set_filter_metadata(product.id,
            {'source_published_at': datetime.now(timezone.utc)-timedelta(seconds=1)}, expected_url=product.product_url)
        with self.db.connect() as db:
            row = db.execute('SELECT filters_checked_at,is_new FROM products WHERE id=?',
                             (product.id,)).fetchone()
        self.assertIsNone(row['filters_checked_at'])
        self.assertEqual(row['is_new'], 1)

    def test_migration_preserves_legacy_badge_without_fabricating_publication(self):
        self.repo.upsert_many([self.p])
        with self.db.connect() as db:
            db.execute('UPDATE products SET is_new=1')
            db.execute('ALTER TABLE products DROP COLUMN source_new_badge')
        self.db.initialize()
        product=self.repo.list_products()[0]
        self.assertTrue(product.source_new_badge)
        self.assertFalse(product.is_new)
        self.assertIsNone(product.source_published_at)
        with self.db.connect() as db:
            self.assertEqual(db.execute('SELECT is_new FROM products').fetchone()[0],0)

    def test_failed_badge_migration_rolls_back_schema_and_can_be_retried(self):
        self.repo.upsert_many([self.p])
        with self.db.connect() as db:
            db.execute('UPDATE products SET is_new=1')
            db.execute('ALTER TABLE products DROP COLUMN source_new_badge')
        connect = self.db.connect
        @contextmanager
        def denied_copy():
            with connect() as db:
                db.set_authorizer(lambda action,table,column,*args:
                    sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_UPDATE and table=='products' and column=='source_new_badge' else sqlite3.SQLITE_OK)
                yield db
        with patch.object(self.db,'connect',denied_copy):
            with self.assertRaises(sqlite3.DatabaseError):
                self.db.initialize()
        with connect() as db:
            self.assertNotIn('source_new_badge',{r['name'] for r in db.execute('PRAGMA table_info(products)')})
            self.assertEqual(db.execute('SELECT is_new FROM products').fetchone()[0],1)
        self.db.initialize()
        self.assertTrue(self.repo.list_products()[0].source_new_badge)

    def test_new_first_does_not_group_old_dated_brand_above_unknown_dates(self):
        now=datetime.now(timezone.utc)
        cases=[('new','Новая',now-timedelta(days=1)),('old','Я старая',now-timedelta(days=90)),('unknown','А без даты',None)]
        self.repo.upsert_many([replace(self.p,source_product_id=key,name=name,product_url=f'https://grasser.ru/{key}/',source_published_at=date) for key,name,date in cases])
        self.assertEqual([p['name'] for p in self.web.page({'sort':'new_first'})['items']],['Новая','А без даты','Я старая'])

    def test_studio_publication_api_is_paginated_and_ignores_modified_date(self):
        provider=StudioYusupovaProvider()
        provider._get_json=AsyncMock(side_effect=[
            ([{'id':1,'date_gmt':'2020-01-01T12:00:00','modified_gmt':'2026-10-28T00:00:00'}],httpx.Headers({'X-WP-TotalPages':'2'})),
            ([{'id':2,'date_gmt':'2026-10-10T09:50:09'}],httpx.Headers({'X-WP-TotalPages':'2'}))])
        dates=asyncio.run(provider.fetch_publication_dates(None))
        self.assertEqual(dates['1'].year,2020)
        self.assertEqual(dates['2'].month,10)
        self.assertEqual(provider._get_json.await_count,2)
        self.assertIn('page=2',provider._get_json.call_args.args[1])

    def test_sew_public_graphql_dates_page_by_sku_and_ignore_updates(self):
        provider=SewItNowProvider()
        provider._seller_id='532'
        provider._get_json=AsyncMock(side_effect=[
            {'data':{'getProducts':{'page':1,'pages':2,'elements':2,'list':[
                {'id':'842224','created_at':'2024-09-07 16:43:09','updated_at':'2026-10-28 00:00:00'}]}}},
            {'data':{'getProducts':{'page':2,'pages':2,'elements':2,'list':[
                {'id':'1158528','created_at':'2026-09-28 12:18:08'}]}}}])
        dates=asyncio.run(provider.fetch_publication_dates(None))
        self.assertEqual(dates['842224'].year,2024)
        self.assertEqual(dates['1158528'].isoformat(),'2026-09-28T12:18:08+00:00')
        p=replace(self.p,source='sewitnow',source_product_id='1105985',
            product_url='https://sewitnow.ru/product/bryuki-yudza-1158528/')
        self.assertEqual(provider.publication_key(p),'1158528')
        self.assertEqual(provider._get_json.await_count,2)

    def test_sew_publication_errors_and_repeated_pages_do_not_fabricate_dates(self):
        provider=SewItNowProvider();provider._seller_id='532'
        provider._get_json=AsyncMock(return_value={'errors':[{'message':'unavailable'}]})
        self.assertEqual(asyncio.run(provider.fetch_publication_dates(None)),{})
        first={'data':{'getProducts':{'page':1,'pages':2,'elements':2,'list':[
            {'id':'1','created_at':'2020-01-01'}]}}}
        provider._get_json=AsyncMock(return_value=first)
        self.assertEqual(set(asyncio.run(provider.fetch_publication_dates(None))),{'1'})
        self.assertEqual(provider._get_json.await_count,2)
