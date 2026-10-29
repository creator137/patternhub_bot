from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from app.database import Database
from app.repositories.analytics import AnalyticsRepository
from app.web.main import create_app
from app.web.auth import WebSettings
from test_web import signed


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db=Database(Path(self.tmp.name)/'catalog.sqlite3')
        self.client=TestClient(create_app(self.db,WebSettings('test-token',frozenset({42}))))
        self.addCleanup(self.client.close)
        self.auth={'X-Telegram-Init-Data':signed()}
        self.repo=AnalyticsRepository(self.db)
        with self.db.connect() as db:
            self.product=db.execute("INSERT INTO products(source,name,product_url) VALUES('grasser','Test','https://grasser.ru/test')").lastrowid

    def event(self,kind='open',user=42,**values):
        return self.client.post('/api/events',headers={'X-Telegram-Init-Data':signed(user)},
                                json=dict({'event_id':str(uuid4()),'kind':kind},**values))

    def summary(self,days=30):
        response=self.client.get('/api/admin/analytics',params={'days':days},headers=self.auth)
        self.assertEqual(response.status_code,200)
        return response.json()

    def test_empty_days_and_auth(self):
        for headers,status in [({},401),({'X-Telegram-Init-Data':signed(99)},403)]:
            self.assertEqual(self.client.get('/api/admin/analytics',headers=headers).status_code,status)
        data=self.summary(7)
        self.assertEqual((data['users'],data['opens'],data['clicks']),(0,0,0))
        self.assertIsNone(data['since']);self.assertEqual(len(data['daily']),7)
        for days in (0,91):
            self.assertEqual(self.client.get('/api/admin/analytics',params={'days':days},headers=self.auth).status_code,422)

    def test_unique_users_repeats_and_server_attribution(self):
        self.event();self.event();self.event(user=99)
        self.assertEqual(self.event('outbound',product_id=self.product,source='vikisews').status_code,200)
        self.event('outbound',source='grasser');self.event('outbound',user=99,source='helpersew')
        data=self.summary()
        self.assertEqual((data['users'],data['opens'],data['clicks'],data['outbound_users']),(2,3,3,2))
        self.assertEqual(data['sources'][0],dict(source='grasser',name='Grasser',clicks=2,users=1))
        self.assertEqual(data['daily'][-1]['users'],2)
        self.assertEqual(data['daily'][-1]['clicks'],3)

    def test_retry_deduplication_is_per_user(self):
        event_id=str(uuid4())
        for user in (42,42,99):
            self.assertEqual(self.event(event_id=event_id,user=user).status_code,200)
        self.assertEqual(self.summary()['opens'],2)
        self.db.initialize()
        self.assertEqual(self.summary()['opens'],2)

    def test_invalid_untrusted_and_missing_events(self):
        self.assertEqual(self.client.post('/api/events',json={'event_id':str(uuid4()),'kind':'open'}).status_code,401)
        self.assertEqual(self.event(event_id='bad').status_code,422)
        self.assertEqual(self.event('purchase').status_code,422)
        self.assertEqual(self.event(user_id=99).status_code,422)
        self.assertEqual(self.event('outbound').status_code,422)
        self.assertEqual(self.event('outbound',source='absent').status_code,404)
        self.assertEqual(self.event('outbound',product_id=9999999).status_code,404)
        self.assertEqual(self.summary()['users'],0)

    def test_hidden_unavailable_and_disabled_destinations_not_counted(self):
        with self.db.connect() as db:
            db.execute('UPDATE products SET is_available=0 WHERE id=?',(self.product,))
        self.assertEqual(self.event('outbound',product_id=self.product).status_code,404)
        with self.db.connect() as db:
            db.execute('UPDATE products SET is_available=1 WHERE id=?',(self.product,))
            db.execute('INSERT INTO product_overrides(product_id,hidden) VALUES(?,1)',(self.product,))
        self.assertEqual(self.event('outbound',product_id=self.product).status_code,404)
        with self.db.connect() as db:
            db.execute("UPDATE sources SET enabled=0 WHERE name='grasser'")
        self.assertEqual(self.event('outbound',source='grasser').status_code,404)

    def test_period_and_renamed_source(self):
        self.event();self.event('outbound',source='grasser')
        with self.db.connect() as db:
            db.execute("UPDATE analytics_events SET created_at=datetime('now','-8 days') WHERE kind='open'")
            db.execute("UPDATE sources SET display_name='Новое имя' WHERE name='grasser'")
        self.assertEqual(self.summary(7)['opens'],0)
        self.assertEqual(self.summary(30)['opens'],1)
        self.assertEqual(self.summary()['sources'][0]['name'],'Новое имя')

    def test_no_usernames_or_ips_saved(self):
        self.event()
        with self.db.connect() as db:
            columns={r['name'] for r in db.execute('PRAGMA table_info(analytics_events)')}
        self.assertFalse(columns & {'username','ip','first_name','last_name'})
