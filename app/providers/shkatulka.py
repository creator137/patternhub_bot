"""The public Yii catalog uses a read-only POST form for infinite scroll."""
from urllib.parse import urljoin
import re

from bs4 import BeautifulSoup

from app.providers.public_http import CatalogFetchError
from app.providers.public_stores import PublicStoreProvider
from app.providers.store_common import money, product_from_values


class ShkatulkaProvider(PublicStoreProvider):
    async def crawl(self, http):
        url = self.config['catalog_url']
        response = await http.get(url)
        soup = BeautifulSoup(response.content, 'html.parser')
        form = soup.select_one('.dfilter')
        if form is None:
            raise CatalogFetchError('Shkatulka public listing form missing')
        data = {}
        for field in form.select('input[name], select[name]'):
            if field.get('type') in {'checkbox','radio'} and not field.has_attr('checked'):
                continue
            selected = field.select_one('option[selected]') if field.name == 'select' else None
            data[field['name']] = selected.get('value', '') if selected else field.get('value', '')
        products, seen = [], set()
        for page in range(1, self.max_pages + 1):
            response = await http.read_catalog_post(url + ('&' if '?' in url else '?') + f'page={page}', data)
            if not response.text.strip():
                if not products:
                    raise CatalogFetchError('Shkatulka empty catalog')
                return products
            fragment = BeautifulSoup(response.content, 'html.parser')
            cards = fragment.select('.grid-product')
            if not cards:
                raise CatalogFetchError('Shkatulka listing fragment changed')
            for card in cards:
                link = card.select_one('a.grid-product__title[href]')
                if link is None:
                    raise ValueError('Shkatulka product link missing')
                target = urljoin(url, link['href'])
                if target in seen:
                    raise CatalogFetchError('Shkatulka pagination repeated')
                seen.add(target)
                self.add(products, self.parse_card(card, url))
        raise CatalogFetchError('Shkatulka pagination limit')

    def parse_card(self, card, url):
        link = card.select_one('a.grid-product__title[href]')
        if link is None:
            raise ValueError('Shkatulka product link missing')
        target = urljoin(url, link['href'])
        price = card.select_one('.ec-price-item__price')
        old = card.select_one('.ec-price-item__preprice')
        images = [n.get('src') for n in card.select('img.grid-product__picture')]
        extra = card.select_one('.grid-product__picture-additional[style]')
        if extra:
            match = re.search(r'url\([\"\x27]?([^\)\"\x27]+)', extra['style'])
            if match:
                images.append(urljoin(url, match[1]))
        return product_from_values(self.config, name=link.get_text(' ', strip=True),url=target,
            price=money(price.get_text()) if price else None,old_price=money(old.get_text()) if old else None,
            currency='RUB',images=images)
