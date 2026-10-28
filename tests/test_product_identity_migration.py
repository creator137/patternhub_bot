import asyncio
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
import tempfile
import unittest
from app.database import Database
from app.models.product import ParsedProduct,ProductFilter
from app.repositories.products import ProductRepository
from app.snapshots import validate_document

class ProductIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Database(Path(self.tmp.name)/'db.sqlite3');self.db.initialize();self.repo=ProductRepository(self.db)
        self.a=ParsedProduct(source='grasser',source_product_id='shirt',name='Рубашка',product_url='https://grasser.ru/set')
        self.b=replace(self.a,source_product_id='pants',name='Брюки')

    def test_two_real_products_can_share_one_storefront_page(self):
        self.assertEqual(self.repo.upsert_many([self.a,self.b]),(2,0))
        self.assertEqual(self.repo.upsert_many([self.b,self.a]),(0,2))
        self.assertEqual(self.repo.count_products(),2)
        self.assertEqual({p.source_product_id for p in self.repo.list_products()},{'shirt','pants'})

    def test_url_fallback_promoted_without_duplicate_or_id_loss(self):
        self.repo.upsert_many([replace(self.a,source_product_id=None)])
        row=self.repo.list_products()[0]
        self.assertEqual(self.repo.upsert_many([self.a]),(0,1))
        self.assertEqual(self.repo.list_products()[0].id,row.id)
        self.assertEqual(self.repo.upsert_many([replace(self.a,source_product_id=None)]),(0,1))
        self.assertEqual(self.repo.list_products()[0].source_product_id,'shirt')

    def test_fallback_remains_unique_when_no_source_id(self):
        p=replace(self.a,source_product_id=None)
        self.assertEqual(self.repo.upsert_many([p,p]),(1,1))
        self.assertEqual(self.repo.count_products(),1)

    def test_snapshot_accepts_real_distinct_ids_but_rejects_ambiguous_fallback(self):
        products=[dict(source='grasser',source_product_id=p.source_product_id,name=p.name,product_url=p.product_url) for p in [self.a,self.b]]
        doc={'version':1,'sources':[dict(source='grasser',complete=True,observed_at=datetime.now(timezone.utc).isoformat(),products=products)]}
        self.assertEqual(len(validate_document(doc)[0].products),2)
        products[1]['source_product_id']=None
        with self.assertRaises(ValueError):validate_document(doc)

    def test_legacy_migration_preserves_rows_user_relations_and_custom_columns(self):
        self.repo.upsert_many([self.a]);row=self.repo.list_products()[0]
        with self.db.connect() as db:
            db.execute('INSERT INTO favorites(user_id,product_id) VALUES(42,?)',(row.id,))
            db.execute('INSERT INTO product_overrides(product_id,hidden) VALUES(?,1)',(row.id,))
            db.execute("INSERT INTO media_assets(key,url) VALUES('cover','https://grasser.ru/front.jpg')")
            db.execute("INSERT INTO product_media_cache(product_id,asset_key) VALUES(?,'cover')",(row.id,))
            db.execute('ALTER TABLE products ADD COLUMN future_metadata TEXT')
            db.execute("UPDATE products SET future_metadata='keep-me'")
        # Historical full-URL UNIQUE constraint, with real dependent tables.
        with self.db.connect() as db:
            db.execute('PRAGMA foreign_keys=OFF')
            sql=db.execute("SELECT sql FROM sqlite_master WHERE name='products'").fetchone()[0]
            sql=sql.replace('CREATE TABLE products','CREATE TABLE old_products')
            sql=sql[:sql.rfind(')')]+', UNIQUE(source,product_url)'+sql[sql.rfind(')'):]
            db.execute(sql);db.execute('INSERT INTO old_products SELECT * FROM products')
            db.execute('DROP TABLE products');db.execute('ALTER TABLE old_products RENAME TO products')
            db.execute('CREATE INDEX custom_products_name ON products(name)')
            db.execute("UPDATE sqlite_sequence SET seq=9999 WHERE name='products'")
        self.db.initialize();self.db.initialize()
        self.assertEqual(self.repo.upsert_many([self.b]),(1,0))
        self.assertGreater(next(p.id for p in self.repo.list_products() if p.source_product_id=='pants'),9999)
        with self.db.connect() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(db.execute('SELECT product_id FROM favorites').fetchone()[0],row.id)
            self.assertEqual(db.execute('SELECT product_id FROM product_media_cache').fetchone()[0],row.id)
            self.assertEqual(db.execute('SELECT hidden FROM product_overrides').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT future_metadata FROM products WHERE id=?',(row.id,)).fetchone()[0],'keep-me')
            self.assertTrue(db.execute("SELECT 1 FROM sqlite_master WHERE name='custom_products_name'").fetchone())
