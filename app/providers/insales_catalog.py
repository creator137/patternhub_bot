"""Public catalogs investigated together; these stores are not all InSales.

Only manufacturer HTML, sitemaps and public storefront data are consumed. No
account endpoints, purchased files, JavaScript execution or authenticated API.
"""
from dataclasses import replace
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.providers.public_http import CatalogFetchError, RobotsRules
from app.providers.public_stores import PublicStoreProvider, WooStoreProvider
from app.providers.store_common import money, plain, product_from_values


def _soup(text):
    return BeautifulSoup(text, 'html.parser')


def _text(root, selector):
    node = root.select_one(selector)
    return node.get('content') or node.get('value') or node.get_text(' ', strip=True) if node else None


def _options(root, selector):
    return tuple(dict.fromkeys(n.get_text(' ', strip=True) for n in root.select(selector)
                               if n.get('value', '').strip()))


async def _sitemap_urls(http, start, limit):
    pending, visited, urls = [start], set(), []
    while pending:
        url = pending.pop(0)
        if url in visited or len(visited) >= 30:
            raise CatalogFetchError('Sitemap repeated or nesting limit')
        visited.add(url)
        response = await http.get(url)
        root = ET.fromstring(response.content)
        locations = [n.text.strip() for child in root for n in child
                     if n.tag.split('}')[-1] == 'loc' and n.text]
        kind = root.tag.split('}')[-1]
        if kind == 'sitemapindex':
            pending.extend(locations)
        elif kind == 'urlset':
            urls.extend(locations)
        else:
            raise CatalogFetchError('Unexpected sitemap structure')
        if len(urls) > limit:
            raise CatalogFetchError('Sitemap product safety limit')
    return list(dict.fromkeys(urls))


class OctoberCatalogProvider(PublicStoreProvider):
    """Shopaholic/OctoberCMS: complete public sitemap instead of blocked paging."""

    async def crawl(self, http):
        urls = await _sitemap_urls(http, self.base_url + '/sitemap.xml', self.max_pages * 4)
        urls = [u for u in urls if re.fullmatch(r'/catalog/[^/]+/[^/]+/?', urlsplit(u).path)]
        if not urls or len(urls) > self.max_pages:
            raise CatalogFetchError('October product sitemap empty/limit')
        products = []
        for url in urls:
            # Non-pattern sections are unambiguous site-owned URL taxonomy.
            if urlsplit(url).path.split('/')[2] in {'videokursy-po-shityu', 'sertifikat', 'subscribe'}:
                self.last_skipped += 1
                continue
            response = await http.get(url)
            self.add(products, self.parse_product(response.text, str(response.url)))
        return products

    def parse_product(self, text, url):
        soup = _soup(text)
        root = soup.select_one('.product-card[data-product-id]')
        if root is None or soup.select_one('h1[ymecommerce-field="name"]') is None:
            raise CatalogFetchError('October product structure missing: ' + url)
        categories = [n.get_text(' ', strip=True) for n in soup.select('.breadcrumb .breadcrumb__item')][1:-1]
        category = root.select_one('[ymecommerce-field="category"]') or soup.select_one('[ymecommerce-field="category"]')
        if category:
            categories.append(category.get('value') or category.get_text(' ', strip=True))
        product = product_from_values(self.config, key=root['data-product-id'], name=_text(soup, 'h1[ymecommerce-field="name"]'), url=url,
            categories=categories, currency='RUB', price=money(_text(root, '.product-card__price')),
            old_price=money(_text(root, '.product-card__price-old, .product-card__old-price')),
            images=[n.get('src') for n in root.select('.product-card__gallery-top img')],
            description=_text(root, '.tabs__content, .product-card__description'),
            sizes=_options(root, 'select[name*="size"] option'))
        return product

    def parse_gallery(self, html, product_url):
        root = _soup(html).select_one('.product-card[data-product-id]')
        from app.providers.gallery import clean_images
        return clean_images([n.get('src') for n in root.select('.product-card__gallery-top img')], product_url) if root else ()


def _flight_strings(soup):
    """Decode only literal JSON passed to React Flight, never eval script code."""
    for node in soup.select('script'):
        match = re.fullmatch(r'\s*self\.__next_f\.push\((.*)\)\s*;?\s*', node.get_text(), re.S)
        if not match:
            continue
        try:
            value = json.loads(match[1])
        except ValueError:
            continue
        if isinstance(value, list) and len(value) == 2 and isinstance(value[1], str):
            yield value[1]


class AnsewsCatalogProvider(PublicStoreProvider):
    """Next.js public JSON-LD and literal Flight metadata; full sitemap crawl."""

    async def crawl(self, http):
        urls = await _sitemap_urls(http, self.base_url + '/sitemap.xml', self.max_pages * 4)
        urls = [u for u in urls if re.fullmatch(r'/products/[^/]+/?', urlsplit(u).path)]
        if not urls or len(urls) > self.max_pages:
            raise CatalogFetchError('Ansews sitemap empty/limit')
        products = []
        for url in urls:
            response = await http.get(url)
            self.add(products, self.parse_product(response.text, str(response.url)))
        return products

    def parse_product(self, text, url):
        soup = _soup(text)
        candidates = []
        for node in soup.select('script[type="application/ld+json"]'):
            value = json.loads(node.get_text())
            nodes = value if isinstance(value, list) else value.get('@graph', [value])
            candidates.extend(n for n in nodes if n.get('@type') == 'Product')
        own = [n for n in candidates if urlsplit(n.get('url', '')).path.rstrip('/') == urlsplit(url).path.rstrip('/')]
        if len(own) != 1:
            raise CatalogFetchError('Ansews own Product JSON-LD missing: ' + url)
        data = own[0]
        flight = '\n'.join(_flight_strings(soup))
        slug = urlsplit(url).path.rstrip('/').split('/')[-1]
        identity = re.search(r'"productId":"([^"\s]+)","productSlug":' + re.escape(json.dumps(slug)), flight)
        if not identity:
            raise CatalogFetchError('Ansews stable product ID missing: ' + url)
        key = identity[1]
        categories = [data['category']] if data.get('category') else []
        offer = data.get('offers') or {}
        if not isinstance(offer, dict) or offer.get('@type') != 'Offer':
            raise CatalogFetchError('Ansews exact offer missing: ' + url)
        sizes, heights = set(), set()
        # Variants must refer to this product; recommendation widgets are ignored.
        for match in re.finditer(r'\{"id":"[^"\s]+","productId":' + re.escape(json.dumps(key)), flight):
            try:
                row, _ = json.JSONDecoder().raw_decode(flight[match.start():])
            except ValueError:
                continue
            attrs = row.get('attributesJson') or {}
            if attrs.get('pa_razmer'):
                sizes.add(str(attrs['pa_razmer']))
            if attrs.get('pa_rost'):
                heights.add(str(attrs['pa_rost']))
        images = data.get('image') or []
        if isinstance(images, str):
            images = [images]
        product = product_from_values(self.config, key=key, name=data['name'], url=data['url'],
            categories=categories, currency=offer.get('priceCurrency'), price=money(offer.get('price')),
            images=images, description=data.get('description'), sizes=sorted(sizes), heights=sorted(heights),
            available=offer.get('availability', '').rsplit('/', 1)[-1] not in {'OutOfStock', 'Discontinued'})
        return product

    def parse_gallery(self, html, product_url):
        p = self.parse_product(html, product_url)
        return p.image_urls or () if p else ()


class ShapeCatalogProvider(PublicStoreProvider):
    """Small custom SSR storefront, all categories linked in its public menu."""

    async def crawl(self, http):
        response = await http.get(self.base_url + '/')
        soup = _soup(response.text)
        sections = {urljoin(self.base_url, a['href']): a.get_text(' ', strip=True)
                    for a in soup.select('a[href^="/models/cats/?cat="]')}
        if not sections:
            raise CatalogFetchError('Shape category menu missing')
        urls = {urljoin(self.base_url, a['href']).rstrip('/') for a in soup.select('a[href^="/model/"]')}
        labels = {}
        for section, label in sections.items():
            r = await http.get(section)
            page = _soup(r.text)
            # No pagination exists on the audited store; fail closed if introduced.
            if page.select('.pagination, a[rel="next"]'):
                raise CatalogFetchError('Shape unexpected pagination')
            for a in page.select('a[href^="/model/"]'):
                url = urljoin(self.base_url, a['href']).rstrip('/')
                urls.add(url)
                labels.setdefault(url, []).append(label)
        if not urls or len(urls) + len(sections) > self.max_pages:
            raise CatalogFetchError('Shape empty catalog/limit')
        products = []
        for url in sorted(urls):
            r = await http.get(url)
            self.add(products, self.parse_product(r.text, str(r.url), labels.get(url, [])))
        return products

    def parse_product(self, text, url, categories=()):
        soup = _soup(text)
        root = soup.select_one('#model')
        if root is None or root.select_one('h1') is None:
            raise CatalogFetchError('Shape product structure missing: ' + url)
        identity = re.fullmatch(r'/model/(\d+)/?', urlsplit(url).path)
        if not identity:
            raise CatalogFetchError('Shape article missing')
        price_text = _text(root, 'h2')
        price = money(price_text)
        if price_text and 'бесплатно' in price_text.casefold():
            price = money('0')
        return product_from_values(self.config, key=identity[1], name=_text(root, 'h1'), url=url,
            categories=categories, currency='RUB', price=price,
            images=[n.get('src') for n in root.select('.carousel img')
                    if '/Data/models/' in (n.get('src') or '') and '/size.' not in n.get('src','')],
            sizes=_options(root, 'select[name="size"] option'), heights=_options(root, 'select[name="height"] option'),
            description=_text(root, '#info'))


class LokoCatalogProvider(WooStoreProvider):
    """Woo Store API after the hosting's public, non-authentication cookie.

    Beget's HTML asks every browser to set exactly beget=begetok and reload.
    Recognize that exact bootstrap, set only that cookie and re-read robots.
    It is neither an account credential nor access to purchased content.
    """

    async def crawl(self, http):
        response = await http.get(self.base_url + '/')
        if "document.cookie='beget=begetok'" in response.text and 'location.reload()' in response.text:
            http.client.cookies.set('beget', 'begetok', domain=urlsplit(self.base_url).hostname)
            robots = await http._request(self.base_url + '/robots.txt')
            if robots.status_code not in {200, 404}:
                raise CatalogFetchError('Loko robots unavailable after public bootstrap')
            if 'set_cookie()' in robots.text:
                raise CatalogFetchError('Loko public bootstrap not accepted')
            http.robots = RobotsRules(robots.text if robots.status_code == 200 else '')
        return await super().crawl(http)
