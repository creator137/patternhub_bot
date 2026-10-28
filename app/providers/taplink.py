"""Public Taplink market SSR and its read-only load-more endpoint."""
import json
import re
from dataclasses import replace
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from app.providers.public_http import CatalogFetchError
from app.providers.public_stores import PublicStoreProvider
from app.providers.store_common import money, product_from_values


def embedded_data(text):
    match = re.search(r'\bwindow\.data\s*=\s*', text)
    if not match:
        raise CatalogFetchError('Taplink public market data missing')
    try:
        value, _ = json.JSONDecoder().raw_decode(text[match.end():])
    except ValueError as error:
        raise CatalogFetchError('Taplink public market JSON invalid') from error
    if not isinstance(value, dict) or not isinstance(value.get('data'), dict):
        raise CatalogFetchError('Taplink market schema changed')
    return value['data']


class TaplinkProvider(PublicStoreProvider):
    async def crawl(self, http):
        home=await http.get(self.base_url+'/')
        title=BeautifulSoup(home.content,'html.parser').title
        self._audience='kids' if title and re.search(r'детск\w*\s+выкрой',title.get_text(),re.I) else None
        response = await http.get(self.base_url + '/m/')
        data = embedded_data(response.text)
        rows, seen = list(data['products']), set()
        for row in rows:
            seen.add(str(row['product_id']))
        for _ in range(self.max_pages):
            if not rows:
                raise CatalogFetchError('Taplink catalog is empty')
            cursor = min(int(row['column_id']) for row in rows)
            query = urlencode({'collection_id':'','next':cursor,'filters[query]':''})
            r = await http.get(self.base_url + '/api/market/products/list.json?' + query)
            payload = r.json()
            if payload.get('result') != 'success' or not isinstance(payload.get('response', {}).get('products'),list):
                raise CatalogFetchError('Taplink load-more response changed')
            more = payload['response']['products']
            if not more:
                break
            keys = {str(row['product_id']) for row in more}
            if keys & seen or len(keys) != len(more) or min(int(row['column_id']) for row in more) >= cursor:
                raise CatalogFetchError('Taplink market pagination repeated')
            seen.update(keys)
            rows.extend(more)
        else:
            raise CatalogFetchError('Taplink market pagination limit')
        products = []
        for row in rows:
            key = int(row['product_id'])
            url = self.base_url + '/o/' + format(key,'x') + '/'
            detail = await http.get(url)
            self.add(products,self.parse_detail(detail.text,url))
        return products

    def parse_detail(self, text, url):
        data = embedded_data(text)
        row = data.get('product')
        if not isinstance(row,dict) or not row.get('product_id'):
            raise CatalogFetchError('Taplink product identity missing')
        gallery = row.get('pictures') or []
        images = ['https://taplink.st/p/' + p['filename'] for p in gallery if p.get('filename')]
        if not images and row.get('picture'):
            images = ['https://taplink.st/p/'+row['picture']]
        product = product_from_values(self.config,key=row['product_id'],name=row['title'],url=url,
            price=money(row.get('price')),old_price=money(row.get('price_compare')),currency='RUB',
            images=images,description=row.get('description'),
            available=bool(row.get('is_active') and row.get('is_visible') and row.get('is_sellable')))
        if product:
            title = BeautifulSoup(text,'html.parser').title
            audience = 'kids' if title and 'детск' in title.get_text().casefold() else getattr(self,'_audience',None)
            return replace(product,audience=audience).normalized()
        return None

    def parse_gallery(self, html, product_url):
        p=self.parse_detail(html,product_url)
        return p.image_urls or () if p else ()
