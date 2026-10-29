from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.database import Database
from app.models.product import ParsedProduct
from app.repositories.products import ProductRepository
from app.suppliers import supplier_definitions
from app.web.auth import WebSettings
from app.web.main import create_app
from app.models.categories import normalize_product_category
from app.handlers.catalog import create_main_keyboard
from app.services.images import MEDIA_HOSTS
from app.web.catalog import FILTERS, MENUS, WebCatalogRepository


class SupplierTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Database(Path(self.temp.name)/'test.sqlite3')
        self.db.initialize();self.repo=ProductRepository(self.db)
        self.client=TestClient(create_app(self.db,WebSettings()))

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    def test_inventory_has_unique_sources_and_repurposed_domains_are_hidden(self):
        definitions=supplier_definitions()
        self.assertEqual(len(definitions),90);self.assertEqual(len({d['source'] for d in definitions}),90)
        public=self.client.get('/api/suppliers').json()
        self.assertEqual(len(public),88)
        self.assertNotIn('andrianova_pattern',{p['source'] for p in public})
        self.assertNotIn('sew_garmentfactory',{p['source'] for p in public})
        mary=next(p for p in public if p['source']=='marymake')
        self.assertIn('marymake.ru',mary['url'])

    def test_all_controls_are_restored_and_admin_visibility_is_respected(self):
        meta=self.client.get('/api/meta').json()
        self.assertEqual({f['key'] for f in meta['ui']['filters'] if f['enabled']},set(FILTERS)-{'is_new'})
        self.assertEqual({m['key'] for m in meta['ui']['menu'] if m['enabled']},set(MENUS))
        self.assertEqual(meta['supplier_count'],88)
        for item in meta['ui']['filters']:
            if item['key']=='is_knit':item['enabled']=False
        WebCatalogRepository(self.db).save_settings(meta['ui'])
        public=self.client.get('/api/meta').json()['ui']
        self.assertFalse(next(item['enabled'] for item in public['filters'] if item['key']=='is_knit'))
        self.assertTrue(next(item['enabled'] for item in public['filters'] if item['key']=='is_beginner'))

    def test_directory_counts_only_public_available_products(self):
        self.repo.upsert_many([ParsedProduct(source='grasser',source_product_id='1',name='Платье',product_url='https://grasser.ru/1'),
                              ParsedProduct(source='grasser',source_product_id='2',name='Юбка',product_url='https://grasser.ru/2',is_available=False)])
        sources=self.client.get('/api/suppliers').json()
        self.assertEqual(next(s for s in sources if s['source']=='grasser')['products'],1)
        self.assertTrue(any(s['products']==0 for s in sources))
        with self.db.connect() as db:db.execute("UPDATE sources SET enabled=0 WHERE name='grasser'")
        self.db.initialize()
        self.assertNotIn('grasser',{s['source'] for s in self.client.get('/api/suppliers').json()})

    def test_brand_order_is_case_insensitive(self):
        with self.db.connect() as db:
            for source,name in [('test_a','alpha'),('test_b','Beta'),('test_z','zeta')]:
                db.execute('INSERT INTO sources(name,display_name,base_url,enabled) VALUES(?,?,?,1)',(source,name,'https://example.com'))
        names=[s['name'] for s in self.client.get('/api/suppliers').json()]
        self.assertLess(names.index('alpha'),names.index('Beta'));self.assertLess(names.index('Beta'),names.index('zeta'))

    def test_audited_catalog_media_hosts_are_allowed_without_trusting_arbitrary_links(self):
        self.assertIn('lekamarket.ru',MEDIA_HOSTS)
        self.assertIn('cdn-sh1.vigbo.com',MEDIA_HOSTS)
        self.assertNotIn('andrianova-pattern.ru',MEDIA_HOSTS)
        self.assertNotIn('127.0.0.1',MEDIA_HOSTS)

    def test_telegram_miniapp_menu_has_only_catalog_suppliers_and_home(self):
        keyboard=create_main_keyboard(miniapp_url='https://example.com/')
        self.assertEqual([button.text for row in keyboard.keyboard for button in row],['Открыть каталог','Производители','🏠 Главное меню'])
        self.assertEqual(keyboard.keyboard[1][0].web_app.url,'https://example.com/?section=suppliers')

    def test_existing_bags_are_migrated_without_erasing_admin_overrides(self):
        self.repo.upsert_many([ParsedProduct(source='vikisews',name='Сумка Феба',source_product_id='bag',product_url='https://vikisews.com/bag',category='Аксессуары')])
        with self.db.connect() as db:
            db.execute("UPDATE products SET category='Аксессуары'")
            db.execute("DELETE FROM settings WHERE key='taxonomy.bags.v1'")
            db.execute("INSERT INTO product_overrides(product_id,hidden,category) VALUES(1,0,'Аксессуары')")
        self.db.initialize()
        self.assertEqual(self.repo.get_product(1).category,'Сумки и рюкзаки')
        self.assertEqual(self.client.get('/api/products/1').json()['category'],'Аксессуары')
        self.assertEqual(normalize_product_category('Аксессуары','Берет Рика'),'Аксессуары')
