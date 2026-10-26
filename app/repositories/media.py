"""Durable, shared media download queue; product records remain in the catalog."""
import random
import time
from hashlib import sha256
from uuid import uuid4
from app.database import Database


class MediaRepository:
    def __init__(self, database: Database):
        self.database = database

    def register(self, key: str, url: str, *, priority=100, referer=None):
        with self.database.connect() as db:
            db.execute("""INSERT INTO media_assets(key,url,priority,referer) VALUES(?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET priority=MAX(priority,excluded.priority),
                referer=COALESCE(excluded.referer,referer)""", (key, url, priority, referer))

    def register_many(self, entries):
        with self.database.connect() as db:
            db.executemany("""INSERT INTO media_assets(key,url,priority,referer) VALUES(?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET priority=MAX(priority,excluded.priority),
                referer=COALESCE(excluded.referer,referer)""", entries)

    def register_products(self, products):
        entries = []
        for product in products:
            product = product.normalized()
            url = product.image_urls[0] if product.image_urls else product.image_url
            if url:
                entries.append((sha256(url.encode()).hexdigest(), url, 100, product.product_url))
        self.register_many(entries)

    def claim(self, key: str, *, force=False) -> str | None:
        now = time.time()
        owner = uuid4().hex
        with self.database.connect() as db:
            result = db.execute("""UPDATE media_assets SET lease_until=?,lease_owner=?
                WHERE key=? AND lease_until<? AND (next_attempt<=? OR ?)
                AND (state NOT IN ('evicted','superseded') OR ?)""", (now + 180, owner, key, now, now, force, force))
        return owner if result.rowcount else None

    def renew(self, key: str, owner: str) -> bool:
        with self.database.connect() as db:
            row = db.execute('UPDATE media_assets SET lease_until=? WHERE key=? AND lease_owner=?', (time.time() + 180, key, owner))
        return bool(row.rowcount)

    def ready(self, key: str, *, owner=None):
        now = time.time()
        with self.database.connect() as db:
            db.execute("""UPDATE media_assets SET state='ready',attempts=0,next_attempt=0,
                last_error=NULL,lease_until=0,lease_owner=NULL,last_success=?,last_access=? WHERE key=?
                AND (? IS NULL OR lease_owner=?)""", (now, now, key, owner, owner))

    def touch(self, key: str):
        now = time.time()
        with self.database.connect() as db:
            db.execute('UPDATE media_assets SET last_access=? WHERE key=? AND last_access<?', (now, key, now - 3600))

    def observed_cached(self, key: str, url: str, modified: float, *, referer=None, priority=200):
        now = time.time()
        with self.database.connect() as db:
            db.execute("""INSERT INTO media_assets(key,url,state,priority,referer,last_success,last_access)
                VALUES(?,?,'ready',?,?,?,?) ON CONFLICT(key) DO UPDATE SET last_access=excluded.last_access
                WHERE media_assets.last_access<?""", (key,url,priority,referer,modified,now,now-3600))

    def failed(self, key: str, error: str, *, retry_after=0, owner=None):
        now = time.time()
        with self.database.connect() as db:
            row = db.execute('SELECT attempts FROM media_assets WHERE key=?', (key,)).fetchone()
            attempts = (row[0] if row else 0) + 1
            pause = max(retry_after, min(6 * 3600, 30 * 2 ** min(attempts, 10) * random.uniform(0.8, 1.2)))
            db.execute("""UPDATE media_assets SET state='retry',attempts=?,next_attempt=?,
                last_error=?,lease_until=0,lease_owner=NULL WHERE key=? AND (? IS NULL OR lease_owner=?)""",
                (attempts, now + pause, error[:100], key, owner, owner))

    def due(self, limit=250):
        now = time.time()
        with self.database.connect() as db:
            rows = db.execute("""SELECT a.* FROM media_assets a WHERE a.state IN ('pending','retry')
                AND a.next_attempt<=? AND a.lease_until<? AND (a.referer IS NULL OR EXISTS (
                    SELECT 1 FROM products p JOIN sources s ON s.name=p.source
                    WHERE p.product_url=a.referer AND p.is_available=1 AND s.enabled=1))
                ORDER BY a.priority DESC,a.attempts,a.key LIMIT ?""", (now, now, limit)).fetchall()
        return [dict(row) for row in rows]

    def get(self, key: str):
        with self.database.connect() as db:
            row = db.execute('SELECT * FROM media_assets WHERE key=?', (key,)).fetchone()
        return dict(row) if row else None

    def evicted(self, key: str):
        with self.database.connect() as db:
            db.execute("UPDATE media_assets SET state='evicted',lease_until=0 WHERE key=?", (key,))

    def stats(self):
        with self.database.connect() as db:
            return {row[0]: row[1] for row in db.execute('SELECT state,COUNT(*) FROM media_assets GROUP BY state')}

    def retention(self):
        with self.database.connect() as db:
            return {row['key']: dict(row) for row in db.execute('SELECT key,priority,last_access,lease_until FROM media_assets')}

    def queue_stale(self, days=30):
        with self.database.connect() as db:
            db.execute("UPDATE media_assets SET state='pending' WHERE state='ready' AND last_success<?", (time.time() - days * 86400,))

    def set_cover(self, product_id: int, key: str):
        with self.database.connect() as db:
            db.execute('INSERT INTO product_media_cache(product_id,asset_key) VALUES(?,?) '
                'ON CONFLICT(product_id) DO UPDATE SET asset_key=excluded.asset_key '
                'WHERE product_media_cache.asset_key!=excluded.asset_key', (product_id, key))

    def last_cover(self, product_id: int):
        with self.database.connect() as db:
            row = db.execute('SELECT a.* FROM product_media_cache c JOIN media_assets a ON a.key=c.asset_key WHERE c.product_id=?', (product_id,)).fetchone()
        return dict(row) if row else None

    def obsolete(self, key: str):
        with self.database.connect() as db:
            db.execute("UPDATE media_assets SET state='superseded',lease_until=0 WHERE key=?", (key,))

    def dashboard(self):
        with self.database.connect() as db:
            row = db.execute("""SELECT COUNT(*) AS total,
                COALESCE(SUM(c.product_id IS NOT NULL AND a.last_success>0 AND a.state!='evicted'),0) AS cached
                FROM products p JOIN sources s ON s.name=p.source
                LEFT JOIN product_overrides o ON o.product_id=p.id
                LEFT JOIN product_media_cache c ON c.product_id=p.id LEFT JOIN media_assets a ON a.key=c.asset_key
                WHERE p.is_available=1 AND s.enabled=1 AND COALESCE(o.hidden,0)=0""").fetchone()
            galleries = db.execute('SELECT COUNT(*) FROM media_gallery_jobs').fetchone()[0]
        return dict(row) | {'queue': self.stats(), 'gallery_errors': galleries}
