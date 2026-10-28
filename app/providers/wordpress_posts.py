"""Public WordPress post collections containing sewing patterns, not files."""
from dataclasses import replace
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from app.models.catalog_policy import publication_datetime
from app.providers.public_http import CatalogFetchError
from app.providers.public_stores import PublicStoreProvider
from app.providers.store_common import plain, product_from_values, money


class WordPressPostsProvider(PublicStoreProvider):
    async def crawl(self, http):
        products, seen, total = [], set(), None
        self._featured = {}
        # Freeze the publication boundary so new posts do not shift pagination.
        before = datetime.now(timezone.utc).isoformat(timespec='seconds')
        page_size = int(self.config.get('page_size', 100))
        if not 1 <= page_size <= 100:
            raise ValueError('WordPress page size must be between 1 and 100')
        cache = Path(self.config['crawl_checkpoint']) if self.config.get('crawl_checkpoint') else None
        if cache:
            cache.mkdir(parents=True, exist_ok=True)
            state_file = cache / 'state.json'
            state = json.loads(state_file.read_text()) if state_file.exists() else {}
            if (state.get('source') == self.source and not state.get('complete')
                    and state.get('page_size') == page_size
                    and (datetime.now(timezone.utc)-datetime.fromisoformat(state['before'])).total_seconds() < 86400):
                before = state['before']
            else:
                for old in cache.glob('page-*.json.gz'):
                    old.unlink()
                state_file.write_text(json.dumps(dict(source=self.source, before=before, page_size=page_size, complete=False)))
        for page in range(1, self.max_pages + 1):
            query = urlencode(dict(per_page=page_size, page=page, before=before, orderby='id', order='asc',
                _fields='id,link,title,content,date_gmt,categories,yoast_head_json,featured_media'))
            page_file = cache / f'page-{page}.json.gz' if cache else None
            if page_file and page_file.exists():
                payload = json.loads(gzip.decompress(page_file.read_bytes()))
                rows, header_total = payload['rows'], payload['total']
            else:
                response = await http.get(self.base_url + '/wp-json/wp/v2/posts?' + query)
                rows, header_total = response.json(), response.headers.get('X-WP-Total')
                if page_file and isinstance(rows, list) and header_total is not None:
                    temporary = page_file.with_suffix('.tmp')
                    temporary.write_bytes(gzip.compress(json.dumps(dict(rows=rows, total=header_total),ensure_ascii=False).encode()))
                    temporary.replace(page_file)
            if not isinstance(rows, list) or header_total is None:
                raise CatalogFetchError('Public WordPress posts schema changed')
            if total is None:
                total = int(header_total)
            elif total != int(header_total):
                raise CatalogFetchError('WordPress post collection changed during crawl')
            keys = {str(row['id']) for row in rows}
            if len(keys) != len(rows) or seen & keys:
                raise CatalogFetchError('WordPress post pagination repeated')
            seen.update(keys)
            for row in rows:
                if 'featured_media' in row:
                    self._featured[str(row['id'])] = row['featured_media']
                self.add(products, self.parse_post(row))
            if len(seen) == total:
                products = await self.enrich_covers(http, products, before)
                if cache:
                    (cache/'state.json').write_text(json.dumps(dict(source=self.source,before=before,page_size=page_size,complete=True)))
                return products
            if not rows or len(seen) > total:
                raise CatalogFetchError('WordPress post collection truncated')
        raise CatalogFetchError('WordPress post pagination limit')

    async def enrich_covers(self, http, products, before):
        """Bulk public media metadata, never pattern documents or per-item HTTP."""
        featured = dict(getattr(self, '_featured', {}))
        missing = {p.source_product_id for p in products if not p.image_url}
        if not missing:
            return products
        if not missing <= featured.keys():
            seen, expected = set(), None
            for page in range(1, self.max_pages + 1):
                query = urlencode(dict(per_page=100, page=page, before=before, orderby='id', order='asc',
                                       _fields='id,featured_media'))
                response = await http.get(self.base_url+'/wp-json/wp/v2/posts?'+query)
                rows = response.json()
                if not isinstance(rows,list) or 'X-WP-Total' not in response.headers:
                    raise CatalogFetchError('WordPress cover references changed')
                total = int(response.headers['X-WP-Total'])
                expected = total if expected is None else expected
                keys = {str(r['id']) for r in rows}
                if total != expected or keys & seen or len(keys) != len(rows):
                    raise CatalogFetchError('WordPress cover references repeated/changed')
                seen.update(keys)
                featured.update({str(r['id']):r['featured_media'] for r in rows})
                if len(seen)==total: break
                if not rows or len(seen)>total:
                    raise CatalogFetchError('WordPress cover references truncated')
            else: raise CatalogFetchError('WordPress cover reference page limit')
        ids = sorted({int(featured[key]) for key in missing if featured.get(key)})
        media = {}
        for offset in range(0,len(ids),100):
            query = urlencode(dict(include=','.join(map(str,ids[offset:offset+100])),per_page=100,
                                   _fields='id,source_url,mime_type'))
            response = await http.get(self.base_url+'/wp-json/wp/v2/media?'+query)
            rows = response.json()
            if not isinstance(rows,list):
                raise CatalogFetchError('WordPress media metadata changed')
            for row in rows:
                if str(row.get('mime_type','')).startswith('image/') and row.get('source_url'):
                    media[int(row['id'])]=row['source_url']
        return [replace(p,image_url=media[featured[p.source_product_id]],
                        image_urls=(media[featured[p.source_product_id]],)).normalized()
                if not p.image_url and featured.get(p.source_product_id) in media else p for p in products]

    def parse_post(self, row):
        name = plain(row['title']['rendered'])
        if re.search(r'журнал|книг[аиуы]|подборк\w*\s+(?:выкро|модел)|^размер\w*\s+выкро|^таблиц\w*\s+размер', name, re.I):
            return None
        article = BeautifulSoup(row.get('content', {}).get('rendered') or '', 'html.parser')
        introduction = article.get_text(' ', strip=True).split('Телеграм')[0][:300]
        if not re.search(r'выкро[йе]|лекал|\bpattern\b', name + ' ' + introduction, re.I):
            return None
        media = row.get('_embedded') or {}
        images = [item.get('source_url') for item in media.get('wp:featuredmedia', []) if isinstance(item, dict)]
        images += [item.get('url') for item in (row.get('yoast_head_json') or {}).get('og_image', []) if isinstance(item, dict)]
        images += [n.get('data-src') or n.get('data-lazy-src') or n.get('src') for n in article.select('img')]
        images = [url for url in images if url and not re.search(r'/wp-includes/|/themes/|\.svg(?:\?|$)|^data:|/vk-files/|/patterns/', url)]
        categories = [name] + [term.get('name', '') for group in media.get('wp:term', [])
                      if isinstance(group, list) for term in group if isinstance(term, dict)]
        free = bool(re.search(r'бесплатн', name, re.I))
        product = product_from_values(self.config, key=row['id'], name=name, url=row['link'],
            categories=categories, images=images, price=money('0') if free else None,
            currency='RUB' if free else None, description=article.get_text(' ', strip=True)[:6000])
        if product:
            return replace(product, source_published_at=publication_datetime(row.get('date_gmt'))).normalized()
        return None
