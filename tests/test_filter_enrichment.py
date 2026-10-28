from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import json
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

from app.database import Database
from app.models.product import ParsedProduct, ProductFilter
from app.models.filter_facts import description_facts
from app.providers.vikisews import VikiSewsProvider
from app.providers.sewitnow import SewItNowProvider
from app.providers.studio_yusupova import StudioYusupovaProvider
from app.providers.base import FilterSnapshot
from app.repositories.products import ProductRepository
from app.web.catalog import WebCatalogRepository


class FilterEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'catalog.db')
        self.db.initialize()
        self.repo = ProductRepository(self.db)
        self.product = ParsedProduct(source='vikisews', source_product_id='1', name='Фарра худи',
            category='Худи, футболки и лонгсливы', product_url='https://vikisews.com/farra/')

    def tearDown(self):
        self.temp.cleanup()

    def test_listing_preserves_known_detail_flags_and_authoritative_false_clears_them(self):
        self.repo.upsert_many([replace(self.product, is_beginner=True, is_knit=True, difficulty='Новичок', description='Описание')])
        self.repo.upsert_many([self.product])
        product = self.repo.list_products()[0]
        self.assertTrue(product.is_beginner)
        self.assertTrue(product.is_knit)
        self.assertEqual(product.description, 'Описание')
        self.repo.upsert_many([replace(self.product, is_beginner=False, is_knit=False)])
        product = self.repo.list_products()[0]
        self.assertFalse(product.is_beginner)
        self.assertFalse(product.is_knit)
        self.assertEqual(self.repo.count_products(), 1)

    def test_viki_real_novice_tag_and_knit_materials(self):
        html = '''<h1 class="product-main-header">Фарра худи</h1>
        <div class="tags"><a href="?tags=3">Новичок</a><a href="?tags=51">Футер</a></div>
        <button class="accordion" data-target="#materials">Рекомендуемые материалы</button>
        <div id="materials"><div class="panel">Для пошива подойдут трикотажные полотна.</div></div>'''
        self.assertEqual(VikiSewsProvider().parse_filter_metadata(html, self.product.product_url),
                         {'is_beginner': True, 'is_knit': True})
        self.assertFalse(VikiSewsProvider().parse_filter_metadata(html.replace('Новичок','Профессионал'), self.product.product_url)['is_beginner'])
        with self.assertRaises(ValueError):
            VikiSewsProvider().parse_filter_metadata('<h1>Проверка браузера</h1>', self.product.product_url)

    def test_description_facts_do_not_turn_negative_recommendations_into_knit(self):
        self.assertTrue(description_facts('<p>Уровень сложности: 1 из 5</p>')['is_beginner'])
        self.assertFalse(description_facts('Уровень сложности: 3')['is_beginner'])
        self.assertTrue(description_facts('Трикотажное платье прилегающего силуэта.')['is_knit'])
        for text in ('Дублерин на трикотажной основе.', 'Не рекомендуется использовать трикотажные полотна.',
                     'Не подходит для начинающих.'):
            self.assertNotIn(True, description_facts(text).values())
        self.assertFalse(replace(self.product, description='Не подходит для начинающих.').normalized().is_beginner)
        self.assertFalse(replace(self.product, difficulty='Сложность: 10').normalized().is_beginner)

    def test_sew_next_product_description_and_identity(self):
        data = {'props': {'pageProps': {'initProduct': {'slug':'dress', 'description':
            '<h3>Уровень сложности: начальный</h3><p>Трикотажное платье.</p>'}}}}
        html = '<script id="__NEXT_DATA__" type="application/json">'+json.dumps(data)+'</script>'
        facts = SewItNowProvider().parse_filter_metadata(html, 'https://sewitnow.ru/product/dress/')
        self.assertTrue(facts['is_beginner'])
        self.assertTrue(facts['is_knit'])
        with self.assertRaises(ValueError):
            SewItNowProvider().parse_filter_metadata(html, 'https://sewitnow.ru/product/other/')
        data['props']['pageProps']['initProduct'].update(id='842224',slug='bluza-kamila-158-40-842224')
        data['props']['pageProps']['initProduct']['images'] = [{'storage_object':{'url':'https://api.sewitnow.ru/storage/image/real.webp'}}]
        html = '<script id="__NEXT_DATA__">'+json.dumps(data)+'</script>'
        self.assertTrue(SewItNowProvider().parse_filter_metadata(html,'https://sewitnow.ru/product/bluza-kamila-842224/')['is_beginner'])
        self.assertEqual(SewItNowProvider().parse_gallery(html,'https://sewitnow.ru/product/bluza-kamila-842224/'),
                         ('https://api.sewitnow.ru/storage/image/real.webp',))

    def test_studio_keeps_knit_membership_when_another_category_is_primary(self):
        item = {'id':1, 'name':'Юбка Кайя', 'permalink':'https://studio-yusupova.ru/shop/kaia/',
            'categories':[{'id':57,'name':'Платья и юбки'}, {'id':62,'name':'Трикотаж'}],
            'description':'Выкройка трикотажной юбки.'}
        p = StudioYusupovaProvider().parse_products_payload([item])[0]
        self.assertTrue(p.is_knit)

    def test_metadata_is_visible_in_combined_web_filters_and_survives_import(self):
        self.repo.upsert_many([self.product])
        product = self.repo.list_products()[0]
        self.repo.set_filter_metadata(product.id, {'is_beginner':True,'is_knit':True}, expected_url=product.product_url)
        self.repo.upsert_many([self.product])
        result = WebCatalogRepository(self.db).page({'source':'vikisews', 'is_beginner':True,
            'is_knit':True,'category':product.category})
        self.assertEqual(result['total'], 1)
        self.assertEqual(len(self.repo.media_products(galleries=True)),1)  # Gallery still due.
        with self.assertRaises(ValueError):
            self.repo.set_filter_metadata(product.id, {'is_free':True}, expected_url=product.product_url)

    def test_new_first_keeps_all_products_while_new_filter_is_explicit(self):
        self.repo.upsert_many([self.product, replace(self.product, source='sewitnow', name='Я новинка', is_new=True,
            source_published_at=datetime.now(timezone.utc)-timedelta(days=1))])
        repo = WebCatalogRepository(self.db)
        result = repo.page({'sort':'new_first'})
        self.assertEqual(result['total'],2)
        self.assertEqual(result['items'][0]['name'],'Я новинка')
        self.assertEqual(repo.page({'is_new':True})['total'],1)

    def test_incomplete_filter_snapshot_only_adds_known_memberships(self):
        other = replace(self.product,source_product_id='2',name='Другая',product_url='https://vikisews.com/other/',is_beginner=True)
        self.repo.upsert_many([self.product,other])
        self.repo.apply_filter_snapshot('vikisews','is_beginner',FilterSnapshot([self.product],False))
        self.assertEqual(self.repo.count_products(ProductFilter(is_beginner=True)),2)
        self.repo.apply_filter_snapshot('vikisews','is_beginner',FilterSnapshot([self.product],True))
        self.assertEqual(self.repo.count_products(ProductFilter(is_beginner=True)),1)
        self.repo.apply_filter_snapshot('vikisews','is_beginner',FilterSnapshot([],True))
        self.assertEqual(self.repo.count_products(ProductFilter(is_beginner=True)),1)
        with self.assertRaises(ValueError):
            self.repo.apply_filter_snapshot('vikisews','is_beginner',FilterSnapshot([replace(self.product,source='grasser')],True))

    def test_filter_crawl_reports_limits_and_pagination_failures_as_incomplete(self):
        html = (Path(__file__).parent/'fixtures/vikisews_catalog.html').read_text()
        provider = VikiSewsProvider(max_pages=1, request_delay=0)
        provider._get_page = AsyncMock(return_value=html+'<div id="infinite-upload-more" data-link="?page=2"></div>')
        snapshots = asyncio.run(provider.fetch_filter_snapshots())
        self.assertFalse(snapshots['is_beginner'].complete)
        self.assertTrue(snapshots['is_beginner'].products)
        provider._get_page = AsyncMock(return_value=html.replace('id="infinite-upload-more"','id="not-pagination"'))
        snapshots = asyncio.run(provider.fetch_filter_snapshots())
        self.assertTrue(snapshots['is_beginner'].complete)
        provider._get_page = AsyncMock(return_value=None)
        self.assertFalse(asyncio.run(provider.fetch_filter_snapshots())['is_knit'].complete)

    def test_absent_detail_tag_cannot_erase_current_complete_section_membership(self):
        self.repo.upsert_many([self.product])
        p = self.repo.list_products()[0]
        self.repo.apply_filter_snapshot('vikisews','is_beginner',FilterSnapshot([self.product],True))
        self.repo.set_filter_metadata(p.id,{'is_beginner':False},expected_url=p.product_url)
        self.assertTrue(self.repo.get_product(p.id).is_beginner)
        self.repo.upsert_many([replace(self.product,is_beginner=False)])
        self.assertTrue(self.repo.get_product(p.id).is_beginner)
        with self.db.connect() as db:
            db.execute("UPDATE source_filter_snapshots SET checked_at=datetime('now','-2 day')")
        self.repo.set_filter_metadata(p.id,{'is_beginner':False},expected_url=p.product_url)
        self.assertFalse(self.repo.get_product(p.id).is_beginner)
