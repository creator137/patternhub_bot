"""Audited public-store adapters; every source uses the shared ParsedProduct."""
import json
import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit, urlencode

from bs4 import BeautifulSoup

from app.providers.base import BaseProvider, ProviderResult
from app.providers.gallery import html_gallery, clean_images
from app.providers.public_http import PublicCatalogHTTP, CatalogFetchError
from app.providers.store_common import money, plain, product_from_values, tilda_product, woo_image_url

logger = logging.getLogger(__name__)


class PublicStoreProvider(BaseProvider):
    def __init__(self, config, *, max_pages=None, transport=None):
        self.config = dict(config)
        self.source = config['source']
        self.base_url = config['base_url'].rstrip('/')
        self.max_pages = int(max_pages if max_pages is not None else config.get('max_pages', 1000))
        self.transport = transport
        self.requests_made = self.retries_made = self.last_skipped = 0

    async def fetch_products(self):
        self.last_skipped = 0
        http = PublicCatalogHTTP(self.base_url, transport=self.transport, timeout=self.config.get("http_timeout",30),
                                 robots_allow=self.config.get('robots_allow', ()))
        try:
            async with http:
                products = await self.crawl(http)
            unique = {}
            for p in products:
                key = p.source_product_id or p.product_url
                unique[key] = p
            if not unique:
                raise CatalogFetchError('Empty pattern snapshot')
            result = ProviderResult(list(unique.values()), skipped=self.last_skipped, complete=True)
        except (CatalogFetchError, ValueError, TypeError, KeyError, ET.ParseError) as error:
            logger.warning('Public catalog rejected source=%s error=%s detail=%s', self.source, type(error).__name__, str(error)[:250])
            result = ProviderResult([], errors=1, skipped=self.last_skipped, complete=False)
        self.requests_made, self.retries_made = http.requests_made, http.retries_made
        logger.info('Public catalog source=%s products=%s skipped=%s requests=%s retries=%s complete=%s',
                    self.source, len(result.products), result.skipped, self.requests_made, self.retries_made, result.complete)
        return result

    def add(self, products, product):
        if product is None:
            self.last_skipped += 1
        else:
            products.append(product)

    async def crawl(self, http):
        raise NotImplementedError


class WooStoreProvider(PublicStoreProvider):
    async def crawl(self, http):
        products, seen = [], set()
        expected = None
        page_size = int(self.config.get('page_size', 100))
        if not 1 <= page_size <= 100:
            raise ValueError('Woo page size must be between 1 and 100')
        endpoint = self.base_url + '/wp-json/wc/store/v1/products'
        for page in range(1, self.max_pages + 1):
            response = await http.get(endpoint + '?' + urlencode({'per_page':page_size,'page':page}))
            rows = response.json()
            if not isinstance(rows,list):
                raise CatalogFetchError('Woo products is not a list')
            if expected is None and response.headers.get('X-WP-Total'):
                expected = int(response.headers['X-WP-Total'])
            keys = {str(row['id']) for row in rows}
            if keys & seen or (not rows and expected and len(seen) < expected):
                raise CatalogFetchError('Woo pagination repeated or truncated')
            seen.update(keys)
            for row in rows:
                self.add(products, self.parse_product(row))
            total_pages = response.headers.get('X-WP-TotalPages')
            if (total_pages and page >= int(total_pages)) or (not total_pages and len(rows) < page_size):
                if expected is not None and len(seen) != expected:
                    raise CatalogFetchError('Woo total changed during pagination')
                return products
        raise CatalogFetchError('Woo pagination limit')

    def parse_product(self, row):
        if row.get('type') == 'variation' or row.get('parent'):
            return None
        prices = row.get('prices') or {}
        unit = int(prices.get('currency_minor_unit', 2))
        price = money(prices.get('price'), minor_unit=unit)
        old = money(prices.get('regular_price'), minor_unit=unit)
        old = old if price is not None and old is not None and old > price else None
        categories = [plain(c['name']) for c in row.get('categories',[]) if c.get('name')]
        sizes, heights = [], []
        for attr in row.get('attributes',[]):
            label = str(attr.get('name','')).casefold()
            values = [plain(v.get('name')) for v in attr.get('terms',[]) if v.get('name')]
            if 'размер' in label:
                sizes.extend(values)
            elif 'рост' in label:
                heights.extend(values)
        announced = any(re.search(r'анонс|скоро в продаже', category, re.I) for category in categories)
        return product_from_values(self.config, key=row['id'], name=row['name'], url=row['permalink'],
            price=price, old_price=old, currency=prices.get('currency_code'), categories=categories,
            images=[woo_image_url(i) for i in row.get('images',[]) if isinstance(i,dict)],
            description=row.get('description') or row.get('short_description'), sizes=sizes, heights=heights,
            available=bool(row.get('is_in_stock',True)) and not announced)

    def parse_gallery(self, html, product_url):
        soup = BeautifulSoup(html, 'html.parser')
        images = [woo_image_url({'src':n.get('data-large_image') or n.get('data-src') or n.get('src'),
                                'srcset':n.get('srcset')}) for n in soup.select('.woocommerce-product-gallery img')]
        return clean_images(images, product_url) or html_gallery(html, product_url)


class WooHTMLProvider(PublicStoreProvider):
    async def crawl(self, http):
        products, seen, visited = [], set(), set()
        url = self.config.get('catalog_url') or self.base_url + '/shop/'
        for _ in range(self.max_pages):
            if url in visited:
                raise CatalogFetchError('Woo HTML pagination loop')
            visited.add(url)
            response = await http.get(url)
            soup = BeautifulSoup(response.content, 'html.parser')
            rows = self.parse_page(soup, str(response.url))
            keys = {p.source_product_id or p.product_url for p in rows if p is not None}
            if not keys or keys <= seen:
                raise CatalogFetchError('Woo HTML empty/repeated listing')
            seen.update(keys)
            for product in rows:
                self.add(products, product)
            next_link = soup.select_one('a.next.page-numbers, a.nextpostslink')
            if next_link is None:
                # An unrecognized pagination widget is not proof of completeness.
                if soup.select('.woocommerce-pagination a, .pagination a'):
                    numbered = [a for a in soup.select('.woocommerce-pagination a, .pagination a')
                                if a.get_text(strip=True).isdigit()]
                    current = soup.select_one('.page-numbers.current, .pagination .current')
                    if numbered and (not current or max(int(a.get_text(strip=True)) for a in numbered) > int(current.get_text(strip=True))):
                        raise CatalogFetchError('Woo HTML unknown next page')
                return products
            url = urljoin(str(response.url), next_link['href'])
        raise CatalogFetchError('Woo HTML pagination limit')

    def parse_page(self, soup, url):
        products = []
        roots = soup.select('li.product, .products .product-grid-item, .products .wd-product, .shop-item')
        for card in roots:
            title = card.select_one('.woocommerce-loop-product__title, .wd-entities-title, .shop-item__title')
            if title is None:
                raise ValueError('Woo title missing')
            link = title if title.name == 'a' else title.select_one('a[href]') or title.find_parent('a',href=True)
            if link is None:
                link = card.select_one('a.woocommerce-LoopProduct-link, a.product-image-link')
            if link is None:
                raise ValueError('Woo product link missing')
            classes = ' '.join(card.get('class', []))
            key_match = re.search(r'\bpost-(\d+)\b', classes)
            button = card.select_one('[data-product_id]')
            key = key_match[1] if key_match else button.get('data-product_id') if button else None
            price = card.select_one('.price ins .amount, .price .amount, .shop-item__price')
            old = card.select_one('.price del .amount')
            # Avoid mistaking the old price for the active one.
            if price and price.find_parent('del'):
                price = next((n for n in card.select('.price .amount') if n.find_parent('del') is None), None)
            symbol = card.select_one('.woocommerce-Price-currencySymbol')
            currency = {'₽':'RUB','руб.':'RUB','руб':'RUB','Br':'BYN','€':'EUR','$':'USD'}.get(symbol.get_text(strip=True) if symbol else '') or self.config.get('currency')
            image = card.select_one('img')
            products.append(product_from_values(self.config, key=key, name=title.get_text(' ',strip=True),
                url=urljoin(url,link['href']), price=money(price.get_text()) if price else None,
                old_price=money(old.get_text()) if old else None, currency=currency,
                images=[image.get('data-src') or image.get('src')] if image else [], available='outofstock' not in classes))
        return products

    def parse_gallery(self, html, product_url):
        return html_gallery(html, product_url, '.woocommerce-product-gallery img')


class TildaSitemapProvider(PublicStoreProvider):
    async def crawl(self, http):
        # The CDN API disallows crawling. Use only the manufacturer's allowed
        # sitemap and public, server-rendered product pages with embedded JSON.
        pending = [self.base_url + '/sitemap-store.xml']
        sitemaps, urls = set(), []
        while pending:
            url = pending.pop(0)
            if url in sitemaps or len(sitemaps) >= 20:
                raise CatalogFetchError('Tilda sitemap loop/limit')
            sitemaps.add(url)
            response = await http.get(url)
            root = ET.fromstring(response.content)
            locations = [node.text for entry in root for node in entry
                         if node.tag.split('}')[-1] == 'loc' and node.text]
            if root.tag.split('}')[-1] == 'sitemapindex':
                pending.extend(locations)
            elif root.tag.split('}')[-1] == 'urlset':
                urls.extend(locations)
            else:
                raise CatalogFetchError('Tilda sitemap is not XML sitemap')
        urls = list(dict.fromkeys(u.split('#',1)[0] for u in urls))
        if not urls or len(urls) > self.max_pages:
            raise CatalogFetchError('Tilda product page limit/empty sitemap')
        products = []
        for index, url in enumerate(urls,1):
            response = await http.get(url)
            try:
                self.add(products, tilda_product(self.config, response.text, str(response.url)))
            except (ValueError, TypeError, KeyError) as error:
                raise CatalogFetchError(f'{type(error).__name__}: {url}') from error
            if index % 25 == 0:
                logger.info('Tilda source=%s page=%s/%s', self.source, index, len(urls))
        return products

    def parse_gallery(self, html, product_url):
        product = tilda_product(self.config, html, product_url)
        return product.image_urls or () if product else ()


class VigboProvider(PublicStoreProvider):
    async def crawl(self, http):
        products, seen, visited = [], set(), set()
        url = self.config['catalog_url']
        for _ in range(self.max_pages):
            if url in visited:
                raise CatalogFetchError('Vigbo pagination loop')
            visited.add(url)
            response = await http.get(url)
            soup = BeautifulSoup(response.content, 'html.parser')
            cards = soup.select('.static-grid-item[data-productid]')
            keys = {card['data-productid'] for card in cards}
            if not keys or keys <= seen:
                raise CatalogFetchError('Vigbo listing empty or repeated')
            seen.update(keys)
            for card in cards:
                self.add(products, self.parse_card(card, str(response.url)))
            more = soup.select_one('a.nav-paginator__link-next[href]')
            if more is None:
                current = soup.select_one('.nav-paginator__link-active')
                pages = [int(a.get_text(strip=True)) for a in soup.select('.nav-paginator__link') if a.get_text(strip=True).isdigit()]
                if pages and (current is None or max(pages) > int(current.get_text(strip=True))):
                    raise CatalogFetchError('Vigbo next link missing')
                return products
            url = urljoin(str(response.url), more['href'])
        raise CatalogFetchError('Vigbo pagination limit')

    def parse_card(self, card, url):
        title = card.select_one('.product-name')
        link = card.select_one('a.product[href]')
        if title is None or link is None:
            raise ValueError('Vigbo product markup missing')
        regular = card.select_one('.product-price-min')
        discount = card.select_one('.product-price-discount')
        price = discount if discount and money(discount.get_text(' ', strip=True)) is not None else regular
        old = card.select_one('.product-price-old, .old-price, del')
        raw_price = price.get_text(' ',strip=True) if price else ''
        currency = 'RUB' if re.search(r'(?:[рp]уб|₽)', raw_price, re.I) else self.config.get('currency')
        return product_from_values(self.config, key=card['data-productid'],
            name=title.get_text(' ',strip=True), url=urljoin(url,link['href']),
            price=money(raw_price), old_price=money(old.get_text()) if old else None,
            currency=currency, images=[n.get('data-src') or n.get('src') for n in card.select('.image img')],
            available='нет в наличии' not in card.get_text(' ',strip=True).casefold())
