"""Offline gallery enrichment and prewarming; no product-page HTTP in handlers."""
import argparse
import asyncio
import logging
import os

import httpx

from app.config import load_settings
from app.database import Database
from app.providers.registry import create_provider
from app.repositories.products import ProductRepository
from app.repositories.media import MediaRepository
from app.services.images import ImageCache, ImageUnavailable, image_key


def needs_resolution(state):
    error = (state or {}).get('last_error') or ''
    return any(marker in error for marker in ('404', '403', 'UnidentifiedImageError', 'Not an image'))


async def prepare(*, mode='covers', source=None, product_id=None, limit=10000):
    settings = load_settings(require_token=False)
    database = Database(settings.database_path)
    database.initialize()
    repo = ProductRepository(database)
    media_repo = MediaRepository(database)
    cache = ImageCache(settings.database_path.parent / 'media', repository=media_repo)
    gate = asyncio.Semaphore(2)
    stats = {'processed': 0, 'galleries': 0, 'cached': 0, 'errors': 0, 'gallery_requests': 0}
    async with httpx.AsyncClient(timeout=httpx.Timeout(35, connect=8), follow_redirects=True,
            trust_env=False, headers={'User-Agent': 'Mozilla/5.0 (compatible; allsewpattern/1.0)'}) as client:
        async def run(product, gallery=False):
            async with gate:
                urls = product.image_urls or ((product.image_url,) if product.image_url else ())
                try:
                    if gallery:
                        for attempt in range(3):
                            try:
                                stats['gallery_requests'] += 1
                                response = await client.get(product.product_url)
                                response.raise_for_status()
                                break
                            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else 0
                                pause = ImageCache.retry_after(exc)
                                if attempt == 2 or status and status not in {408,429,500,502,503,504,522,524} or pause > 30:
                                    raise
                                import random
                                await asyncio.sleep(max(pause, 2 ** attempt * random.uniform(.8,1.2)))
                        found = create_provider(product.source).parse_gallery(response.text, product.product_url)
                        if not found:
                            raise ValueError('Product gallery markup missing')
                        if found:
                            urls = found if len(found) > 1 or len(urls) < 2 else urls
                    for index, url in enumerate(urls[:3]):
                        try:
                            await cache.get(url, referer=product.product_url, priority=100)
                            if gallery or index:
                                repaired = urls[index:] + urls[:index]
                                await asyncio.to_thread(repo.set_gallery, product.id, repaired, expected_url=product.product_url)
                                stats['galleries'] += bool(gallery)
                            await asyncio.to_thread(media_repo.set_cover, product.id, image_key(url))
                            stats['cached'] += 1
                            break
                        except ImageUnavailable:
                            if index == min(len(urls), 3) - 1:
                                raise
                except Exception as exc:
                    stats['errors'] += 1
                    if gallery:
                        await asyncio.to_thread(repo.gallery_failed, product.id, type(exc).__name__)
                    logging.warning('Media failed: id=%s source=%s url=%s error=%s', product.id, product.source, product.product_url, type(exc).__name__)
                stats['processed'] += 1
                if stats['processed'] % 25 == 0:
                    logging.info('Media progress: %s', stats)

        if mode in {'register', 'covers', 'all'}:
            products = repo.media_products(product_id=product_id, source=source, limit=limit)
            # Warm the entry pages for every category before the long tail.
            counts, entries = {}, []
            for product in products:
                key = product.category
                counts[key] = counts.get(key, 0) + 1
                url = product.image_urls[0] if product.image_urls else product.image_url
                if url:
                    entries.append((image_key(url), url, 150 if counts[key] <= 24 else 100, product.product_url))
            await asyncio.to_thread(media_repo.register_many, entries)
        if mode in {'covers', 'queue', 'all'}:
            await asyncio.to_thread(media_repo.queue_stale)
            async def download(entry):
                async with gate:
                    try:
                        await cache.get(entry['url'], referer=entry['referer'], priority=entry['priority'],
                            refresh=bool(entry['last_success']))
                        for product_id in await asyncio.to_thread(repo.cover_product_ids, entry['url']):
                            await asyncio.to_thread(media_repo.set_cover, product_id, entry['key'])
                        stats['cached'] += 1
                    except ImageUnavailable:
                        stats['errors'] += 1
                        state = await asyncio.to_thread(media_repo.get, entry['key'])
                        if needs_resolution(state):
                            await asyncio.to_thread(repo.request_gallery_repair, entry['url'])
                    stats['processed'] += 1
                    if stats['processed'] % 25 == 0:
                        logging.info('Media progress: %s', stats)
                    if stats['processed'] % 100 == 0:
                        await asyncio.to_thread(cache.prune, max_bytes=int(os.getenv('MEDIA_CACHE_MAX_MB', '768')) * 1024 * 1024)
            due = await asyncio.to_thread(media_repo.due, limit)
            await asyncio.gather(*(download(entry) for entry in due))
            for entry in due:
                state = await asyncio.to_thread(media_repo.get, entry['key'])
                if needs_resolution(state):
                    affected = await asyncio.to_thread(repo.products_with_image, entry['url'])
                    for product in affected:
                        await run(product, gallery=True)
                    if affected and all(entry['url'] not in ((p.image_url,) + tuple(p.image_urls or ()))
                            for p in (repo.get_product(product.id) for product in affected) if p):
                        await asyncio.to_thread(media_repo.obsolete, entry['key'])
        if mode in {'galleries', 'all'}:
            products = repo.media_products(product_id=product_id, source=source, galleries=True, limit=limit)
            await asyncio.gather(*(run(product, gallery=True) for product in products))
    await asyncio.to_thread(cache.prune, max_bytes=int(os.getenv('MEDIA_CACHE_MAX_MB', '768')) * 1024 * 1024)
    await cache.aclose()
    stats.update(image_requests=cache.requests_made, image_retries=cache.retries_made, downloaded_bytes=cache.bytes_downloaded)
    logging.info('Media result: %s', stats)
    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('register', 'covers', 'galleries', 'queue', 'all'), default='covers')
    parser.add_argument('--source')
    parser.add_argument('--product-id', type=int)
    parser.add_argument('--limit', type=int, default=10000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    asyncio.run(prepare(mode=args.mode, source=args.source, product_id=args.product_id, limit=args.limit))
