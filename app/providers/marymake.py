"""Marymake's public, manually assembled Vigbo pattern catalog."""
import re
from dataclasses import replace
from urllib.parse import urljoin, urlsplit, urlunsplit
from bs4 import BeautifulSoup
from app.providers.public_http import CatalogFetchError
from app.providers.public_stores import PublicStoreProvider
from app.providers.store_common import money, product_from_values

class MarymakeProvider(PublicStoreProvider):
    async def crawl(self, http):
        response = await http.get(self.config['catalog_url'])
        return self.parse_listing(response.text, str(response.url))

    def parse_listing(self, html, url):
        soup, products = BeautifulSoup(html, 'html.parser'), {}
        buttons = [a for a in soup.select('a[href]') if a.get_text(' ', strip=True).casefold() in {'купить','скачать','подробнее','подробней'}]
        if not buttons:
            raise CatalogFetchError('Marymake catalog rows missing')
        for a in buttons:
            row = a.find_parent(class_='row')
            if row is None:
                raise CatalogFetchError('Marymake row structure changed')
            raw_url = urlsplit(urljoin(url,a['href']))
            if raw_url.hostname not in {urlsplit(self.base_url).hostname, 'www.'+urlsplit(self.base_url).hostname}:
                raise CatalogFetchError('Marymake product changed origin')
            path = raw_url.path.split('/post-preview/')[0].rstrip('/')
            product_url = urlunsplit((raw_url.scheme,raw_url.netloc,path,'',''))
            blocks = [n.get_text(' ',strip=True) for n in row.select('.text-box') if n.get_text(' ',strip=True)]
            if not blocks:
                raise CatalogFetchError('Marymake product name missing')
            name, description = blocks[0], row.get_text(' ',strip=True)
            price_match = re.search(r'(\d[\d\s]*[.,]?\d*)\s*RUB\b', description)
            price = money(price_match[1]) if price_match else money('0') if 'бесплатно' in description.casefold() else None
            images = []
            for img in row.select('img[data-base-path][data-file-name]'):
                images.append(urljoin(url,img['data-base-path']+'1000-'+img['data-file-name']))
            categories = [name]
            if "BIRDY" in name:
                categories.append("Блузы")
            if "BAG" in name:
                categories.append("Сумки")
            p = product_from_values(self.config,key=product_url,name=name,url=product_url,price=price,
                currency='RUB',images=images,categories=categories,description=description)
            if p:
                level = re.search(r'Уровень сложности:\s*(новичок|продолжающий|продвинутый|средний)',description,re.I)
                if level:
                    p=replace(p,difficulty=level[1],is_beginner=level[1].casefold()=='новичок').normalized()
                old=products.get(product_url)
                # The same pattern is sold with/without a video course. These
                # are price options, never an invented sale or duplicate model.
                if old is None or (p.price is not None and (old.price is None or p.price < old.price)):
                    products[product_url]=p
        return list(products.values())

    def parse_gallery(self, html, product_url):
        soup=BeautifulSoup(html,'html.parser')
        return tuple(dict.fromkeys(urljoin(product_url,n['data-base-path']+'1000-'+n['data-file-name'])
            for n in soup.select('img[data-base-path][data-file-name]')))
