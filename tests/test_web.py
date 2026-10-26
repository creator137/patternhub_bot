import hashlib
import hmac
import json
from pathlib import Path
import tempfile
import time
import unittest
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from app.database import Database
from app.models.product import ParsedProduct
from app.repositories.products import ProductRepository
from app.web.auth import WebSettings, telegram_user
from app.web.main import create_app
from app.repositories.media import MediaRepository
from app.services.images import image_key
from unittest.mock import AsyncMock, patch


def signed(user_id=42, age=0, username=None):
    user = {"id": user_id}
    if username is not None:
        user["username"] = username
    values = {"auth_date": str(int(time.time()) - age), "user": json.dumps(user), "query_id": "test"}
    key = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(key, "\n".join(f"{k}={v}" for k, v in sorted(values.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.sqlite3")
        self.db.initialize()
        self.repo = ProductRepository(self.db)
        self.p = ParsedProduct(source="vikisews", source_product_id="1", name="Платье Лето", product_url="https://example.com/a", category="Платья", audience="women", is_new=True)
        self.repo.upsert_many([self.p, ParsedProduct(source="grasser", source_product_id="2", name="Жакет", product_url="https://example.com/b", category="Жакеты", audience="men")])
        self.client = TestClient(create_app(self.db, WebSettings("test-token", frozenset({42}))))
        self.auth = {"X-Telegram-Init-Data": signed()}

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_combined_filters_and_unicode_search(self):
        response = self.client.get("/api/products", params={"search": "ПЛАТЬЕ", "audience": "women", "source": "vikisews", "category": "Платья", "is_new": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(self.client.get("/api/products?search=%27%20OR%201=1--").json()["total"], 0)

    def test_pagination_limits_and_unknown_sort(self):
        self.assertEqual(len(self.client.get("/api/products?limit=1&offset=1").json()["items"]), 1)
        for query in ("limit=1000", "offset=-1", "sort=DROP", "audience=bad"):
            self.assertEqual(self.client.get("/api/products?"+query).status_code, 422)

    def test_filter_counts_use_public_visibility(self):
        coverage = self.client.get('/api/meta').json()['coverage']
        self.assertEqual(coverage['counts']['women'], 1)
        self.assertEqual(coverage['counts']['is_new'], 1)
        self.client.patch('/api/admin/products/1', headers=self.auth, json={'hidden': True}).raise_for_status()
        coverage = self.client.get('/api/meta').json()['coverage']
        self.assertEqual(coverage['counts']['women'], 0)
        self.assertEqual(coverage['counts']['is_new'], 0)
        self.assertEqual(coverage['total'], 1)

    def test_disabled_source_survives_restart(self):
        self.client.patch("/api/admin/sources/grasser", headers=self.auth, json={"enabled": False}).raise_for_status()
        self.db.initialize()
        self.assertEqual(self.client.get("/api/products").json()["total"], 1)
        self.assertEqual(self.client.get("/api/products/2").status_code, 404)
        self.assertEqual(self.client.get("/api/admin/products", headers=self.auth).json()["total"], 2)

    def test_override_survives_import(self):
        self.client.patch("/api/admin/products/1", headers=self.auth, json={"hidden": True, "category": "Юбки"}).raise_for_status()
        self.repo.upsert_many([self.p])
        self.assertEqual(self.client.get("/api/products/1").status_code, 404)
        p = self.client.get("/api/admin/products?source=vikisews", headers=self.auth).json()["items"][0]
        self.assertEqual(p["category"], "Юбки")
        self.assertEqual(p["imported_category"], "Платья")
        self.client.patch("/api/admin/products/1", headers=self.auth, json={"hidden": False, "category": None}).raise_for_status()
        self.assertEqual(self.client.get("/api/products/1").json()["category"], "Платья")

    def test_unavailable_and_unsafe_urls(self):
        with self.db.connect() as db:
            db.execute("UPDATE products SET image_url='javascript:alert(1)',product_url='data:text/html,x' WHERE id=1")
        p = self.client.get("/api/products/1").json()
        self.assertIsNone(p["image_url"])
        self.assertIsNone(p["product_url"])
        with self.db.connect() as db:
            db.execute("UPDATE products SET is_available=0 WHERE id=1")
        self.assertEqual(self.client.get("/api/products/1").status_code, 404)

    def test_auth_rejections(self):
        for raw in ("", signed(43), signed(age=3601), signed(age=-100), signed()+"&user=oops", signed().replace("test", "tampered")):
            self.assertIn(self.client.get("/api/admin/sources", headers={"X-Telegram-Init-Data": raw}).status_code, (401,403))
        self.assertEqual(telegram_user(signed(), "test-token"), 42)
        self.assertEqual(self.client.get("/api/admin/session", headers={"X-Dev-Key":"x"*32}).status_code, 401)

    def test_all_admin_writes_require_auth(self):
        for method,path,payload in [("POST","/api/admin/sources",{"display_name":"X","base_url":"https://example.com"}), ("PATCH","/api/admin/sources/grasser",{"enabled":False}), ("PATCH","/api/admin/products/1",{"hidden":True}), ("PUT","/api/admin/settings",{"filters":[],"menu":[]})]:
            self.assertEqual(self.client.request(method,path,json=payload).status_code, 401)

    def test_username_admins_bind_verified_stable_ids(self):
        self.client.app.state.web_settings = WebSettings(
            "test-token", admin_usernames=frozenset({"shanniwaby", "tatiana_svetlic"}))
        for user_id, username in ((101, "Shanniwaby"), (202, "tatiana_svetlic")):
            headers = {"X-Telegram-Init-Data": signed(user_id, username=username)}
            self.assertEqual(self.client.get("/api/admin/session", headers=headers).status_code, 200)
            # The owner keeps access even after changing their username.
            headers = {"X-Telegram-Init-Data": signed(user_id, username="renamed")}
            self.assertEqual(self.client.get("/api/admin/session", headers=headers).status_code, 200)
            headers = {"X-Telegram-Init-Data": signed(303, username=username)}
            self.assertEqual(self.client.get("/api/admin/session", headers=headers).status_code, 403)
        self.assertEqual(self.client.get("/api/admin/session", headers=self.auth).status_code, 403)

    def test_username_claim_requires_telegram_signature(self):
        self.client.app.state.web_settings = WebSettings("test-token", admin_usernames=frozenset({"shanniwaby"}))
        raw = signed(101, username="outsider").replace("outsider", "shanniwaby")
        self.assertEqual(self.client.get("/api/admin/session", headers={"X-Telegram-Init-Data": raw}).status_code, 401)
        with self.db.connect() as db:
            self.assertIsNone(db.execute("SELECT value FROM settings WHERE key='miniapp.admin.shanniwaby'").fetchone())

    def test_settings_persist_and_affect_query(self):
        ui = self.client.get("/api/meta").json()["ui"]
        ui["filters"].reverse()
        next(x for x in ui["filters"] if x["key"]=="is_new")["enabled"] = False
        ui["menu"][0]["enabled"] = False
        self.client.put("/api/admin/settings", headers=self.auth, json=ui).raise_for_status()
        other = TestClient(create_app(self.db, WebSettings()))
        self.assertEqual(other.get("/api/meta").json()["ui"], ui)
        self.assertEqual(other.get("/api/products?is_new=true").json()["total"], 2)
        other.close()
        self.assertEqual(self.client.put("/api/admin/settings",headers=self.auth,json={"filters":[],"menu":[]}).status_code,422)

    def test_new_source_pending_and_url_validation(self):
        self.client.post("/api/admin/sources",headers=self.auth,json={"display_name":"Example","base_url":"https://example.com"}).raise_for_status()
        row = next(s for s in self.client.get("/api/admin/sources",headers=self.auth).json() if s["display_name"]=="Example")
        self.assertEqual(row["parser_status"],"pending")
        self.assertFalse(row["enabled"])
        for url in ("javascript:alert(1)","https://user:password@example.com"):
            self.assertEqual(self.client.post("/api/admin/sources",headers=self.auth,json={"display_name":"X","base_url":url}).status_code,422)

    def test_dev_auth_only_explicit_loopback(self):
        with self.assertRaises(ValueError):
            WebSettings(dev_key="x"*32)
        with self.assertRaises(ValueError):
            WebSettings(environment="local",dev_key="short")
        app = create_app(self.db, WebSettings(environment="local",dev_key="x"*32))
        for host,client_host,expected in [("localhost","127.0.0.1",200),("example.com","127.0.0.1",401),("localhost","203.0.113.1",401)]:
            with TestClient(app,base_url="http://"+host,client=(client_host,1234)) as client:
                self.assertEqual(client.get("/api/admin/session",headers={"X-Dev-Key":"x"*32}).status_code,expected)

    def test_favorites_are_private_idempotent_and_do_not_require_admin(self):
        user = {'X-Telegram-Init-Data': signed(77)}
        other = {'X-Telegram-Init-Data': signed(78)}
        self.assertEqual(self.client.get('/api/favorites').status_code, 401)
        for _ in range(2):
            self.client.put('/api/favorites/1', headers=user, json={'saved':True}).raise_for_status()
        self.assertEqual(self.client.get('/api/favorites', headers=user).json()['ids'], [1])
        self.assertEqual(self.client.get('/api/favorites', headers=other).json()['ids'], [])
        self.assertEqual(self.client.get('/api/admin/session', headers=user).status_code, 403)
        self.client.put('/api/favorites/1', headers=other, json={'saved':False}).raise_for_status()
        self.assertEqual(self.client.get('/api/favorites', headers=user).json()['ids'], [1])
        self.client.put('/api/favorites/1', headers=user, json={'saved':False}).raise_for_status()
        self.assertEqual(self.client.get('/api/favorites', headers=user).json()['ids'], [])

    def test_favorites_and_id_filter_keep_public_visibility(self):
        self.client.put('/api/favorites/1', headers=self.auth, json={'saved':True}).raise_for_status()
        self.assertEqual(self.client.get('/api/products?ids=1').json()['total'], 1)
        self.assertEqual(self.client.get('/api/products?ids=1,2').json()['total'], 2)
        self.assertEqual(self.client.get('/api/products?ids=1%29%20OR%201=1').status_code, 422)
        self.client.patch('/api/admin/products/1', headers=self.auth, json={'hidden':True}).raise_for_status()
        self.assertEqual(self.client.get('/api/products?ids=1').json()['total'], 0)
        self.assertEqual(self.client.get('/api/favorites', headers=self.auth).json()['ids'], [])

    def test_image_routes_cached_and_protected_by_product_visibility(self):
        url = 'https://grasser.ru/test.jpg'
        with self.db.connect() as db:
            db.execute('UPDATE products SET image_url=?,image_urls=? WHERE id=1', (url,json.dumps([url,'https://grasser.ru/back.jpg'])))
        asset = MediaRepository(self.db)
        asset.register(image_key(url),url)
        path = Path(self.temp.name) / 'test.webp'; path.write_bytes(b'cached-test-image')
        images = self.client.app.state.images
        with patch.object(images,'get',new=AsyncMock(return_value=path)):
            response = self.client.get('/api/products/1/image/0')
            self.assertEqual(response.status_code,200)
            self.assertIn('max-age=86400',response.headers['cache-control'])
            self.assertEqual(self.client.get('/api/products/1/image/0',headers={'If-None-Match':response.headers['etag']}).status_code,304)
            self.assertEqual(self.client.get('/api/products/1/image/9').status_code,404)
            self.client.patch('/api/admin/products/1',headers=self.auth,json={'hidden':True}).raise_for_status()
            self.assertEqual(self.client.get('/api/products/1/image/0').status_code,404)
        detail = self.client.get('/api/admin/products?ids=1',headers=self.auth).json()['items'][0]
        self.assertEqual(detail['image_count'],2)
        self.assertEqual(len(detail['photo_urls']),2)

    def test_changed_image_url_can_use_last_successful_cover(self):
        from app.services.images import ImageUnavailable
        asset = MediaRepository(self.db)
        old = 'https://grasser.ru/old.jpg'
        new = 'https://grasser.ru/new.jpg'
        asset.register(image_key(old),old)
        asset.ready(image_key(old))
        asset.set_cover(1,image_key(old))
        images = self.client.app.state.images
        path = images.cached_path(old,'thumb'); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b'last-working-cover')
        with self.db.connect() as db:
            db.execute('UPDATE products SET image_url=? WHERE id=1',(new,))
        with patch.object(images,'get',new=AsyncMock(side_effect=ImageUnavailable('preparing'))):
            response = self.client.get('/api/products/1/image/0')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.content,b'last-working-cover')
        dashboard = self.client.get('/api/admin/media',headers=self.auth)
        self.assertEqual(dashboard.status_code,200)
        self.assertEqual(dashboard.json()['cached'],1)
        self.assertEqual(self.client.get('/api/admin/media').status_code,401)


if __name__ == "__main__":
    unittest.main()
