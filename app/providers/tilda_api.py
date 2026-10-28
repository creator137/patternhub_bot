"""Read-only public Tilda storefront API for owner-authorized catalogs."""
import json
import re
from urllib.parse import urlencode, urljoin, urlsplit

from app.providers.public_http import PublicCatalogHTTP, CatalogFetchError
from app.providers.public_stores import PublicStoreProvider
from app.providers.store_common import money, product_from_values
from app.providers.gallery import html_gallery
from app.providers.tilda_extended import _non_pattern


class TildaAPIProvider(PublicStoreProvider):
    async def crawl(self, http):
        if not self.config.get('public_api_authorized'):
            raise CatalogFetchError('Public storefront API authorization is not configured')
        parts = set()
        for url in dict.fromkeys([self.config.get('catalog_url') or self.base_url, self.base_url]):
            response = await http.get(url)
            parts.update(re.findall(r'\bstorepart\s*:\s*[\"\x27](\d+)', response.text))
            parts.update(re.findall(r'data-storepart-uid=[\"\x27](\d+)', response.text))
        if not parts:
            raise CatalogFetchError('Public catalog storepart identifiers missing')
        products = []
        api = PublicCatalogHTTP('https://store.tildacdn.com', transport=self.transport,
            robots_allow=[r'/api/getproductslist/\?storepartuid=\d+&slice=\d+&size=100&getparts=true&getoptions=true'])
        try:
            async with api:
                for part in sorted(parts):
                    seen, total = set(), None
                    for page in range(1, self.max_pages + 1):
                        query = urlencode(dict(storepartuid=part, slice=page, size=100, getparts='true', getoptions='true'))
                        response = await api.get('https://store.tildacdn.com/api/getproductslist/?' + query)
                        # Tilda returns JSON with text/html Content-Type.
                        data = response.json()
                        rows = data.get('products')
                        if not isinstance(rows, list) or 'total' not in data or str(data.get('partuid')) != str(part):
                            raise CatalogFetchError('Tilda public API schema changed')
                        count = int(data['total'])
                        if total is not None and total != count:
                            raise CatalogFetchError('Tilda catalog total changed during pagination')
                        total = count
                        keys = {str(row['uid']) for row in rows}
                        if len(keys) != len(rows) or keys & seen or (not rows and len(seen) < total):
                            raise CatalogFetchError('Tilda pagination repeated or truncated')
                        seen.update(keys)
                        for row in rows:
                            self.add(products, self.parse_row(row))
                        if len(seen) == total:
                            break
                        if len(seen) > total:
                            raise CatalogFetchError('Tilda total does not match products')
                    else:
                        raise CatalogFetchError('Tilda API pagination limit')
        finally:
            http.requests_made += api.requests_made
            http.retries_made += api.retries_made
        return products

    def parse_row(self, row):
        raw_url = row.get('url') or row.get('buttonlink')
        url = urljoin(self.base_url + '/', raw_url or '')
        host = urlsplit(url).hostname
        own = urlsplit(self.base_url).hostname.removeprefix('www.')
        if not raw_url or not host or host.removeprefix('www.') != own:
            raise CatalogFetchError('Tilda product canonical is missing or foreign')
        if _non_pattern(str(row.get('title') or ''), url):
            return None
        gallery = row.get('gallery') or []
        if isinstance(gallery, str):
            gallery = json.loads(gallery)
        if not isinstance(gallery, list):
            raise CatalogFetchError('Tilda gallery structure changed')
        price, old = money(row.get('price')), money(row.get('priceold'))
        editions = row.get('editions') or []
        priced = [(money(e.get('price')), e) for e in editions if money(e.get('price')) is not None]
        if priced:
            price, edition = min(priced, key=lambda item: item[0])
            old = money(edition.get('priceold'))
        sizes, heights = [], []
        for field in row.get('properties') or []:
            label = str(field.get('title', '')).casefold()
            values = str(field.get('values') or '').splitlines()
            if 'размер' in label and 'рост' not in label:
                sizes.extend(values)
            elif 'рост' in label and 'размер' not in label:
                heights.extend(values)
        categories = [str(p.get('value') or p.get('values') or '') for p in row.get('characteristics') or []
                      if re.search(r'категор|издели|аудитор|для кого', str(p.get('title') or ''), re.I)]
        quantities = [str(e.get('quantity', '')).strip() for e in editions]
        available = any(q != '0' for q in quantities) if quantities else str(row.get('quantity', '')).strip() != '0'
        return product_from_values(self.config, key=row['uid'], name=row['title'], url=url,
            price=price, old_price=old, currency=self.config.get('currency', 'RUB'),
            images=[entry.get('img') for entry in gallery if isinstance(entry, dict)],
            categories=categories, description=row.get('text') or row.get('descr'),
            sizes=sizes, heights=heights, available=available)

    def parse_gallery(self, html, product_url):
        return html_gallery(html, product_url)
