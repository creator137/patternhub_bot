"""Public Bitrix storefronts, including custom storefront templates.

Only public HTML and sitemap indexes are read. In particular, a blocked PAGEN
URL is never substituted with a private Bitrix AJAX endpoint.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

from bs4 import BeautifulSoup

from app.providers.public_http import CatalogFetchError
from app.providers.public_stores import PublicStoreProvider
from app.providers.store_common import money, product_from_values


SITE_OPTIONS = {
    'patternclo': {'strategy': 'sitemap', 'product_path': r'^/catalog/.+/.+/$'},
    'easysew': {'strategy': 'sitemap', 'product_path': r'^/catalogy/\d+/\d+/$'},
    'lspatterns': {'strategy': 'sitemap', 'product_path': r'^/collection/.+/.+/$'},
    'yasew': {'strategy': 'sitemap', 'product_path': r'^/catalog/.+/.+/$'},
    'wantandsew': {'strategy': 'sections', 'product_path': r'^/catalog/.+/.+/$'},
    'kapsulestore': {'strategy': 'listing', 'product_path': r'^/catalog/[^/]+/$'},
    'vikroy_ka': {'strategy': 'listing', 'catalog_paths': ['/pattern/models/', '/pattern/base/'],
                  'product_path': r'^/pattern/m/[^/]+/$'},
}


def value(node):
    return (node.get('content') or node.get_text(' ', strip=True)) if node else None


class BitrixCatalogProvider(PublicStoreProvider):
    """Configurable adapter; source defaults describe audited public templates."""

    def __init__(self, config, *, max_pages=3000, transport=None):
        super().__init__(config, max_pages=max_pages, transport=transport)
        self.options = {**SITE_OPTIONS.get(self.source, {}), **config.get('bitrix', {})}
        self.pages_crawled = 0

    async def crawl(self, http):
        self.pages_crawled = 0
        url = self.config['catalog_url']
        response = await http.get(url)
        soup = BeautifulSoup(response.content, 'html.parser')
        self.pages_crawled += 1
        if self.options.get('strategy') in {'listing', 'sections'}:
            return await self.crawl_listings(http, soup, str(response.url))
        urls = await self.sitemap_urls(http)
        pattern = re.compile(self.options['product_path'])
        candidates = {u for u in urls if pattern.match(urlsplit(u).path)
                      and '/filter/' not in u and not urlsplit(u).query}
        # Sitemaps sometimes include category nodes. Keep leaves, plus every
        # product currently linked by the actual storefront (fresh releases).
        candidates = {u for u in candidates if not any(
            v != u and v.startswith(u.rstrip('/') + '/') for v in candidates)}
        for card in self.cards(soup):
            link = self.card_link(card)
            if link:
                candidates.add(urljoin(str(response.url), link['href']))
        if not candidates or len(candidates) > self.max_pages:
            raise CatalogFetchError('Empty/oversized Bitrix product sitemap')
        products = []
        # Bounded concurrency on a single HTTP session. All failures propagate;
        # a partial detail crawl must never reconcile a source as complete.
        semaphore = asyncio.Semaphore(2)

        async def read(u):
            async with semaphore:
                try:
                    r = await http.get(u)
                except CatalogFetchError as error:
                    # Stale public sitemap entries can point to deleted models.
                    # Only an actual 404/410 is a verified removal, never timeout.
                    if re.match(r'HTTP (?:404|410): ', str(error)):
                        return None
                    raise
                self.pages_crawled += 1
                return self.parse_detail(r.text, str(r.url))

        for offset in range(0, len(candidates), 20):
            batch = sorted(candidates)[offset:offset + 20]
            rows = await asyncio.gather(*(read(u) for u in batch), return_exceptions=True)
            failures = [row for row in rows if isinstance(row, BaseException)]
            if failures:
                raise failures[0]
            for p in rows:
                self.add(products, p)
        total_node = soup.select_one('[data-total][data-page-count]')
        if total_node and len({p.source_product_id or p.product_url for p in products}) + self.last_skipped < int(total_node['data-total']):
            raise CatalogFetchError('Product sitemap contains fewer products than listing total')
        return products

    async def sitemap_urls(self, http):
        pending = [self.base_url + '/sitemap.xml']
        visited, urls = set(), set()
        while pending:
            url = pending.pop(0)
            if url in visited:
                continue  # Bitrix often repeats the very same sitemap entry.
            if len(visited) >= 40:
                raise CatalogFetchError('Bitrix sitemap limit')
            visited.add(url)
            response = await http.get(url)
            self.pages_crawled += 1
            root = ET.fromstring(response.content)
            locs = [n.text.strip() for entry in root for n in entry
                    if n.tag.split('}')[-1] == 'loc' and n.text]
            if root.tag.split('}')[-1] == 'sitemapindex':
                pending.extend(locs)
            elif root.tag.split('}')[-1] == 'urlset':
                urls.update(locs)
            else:
                raise CatalogFetchError('Invalid public sitemap structure')
        return urls

    @staticmethod
    def cards(soup):
        return soup.select('.card-product, .catalog-item, article.product-cat, .catalog_block .catalog_item, a.square[href*="/catalogy/"]')

    @staticmethod
    def card_link(card):
        if card.name == 'a' and card.get('href'):
            return card
        return card.select_one('.card-product__link[href], .product-cat-title a[href], .item-title a[href], a[item_id][href], a[href]')

    async def crawl_listings(self, http, soup, url):
        products, visited, pending = [], set(), [(url, soup)]
        pending.extend((urljoin(self.base_url, p), None)
                       for p in self.options.get('catalog_paths', []) if urljoin(self.base_url, p) != url)
        while pending:
            url, soup = pending.pop(0)
            if url in visited:
                continue
            if len(visited) >= self.max_pages:
                raise CatalogFetchError('Bitrix listing limit')
            visited.add(url)
            if soup is None:
                r = await http.get(url)
                self.pages_crawled += 1
                soup = BeautifulSoup(r.content, 'html.parser')
            cards = self.cards(soup)
            for card in cards:
                self.add(products, self.parse_card(card, url))
            # Only follow actual server-rendered navigation. HTTP enforces robots.
            pages = [urljoin(url, a['href']) for a in soup.select('a[href]')
                     if re.search(r'[?&]PAGEN_\d+=\d+', a['href'])]
            # Sort/view preferences are unrelated to pagination. A single
            # canonical query also prevents crawling every sort permutation.
            pages = [urlunsplit((*urlsplit(u)[:3], urlencode([(k,v) for k,v in parse_qsl(urlsplit(u).query)
                       if re.fullmatch(r'PAGEN_\d+', k)]), '')) for u in pages]
            pending.extend((u, None) for u in dict.fromkeys(pages) if u not in visited)
            if self.options.get('strategy') == 'sections':
                for a in soup.select('.section_item a[href], li.sect a[href]'):
                    u = urljoin(url, a['href'])
                    if not re.search(r'kurs|marafon|sertifikat|na_zakaz', u) and u not in visited:
                        pending.append((u, None))
            if not cards and not pending:
                raise CatalogFetchError('Bitrix catalog has no recognized products')
        return products

    def parse_card(self, card, url):
        if self.source == 'easysew':
            product_url = urljoin(url, card['href'])
            spans = [n.get_text(' ', strip=True) for n in card.select('span') if 'free_sw' not in n.get('class', [])]
            match = re.search(r'url\([\'"]?([^\)\'"]+)', card.get('style', ''))
            section = urlsplit(product_url).path.strip('/').split('/')[1]
            categories = [{'1':'Мужские выкройки','2':'Женские выкройки','3':'Детские выкройки'}.get(section, '')]
            return product_from_values(self.config, key=urlsplit(product_url).path.strip('/').split('/')[-1],
                name=' '.join(spans), url=product_url, categories=categories, currency='RUB',
                price=money('0') if card.select_one('.free_sw') else None,
                images=[match[1]] if match else [])
        link = self.card_link(card)
        title = card.select_one('.catalog-item__name, .card-product__link, .product-cat-title, .item-title')
        if not link or not title:
            raise ValueError('Bitrix product title/link missing')
        key_node = card.select_one('[item_id], [data-id]')
        key = (key_node.get('item_id') or key_node.get('data-id')) if key_node else None
        price = card.select_one('.catalog-item__price, .price-row__price-current, .product-cat-price-current, .price_value')
        old = card.select_one('.price-row__price-old, .product-cat-price-old, .discount-price')
        images = [n.get('data-src') or n.get('src') for n in card.select('img')]
        product_url = urljoin(url, link['href'])
        categories = []
        if self.source == 'wantandsew':
            for part, label in {'zhenskie_vykroyki':'Женские выкройки', 'detskie_vykroyki':'Детские выкройки',
                'muzhskie_vykroyki':'Мужские выкройки', 'vykroyki_dlya_mladentsev_':'Детские выкройки',
                'bazovye_lekala':'Базовые лекала', 'aksessuary':'Аксессуары'}.items():
                if '/'+part+'/' in url:
                    categories.append(label)
        if self.source == 'vikroy_ka':
            categories.append(value(title))  # Explicit "для мальчиков" etc, not garment-name guessing.
            if '/base/' in url:
                categories.append('Базовые лекала')
        return product_from_values(self.config, key=key or product_url, name=value(title), url=product_url,
            price=money(value(price)), old_price=money(value(old)), currency='RUB', images=images, categories=categories)

    def parse_detail(self, html, url):
        soup = BeautifulSoup(html, 'html.parser')
        h1 = soup.select_one('h1')
        if h1 is None:
            raise ValueError('Bitrix detail title missing: ' + url)
        categories = [n.get_text(' ', strip=True) for n in soup.select(
            '.bx-breadcrumb a, .breadcrumbs a, .breadcrumb a, .bread a')]
        if self.source == 'easysew':
            # Numeric sections are explicitly labelled in the site's navigation.
            audience_sections = {'1': 'Мужские выкройки', '2': 'Женские выкройки', '3': 'Детские выкройки'}
            for a in soup.select('.bx-breadcrumb a[href]'):
                match = re.fullmatch(r'/catalogy/([123])/', urlsplit(a['href']).path)
                if match:
                    categories.append(audience_sections[match[1]])
        root = soup.select_one('.product-detail__info') or soup.select_one('.product-detail') or soup
        key = None
        if self.source == 'patternclo':
            node = soup.select_one('[id^="elemnt_"]')
            key = node['id'].split('_')[-1] if node else None
        elif self.source == 'easysew':
            key = urlsplit(url).path.strip('/').split('/')[-1]
        elif self.source == 'lspatterns':
            if soup.select_one('.product-detail__info') is None:
                return None  # Category recommendations are not its own offer.
            node = root.select_one('.btn-favorite[data-id]')
            key = node['data-id'] if node else None
            if key is None:
                if soup.select_one('.slider-product__main') is None:
                    return None  # Empty category leaf, not a product offer.
                raise ValueError('LS product ID missing: ' + url)
        elif self.source == 'yasew':
            node = soup.select_one('[id^="bx_"][id$="_big_slider"]')
            match = re.match(r'bx_\d+_(\d+)_big_slider', node['id']) if node else None
            key = match[1] if match else None
        elif self.source == 'vikroy_ka':
            node = soup.select_one('.product-price-button .btn-primary[data-id]')
            key = node['data-id'] if node else None
        price = root.select_one('[itemprop="price"]') or soup.select_one('[itemprop="price"]')
        price = price or root.select_one('.price-row__price-current, .catalog-price, .price_value, .product__price')
        old = root.select_one('.price-row__price-old, .product-cat-price-old, .old_price, .discount-price')
        if self.source == 'easysew' and price:
            old = price.parent.select_one('s, del')
        if price is None:
            # A sitemap leaf can be an empty garment category, not a product.
            if soup.select('.section_item, .catalog-section, .bx_sitemap'):
                return None
            raise ValueError('Bitrix product price markup missing: ' + url)
        price_text = value(price)
        current = money(price_text)
        if price_text and re.search(r'бесплатн', price_text, re.I):
            current = money('0')
        # Never treat a subscription's monthly amount as the pattern's price.
        if self.source == 'yasew' and price.find_parent(class_='product-cat'):
            raise ValueError('Only recommendation price found: ' + url)
        images = [n.get('href') for n in soup.select('.carousel-inner a[data-fancybox][href], .slider-product__main a.js-gallery-item[href]')]
        images += [n.get('data-src') or n.get('src') or n.get('content') for n in soup.select(
            '[itemprop="image"], .product-item-detail-slider-image img, .product-detail-slider-image img')]
        if self.source == 'easysew':
            # The site's main product images precede the unrelated account icons.
            images += [n.get('href') for n in soup.select('a[href*="/upload/iblock/"]')]
        cover = soup.select_one('meta[property="og:image"]')
        if not any(images) and cover:
            images.append(cover.get('content'))
        description = soup.select_one('[itemprop="description"], .product-detail__description, .product-description')
        available_node = soup.select_one('[itemprop="availability"]')
        product = product_from_values(self.config, key=key, name=value(h1), url=url,
            price=current, old_price=money(value(old)), currency='RUB', categories=categories,
            images=images, description=value(description),
            available='OutOfStock' not in str(available_node))
        if product:
            sizes = tuple(n.get_text(' ', strip=True) for n in soup.select('#sizes-wrap-second .input-radio-params__custom'))
            heights = tuple(n.get_text(' ', strip=True) for n in soup.select('#heights-wrap-second .input-radio-params__custom'))
            badge = any(re.search(r'новинка', n.get_text(), re.I) for n in root.select('.label, .product-cat-label-text-item'))
            product = replace(product, sizes=sizes or None, heights=heights or None, source_new_badge=badge).normalized()
        return product

    def parse_gallery(self, html, product_url):
        product = self.parse_detail(html, product_url)
        return product.image_urls or () if product else ()
