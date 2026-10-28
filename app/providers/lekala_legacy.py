"""Public model-number catalogs used by Leko Mail and Latelye.

Only HTML catalog pages and preview-image URLs are read. Registration, saving,
ordering, measurement submission and downloadable pattern files are untouched.
"""
from dataclasses import replace
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from app.models.categories import normalize_category, CATEGORIES
from app.providers.public_http import CatalogFetchError
from app.providers.public_stores import PublicStoreProvider
from app.providers.store_common import product_from_values, money


class LekalaLegacyProvider(PublicStoreProvider):
    async def crawl(self, http):
        url = self.base_url + '/mod-p.php'
        response = await http.get(url)
        soup = BeautifulSoup(response.content, 'html.parser')
        audiences = {'0':'women','1':'men','2':'kids','3':'kids','33':'kids','4':'women','5':'men'}
        starts = {url:(None, 'women', False)}
        known = {c.name for c in CATEGORIES} - {'Другое'}
        # Explicit catalog navigation supplies the audience and garment type.
        for a in soup.select('a[href]'):
            target = urljoin(url, a['href'])
            q = parse_qs(urlsplit(target).query)
            if urlsplit(target).path != '/mod-p.php' or set(q)-{'t','a','f'}:
                continue
            if 't' not in q:
                continue
            label = a.get_text(' ', strip=True)
            category = normalize_category(label)
            t = q['t'][0]
            if 'a' not in q or category in known or 'Все модели' in label:
                starts[target] = (category if category in known else None, audiences.get(t), q.get('f') == ['1'])
        products, page_count = {}, 0
        sections = list(starts.items())
        while sections:
            start, (category, audience, free) = sections.pop(0)
            pending, visited, fingerprints = [start], set(), set()
            startq = parse_qs(urlsplit(start).query)
            while pending:
                current = pending.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                page_count += 1
                if page_count > self.max_pages:
                    raise CatalogFetchError('Legacy catalog page limit')
                if current == url:
                    page = soup
                else:
                    r = await http.get(current)
                    page = BeautifulSoup(r.content, 'html.parser')
                for a in page.select('a[href]'):
                    target = urljoin(current, a['href'])
                    q = parse_qs(urlsplit(target).query)
                    label = a.get_text(' ', strip=True)
                    cat = normalize_category(label)
                    if (urlsplit(target).path == '/mod-p.php' and 't' in q
                            and not (set(q)-{'t','a','f'}) and target not in starts
                            and ('a' not in q or cat in known or 'Все модели' in label)):
                        entry = (cat if cat in known else None,audiences.get(q['t'][0]),q.get('f')==['1'])
                        starts[target] = entry
                        sections.append((target,entry))
                rows = self.parse_page(page, current, category, audience, free)
                fingerprint = tuple(p.source_product_id for p in rows)
                if fingerprint and fingerprint in fingerprints:
                    raise CatalogFetchError('Legacy catalog pagination repeated')
                fingerprints.add(fingerprint)
                if not rows:
                    raise CatalogFetchError('Legacy catalog empty or markup changed: ' + current)
                for p in rows:
                    old = products.get(p.source_product_id)
                    if old:
                        products[p.source_product_id] = replace(old,
                            category=p.category if old.category in {None,'Другое'} and p.category else old.category,
                            price=p.price if p.is_free else old.price,
                            is_free=old.is_free or p.is_free).normalized()
                    else:
                        products[p.source_product_id] = p
                index = int(parse_qs(urlsplit(current).query).get('n', ['0'])[0])
                for a in page.select('a[href]'):
                    target = urljoin(current, a['href'])
                    q = parse_qs(urlsplit(target).query)
                    if 'n' not in q or 'mod' in q or not q['n'][0].isdigit():
                        continue
                    if int(q['n'][0]) <= index:
                        continue
                    if any(q.get(k, ['0']) != startq.get(k, ['0']) for k in ['t','a','f']):
                        continue
                    if target not in visited and target not in pending:
                        pending.append(target)
                pending.sort(key=lambda u:int(parse_qs(urlsplit(u).query).get('n',['0'])[0]))
        return list(products.values())

    def parse_page(self, soup, url, category=None, audience=None, free=False):
        products = []
        for image in soup.select('img[src]'):
            match = re.search(r'(?:^|/)(?:i|ipm)/(\d+)\.(?:jpg|png)$', image['src'], re.I)
            if not match:
                continue
            key = match[1]
            card = image.find_parent('td')
            if card is None:
                raise ValueError('Legacy model card missing')
            link = next((a for a in card.select('a[href]') if parse_qs(urlsplit(a['href']).query).get('mod') == [key]
                         and urlsplit(a['href']).path.endswith('mod-p.php')
                         and 'reg' not in parse_qs(urlsplit(a['href']).query)), None)
            if link is None:
                raise ValueError('Legacy product link missing')
            pictures = [urljoin(url,image['src'])]
            hover = re.search(r"this\.src=['\"]([^'\"]+)", image.get('onmouseover', ''))
            if hover:
                pictures.append(urljoin(url,hover[1]))
            product = product_from_values(self.config, key=key, name='Выкройка №'+key,
                url=urljoin(url,link['href']), categories=[category] if category else [],
                images=pictures, price=money('0') if free else None, currency='RUB' if free else None)
            if product:
                products.append(replace(product,audience=audience).normalized())
        return products
