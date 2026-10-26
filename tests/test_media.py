import asyncio
from io import BytesIO
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image

from app.database import Database
from app.models.product import ParsedProduct
from app.repositories.products import ProductRepository
from app.repositories.media import MediaRepository
from app.services.images import ImageCache, ImageUnavailable, image_key
from app.providers.registry import create_provider


def png():
    buffer = BytesIO()
    Image.new('RGB', (1000, 1400), 'green').save(buffer, format='PNG')
    return buffer.getvalue()


class ImageCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'test.sqlite3')
        self.db.initialize()
        self.queue = MediaRepository(self.db)
        self.url = 'https://grasser.ru/test-image.png'
        self.calls = 0
        self.response = lambda request: httpx.Response(200, content=png(), headers={'content-type': 'image/png'})
        async def handler(request):
            self.calls += 1
            return self.response(request)
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.cache = ImageCache(Path(self.temp.name) / 'media', client=self.client, repository=self.queue)
        self.validation = patch.object(self.cache, 'validate_url', AsyncMock())
        self.validation.start()

    async def asyncTearDown(self):
        self.validation.stop()
        await self.client.aclose()
        self.temp.cleanup()

    async def test_dedup_thumbnails_persist_across_instances(self):
        paths = await asyncio.gather(*(self.cache.get(self.url) for _ in range(6)))
        self.assertEqual(self.calls, 1)
        with Image.open(paths[0]) as image:
            self.assertLessEqual(max(image.size), 384)
            self.assertEqual(image.format, 'WEBP')
        cache = ImageCache(self.cache.root, client=self.client, repository=self.queue)
        await cache.get(self.url, 'detail')
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.queue.get(image_key(self.url))['state'], 'ready')

    async def test_stale_ready_assets_requeue_but_evicted_assets_stay_evicted(self):
        await self.cache.get(self.url)
        key = image_key(self.url)
        with self.db.connect() as db:
            db.execute('UPDATE media_assets SET last_success=? WHERE key=?', (time.time() - 31 * 86400, key))
        self.queue.queue_stale()
        self.assertEqual(self.queue.get(key)['state'], 'pending')
        self.queue.evicted(key)
        self.queue.queue_stale()
        self.assertEqual(self.queue.get(key)['state'], 'evicted')

    async def test_temporary_server_error_retried(self):
        self.response = lambda request: httpx.Response(503) if self.calls < 3 else httpx.Response(200, content=png(), headers={'content-type': 'image/png'})
        with patch('app.services.images.asyncio.sleep', new=AsyncMock()):
            await self.cache.get(self.url)
        self.assertEqual(self.calls, 3)

    async def test_valid_image_with_generic_storage_mime_is_decoded(self):
        self.response = lambda request: httpx.Response(200,content=png(),headers={'content-type':'application/octet-stream'})
        path = await self.cache.get(self.url)
        with Image.open(path) as image:
            self.assertEqual(image.format,'WEBP')
        self.assertEqual(self.calls,1)

    async def test_timeout_retried_then_success(self):
        def response(request):
            if self.calls < 2:
                raise httpx.ReadTimeout('temporary', request=request)
            return httpx.Response(200, content=png(), headers={'content-type': 'image/png'})
        self.response = response
        with patch('app.services.images.asyncio.sleep', new=AsyncMock()):
            await self.cache.get(self.url)
        self.assertEqual(self.calls, 2)

    async def test_404_keeps_durable_retry_and_is_not_hammered(self):
        self.response = lambda request: httpx.Response(404)
        for _ in range(2):
            with self.assertRaises(ImageUnavailable):
                await self.cache.get(self.url)
        self.assertEqual(self.calls, 1)
        state = self.queue.get(image_key(self.url))
        self.assertEqual(state['state'], 'retry')
        self.assertGreater(state['next_attempt'], time.time())
        self.assertIn('404', state['last_error'])
        another_process = ImageCache(self.cache.root, client=self.client, repository=self.queue)
        with self.assertRaises(ImageUnavailable):
            await another_process.get(self.url)
        self.assertEqual(self.calls, 1)

    async def test_shared_queue_lease_and_expiry(self):
        key = image_key(self.url)
        self.queue.register(key, self.url)
        second = MediaRepository(self.db)
        first_owner = self.queue.claim(key)
        self.assertTrue(first_owner)
        self.assertFalse(second.claim(key))
        with self.db.connect() as db:
            db.execute('UPDATE media_assets SET lease_until=0 WHERE key=?', (key,))
        second_owner = second.claim(key)
        self.assertTrue(second_owner)
        self.queue.failed(key,'old worker failed',owner=first_owner)
        self.queue.ready(key,owner=first_owner)
        self.assertEqual(second.get(key)['lease_owner'],second_owner)
        self.assertTrue(second.renew(key,second_owner))

    async def test_retry_after_is_honored_without_blocking_request(self):
        self.response = lambda request: httpx.Response(429, headers={'Retry-After': '120'})
        with self.assertRaises(ImageUnavailable):
            await self.cache.get(self.url)
        self.assertEqual(self.calls, 1)
        self.assertGreaterEqual(self.queue.get(image_key(self.url))['next_attempt'], time.time() + 119)

    async def test_failed_refresh_preserves_last_working_copy(self):
        path = await self.cache.get(self.url)
        old = path.read_bytes()
        self.response = lambda request: httpx.Response(503)
        with patch('app.services.images.asyncio.sleep', new=AsyncMock()):
            self.assertEqual(await self.cache.get(self.url, refresh=True), path)
        self.assertEqual(path.read_bytes(), old)
        self.assertEqual(self.queue.get(image_key(self.url))['state'], 'retry')

    async def test_redirect_to_internal_host_rejected(self):
        self.validation.stop()
        self.response = lambda request: httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
        async def validate(url):
            if '127.0.0.1' in url:
                raise ImageUnavailable('blocked')
        with patch.object(self.cache, 'validate_url', side_effect=validate):
            with self.assertRaises(ImageUnavailable):
                await self.cache.get(self.url)
        self.assertEqual(self.calls, 1)

    async def test_untrusted_and_private_dns_hosts_rejected(self):
        self.validation.stop()
        with self.assertRaises(ImageUnavailable):
            await self.cache.validate_url('http://127.0.0.1/a')
        with patch('app.services.images.socket.getaddrinfo', return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ImageUnavailable):
                await self.cache.validate_url(self.url)

    async def test_oversized_and_non_image_bodies_rejected(self):
        for url, headers in [(self.url, {'content-type':'text/html'}),
                (self.url + '?large', {'content-type':'image/png','content-length': str(20 * 1024 * 1024)})]:
            self.response = lambda request, headers=headers: httpx.Response(200, content=b'x', headers=headers)
            with self.assertRaises(ImageUnavailable):
                await self.cache.get(url)

    async def test_disk_quota_prefers_preserving_cover_thumbnails(self):
        thumb = await self.cache.get(self.url)
        detail = self.cache.cached_path(self.url, 'detail')
        await asyncio.to_thread(self.cache.prune, max_bytes=thumb.stat().st_size + 1, reserve_bytes=0)
        self.assertTrue(thumb.exists())
        self.assertFalse(detail.exists())

    async def test_cached_files_can_be_reused_after_database_restore(self):
        path = await self.cache.get(self.url)
        with self.db.connect() as db:
            db.execute('DELETE FROM media_assets')
        self.assertEqual(await self.cache.get(self.url), path)
        self.assertEqual(self.queue.get(image_key(self.url))['state'], 'ready')
        self.assertEqual(self.calls, 1)


class GalleryTests(unittest.TestCase):
    def test_parsers_extract_product_gallery_not_reviews(self):
        cases = [
            ('vikisews', '<script type="application/ld+json">{"@type":"Product","image":["/a.jpg","/b.jpg"]}</script>'),
            ('grasser', '<div class="product__slider-big"><img src="/a.jpg"><img src="/b.jpg"></div><div class="small-review__gallery"><img src="/wrong.jpg"></div>'),
            ('helpersew', '<div class="cat-detail__pics"><img src="/a.jpg"><img src="/b.jpg"></div><img src="/logo.jpg">'),
            ('studio_yusupova', '<div class="woocommerce-product-gallery__image"><a href="/a.jpg"></a><a href="/b.jpg"></a></div>'),
            ('sewitnow', '<script id="__NEXT_DATA__">{"props":{"pageProps":{"product":{"slug":"test","images":[{"storage_object":{"url":"/a.jpg"}},{"storage_object":{"url":"/b.jpg"}}]}}}}</script>'),
        ]
        for source, html in cases:
            with self.subTest(source=source):
                self.assertEqual(create_provider(source).parse_gallery(html, 'https://example.com/product/test/'), ('https://example.com/a.jpg','https://example.com/b.jpg'))

    def test_unrelated_website_logo_is_not_a_product_photo(self):
        self.assertEqual(create_provider('vikisews').parse_gallery('<meta property="og:image" content="/logo.jpg"><meta property="og:type" content="website">', 'https://example.com/'), ())

    def test_gallery_survives_listing_upsert_and_cover_variants_not_duplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / 'catalog.sqlite3'); db.initialize()
            repo = ProductRepository(db)
            p = ParsedProduct(source='grasser',name='Test',product_url='https://example.com/a',image_url='https://example.com/small.jpg',image_urls=('https://example.com/a.jpg','https://example.com/b.jpg','https://example.com/a.jpg'))
            repo.upsert_many([p])
            repo.upsert_many([ParsedProduct(source='grasser',name='Test',product_url=p.product_url,image_url=p.image_url)])
            self.assertEqual(repo.get_product(1).image_urls, ('https://example.com/a.jpg','https://example.com/b.jpg'))
            self.assertEqual(repo.get_product(1).image_url, p.image_url)
