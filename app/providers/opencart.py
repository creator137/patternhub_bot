"""Public OpenCart XML catalogs and server-rendered product pages.

No cart/account calls, downloads or authenticated APIs are used. A crawl is
atomic: the shared provider discards partial snapshots on any fetch/parse error.
"""
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from app.providers.public_http import CatalogFetchError
from app.providers.public_stores import PublicStoreProvider
from app.providers.store_common import is_pattern, money, plain, product_from_values


class OpenCartProvider(PublicStoreProvider):
    """Config: sitemap_url, or listing_urls for explicitly audited sections.

    max_pages bounds *all* fetched XML/listing/detail pages, not individual
    categories. Reaching the bound never produces a complete snapshot.
    """

    async def crawl(self, http):
        self._pages = 0
        if self.config.get('listing_urls'):
            return await self._listings(http)
        pending = [self.config.get('sitemap_url') or
                   self.base_url + '/index.php?route=extension/feed/google_sitemap']
        visited, entries, contexts = set(), {}, {}
        while pending:
            url = pending.pop(0)
            if url in visited:
                raise CatalogFetchError('OpenCart sitemap loop')
            visited.add(url)
            response = await self._get(http, url)
            root = ET.fromstring(response.content)
            kind = root.tag.split('}')[-1]
            if kind not in {'sitemapindex', 'urlset'}:
                raise CatalogFetchError('OpenCart invalid sitemap root')
            for entry in root:
                loc = next((n.text for n in entry if n.tag.split('}')[-1] == 'loc'), None)
                if not loc:
                    raise CatalogFetchError('OpenCart sitemap entry without location')
                loc = urljoin(str(response.url), loc).split('#')[0]
                if kind == 'sitemapindex':
                    pending.append(loc)
                    continue
                # OpenCart's public google_sitemap marks product rows with
                # image:image. Category/information aliases have no image.
                images = [n for n in entry if n.tag.split('}')[-1] == 'image']
                slug = urlsplit(loc).path.rstrip('/').rsplit('/', 1)[-1]
                contexts.setdefault(slug, []).append(loc)
                if images:
                    caption = next((n.text for n in images[0]
                                    if n.tag.split('}')[-1] in {'caption', 'title'}), '')
                    entries.setdefault(loc, caption)
        if not entries:
            raise CatalogFetchError('OpenCart sitemap has no product entries')
        products = []
        for url, caption in entries.items():
            if caption and not is_pattern(caption):
                self.last_skipped += 1
                continue
            response = await self._get(http, url)
            slug = urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1]
            product = self.parse_product(response.text, str(response.url), contexts.get(slug, ()))
            self.add(products, product)
        return self._unique(products)

    async def _get(self, http, url):
        if self._pages >= self.max_pages:
            raise CatalogFetchError('OpenCart page limit')
        self._pages += 1
        return await http.get(url)

    async def _listings(self, http):
        products, visited = [], set()
        for start in dict.fromkeys(self.config['listing_urls']):
            url = urljoin(self.base_url + '/', start)
            section_links, seen_pages, expected = set(), set(), None
            while url:
                if url in visited:
                    raise CatalogFetchError('OpenCart pagination loop')
                visited.add(url)
                response = await self._get(http, url)
                soup = BeautifulSoup(response.text, 'html.parser')
                cards = soup.select('#content .product-layout, #content .product-grid .product, '
                                    '#content .product-list .product, #content .product-grid > div > .product')
                # Journal/OC2 custom themes put product cards in content directly.
                if not cards:
                    cards = soup.select('#content .product')
                if not cards:
                    cards = soup.select('#content .name-actions')
                links = {}
                for card in cards:
                    anchor = card.select_one('.name a[href], h4 a[href], .caption a[href]')
                    if not anchor:
                        raise CatalogFetchError('OpenCart listing product link missing')
                    links[urljoin(str(response.url), anchor['href'])] = anchor.get_text(' ', strip=True)
                if not links:
                    content = soup.select_one('#content')
                    if content and re.search(r'нет товаров|категори\w* пуста|в этой категории нет', content.get_text(' ', strip=True), re.I):
                        break
                    raise CatalogFetchError('OpenCart empty listing')
                fingerprint = tuple(sorted(links))
                if fingerprint in seen_pages:
                    raise CatalogFetchError('OpenCart repeated listing page')
                seen_pages.add(fingerprint)
                section_links.update(links)
                totals = re.search(r'Показано\s+с\s+\d+\s+по\s+\d+\s+из\s+(\d+)', soup.get_text(' ', strip=True), re.I)
                if totals:
                    count = int(totals[1])
                    if expected is not None and expected != count:
                        raise CatalogFetchError('OpenCart listing total changed')
                    expected = count
                for link, title in links.items():
                    if not is_pattern(title):
                        self.last_skipped += 1
                        continue
                    if any(p.product_url == link for p in products):
                        continue
                    detail = await self._get(http, link)
                    self.add(products, self.parse_product(detail.text, str(detail.url), (url,)))
                next_link = soup.select_one('link[rel="next"][href], .pagination a[rel="next"][href]')
                if not next_link:
                    next_link = next((a for a in soup.select('.pagination a[href]')
                                      if a.get_text(strip=True) in {'>', '›', '→', 'Следующая', 'Далее'}), None)
                if next_link:
                    url = urljoin(str(response.url), next_link['href'])
                else:
                    current = soup.select_one('.pagination .active')
                    numbers = [int(a.get_text(strip=True)) for a in soup.select('.pagination a')
                               if a.get_text(strip=True).isdigit()]
                    if numbers and (not current or not current.get_text(strip=True).isdigit()
                                    or max(numbers) > int(current.get_text(strip=True))):
                        raise CatalogFetchError('OpenCart next page missing')
                    if expected is not None and len(section_links) != expected:
                        raise CatalogFetchError('OpenCart listing truncated')
                    url = None
        return self._unique(products)

    @staticmethod
    def _unique(products):
        result = {}
        for product in products:
            key = product.source_product_id
            if key in result and result[key].name != product.name:
                raise CatalogFetchError('OpenCart conflicting product identity')
            result.setdefault(key, product)
        return list(result.values())

    def parse_product(self, html, url, context_urls=()):
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.select_one('#content h1, h1[itemprop="name"], h1')
        identity = soup.select_one('input[name="product_id"][value]')
        if title is None or identity is None or not re.fullmatch(r'[1-9]\d*', identity['value']):
            raise CatalogFetchError('OpenCart product title/ID missing: ' + url)
        name = title.get_text(' ', strip=True)
        canonical = soup.select_one('link[rel="canonical"][href]')
        product_url = urljoin(url, canonical['href']) if canonical else url
        if urlsplit(product_url).hostname != urlsplit(url).hostname:
            raise CatalogFetchError('OpenCart foreign canonical')
        canonical_id = parse_qs(urlsplit(product_url).query).get('product_id')
        if canonical_id and canonical_id != [identity['value']]:
            raise CatalogFetchError('OpenCart conflicting canonical ID')
        categories = [a.get_text(' ', strip=True) for a in soup.select('.breadcrumb li')][1:-1]
        for candidate in [url, *context_urls]:
            for slug, label in self.config.get('section_labels', {}).items():
                if slug.strip('/') in urlsplit(candidate).path.strip('/').split('/'):
                    categories.append(label)
        categories = list(dict.fromkeys(c for c in categories if c))
        price_node = soup.select_one('[itemprop="price"]')
        if price_node is None:
            price_node = soup.select_one('#content .price-new, #content #price-new, #content .price')
        old_node = soup.select_one('#content .price-old, #content #price-old')
        price = money(price_node.get('content') or price_node.get_text(' ', strip=True)) if price_node else None
        old = money(old_node.get_text(' ', strip=True)) if old_node else None
        currency = soup.select_one('[itemprop="priceCurrency"]')
        currency = currency.get('content') or currency.get_text(strip=True) if currency else self.config.get('currency', 'RUB')
        images = []
        # Scope to actual gallery, not related products or menu logos.
        for node in soup.select('#mainimage, [itemprop="image"], .thumbnails a[href], '
                                '#content .image a.thumbnail[href], #content .product-info .image a[href]'):
            image = node.get('data-main-popup') or node.get('data-src') or node.get('href') or node.get('src') or node.get('content')
            if image:
                images.append(urljoin(url, image))
        if not images:
            cover = soup.select_one('meta[property="og:image"][content]')
            if cover:
                images.append(urljoin(url, cover['content']))
        sizes, heights = [], []
        for group in soup.select('#product .form-group, #content .options .form-group'):
            label = group.select_one('.control-label, label')
            label = plain(label).casefold() if label else ''
            values = [n.get_text(' ', strip=True) for n in group.select('option[value]:not([value=""]), .radio-block label')]
            if 'размер' in label:
                sizes.extend(values)
            elif 'рост' in label:
                heights.extend(values)
        availability = soup.select_one('[itemprop="availability"]')
        status = (availability.get('href') or availability.get('content') or '') if availability else ''
        stock = soup.select_one('#content .stock')
        available = not any(x in status.casefold() for x in ['outofstock', 'discontinued', 'preorder'])
        if stock and re.search(r'нет в наличии|отсутствует|ожидается', stock.get_text(), re.I):
            available = False
        description = soup.select_one('#tab-description, [itemprop="description"]')
        return product_from_values(self.config, key=identity['value'], name=name, url=product_url,
            price=price, old_price=old, currency=currency, categories=categories, images=images,
            sizes=sizes, heights=heights, available=available,
            description=str(description) if description else None)

    def parse_gallery(self, html, product_url):
        product = self.parse_product(html, product_url)
        return product.image_urls or () if product else ()
