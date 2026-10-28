import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest

from app.database import Database
from app.repositories.products import ProductRepository
from app.services.catalog import CatalogService
from app.snapshots import apply_document, validate_document


class SnapshotTests(unittest.TestCase):
    def document(self):
        return {'version':1,'sources':[{'source':'grasser','complete':True,
            'observed_at':datetime.now(timezone.utc).isoformat(),
            'products':[{'source':'grasser','source_product_id':'new','name':'Платье',
                'product_url':'https://grasser.ru/product/new','price':'300','currency':'RUB'}]}]}

    def test_repeat_import_uses_common_upsert_without_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            db=Database(Path(temp)/'db.sqlite3');db.initialize();repo=ProductRepository(db)
            service=CatalogService(repo)
            first=asyncio.run(apply_document(self.document(),service))
            second=asyncio.run(apply_document(self.document(),service))
            self.assertEqual((first[0].added,second[0].added,second[0].updated),(1,0,1))
            self.assertEqual(repo.stats().total,1)

    def test_incomplete_stale_wrong_origin_and_unknown_source_are_rejected(self):
        for case in ['incomplete','stale','origin','source']:
            doc=self.document();entry=doc['sources'][0]
            if case=='incomplete':entry['complete']=False
            elif case=='stale':entry['observed_at']=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
            elif case=='origin':entry['products'][0]['product_url']='https://unrelated.example/product'
            else:entry['products'][0]['source']='vikisews'
            with self.assertRaises(ValueError):validate_document(doc)

    def test_import_timestamp_is_not_a_publication_date(self):
        provider=validate_document(self.document())[0]
        self.assertIsNone(provider.products[0].source_published_at)
        self.assertFalse(provider.products[0].is_new)
