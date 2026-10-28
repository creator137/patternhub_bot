"""Public Tilda HTML/sitemap snapshots, including legacy static catalogs.

Configuration stays in the caller's registry.  Sitemap failures and unresolved
product URLs never authorize availability reconciliation, even if some useful
products were recovered.  Only same-manufacturer canonical URLs are accepted.
"""
from dataclasses import replace
import json
import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from app.providers.base import ProviderResult
from app.providers.public_http import CatalogFetchError, PublicCatalogHTTP
from app.providers.public_stores import TildaSitemapProvider
from app.providers.store_common import (
    audience_for, embedded_tilda_product, money, plain, product_from_values,
    tilda_product,
)

logger = logging.getLogger(__name__)


def _same_host(url, base):
    parsed = urlsplit(url)
    return (parsed.scheme in {'http', 'https'} and not parsed.username and not parsed.password
            and parsed.port in {None, 80, 443}
            and parsed.hostname is not None
            and parsed.hostname.removeprefix('www.') == urlsplit(base).hostname.removeprefix('www.'))


def _canonical_url(soup, url, base):
    node = soup.select_one('link[rel="canonical"][href]')
    value = urljoin(url, node['href']) if node else url
    if not _same_host(value, base):
        raise ValueError('Foreign product canonical')
    parsed = urlsplit(value)
    # www and HTTPS aliases must share the same stable URL fallback identity.
    return urlunsplit(('https', urlsplit(base).netloc, parsed.path, parsed.query, ''))


def _non_pattern(title, url):
    path = urlsplit(url).path.casefold()
    return (bool(re.search(r'^/(?:education|courses?|members|personalaccount|personal_area|proshivka)(?:/|$)', path))
            or (not re.match(r'^\s*выкройк', title, re.I) and bool(re.search(
                r'\b(?:видеоурок\w*|видеоинструкция|видеокурс\w*|мастер.класс|онлайн.курс|мини.курс\w*|'
                r'выпуск\s+\d|продление|доступ\s+к|марафон\w*|список\s+поставщиков)\b', title, re.I)))
            or bool(re.search(r'для\s+вто|колодка|вдевания\s+резинки', title, re.I)))


class ExtendedTildaProvider(TildaSitemapProvider):
    """Sitemap-store products, plus explicitly configured static pattern catalogs.

    Options: discovery='store' (default) or 'static_catalog'; catalog_url is the
    authoritative listing for the latter. Static discovery follows only public
    links whose path matches static_product_pattern; an unknown/empty listing
    is a failed crawl, never a complete empty snapshot.
    """

    async def fetch_products(self):
        self.last_skipped = 0
        self.last_errors = []
        self.pages_visited = 0
        self._products = {}
        http = PublicCatalogHTTP(self.base_url, transport=self.transport, robots_allow=self.config.get("robots_allow", ()))
        complete = False
        try:
            async with http:
                await self.crawl(http)
            complete = bool(self._products) and not self.last_errors
        except (CatalogFetchError, ValueError, TypeError, KeyError, ET.ParseError) as error:
            self.last_errors.append(str(error))
            logger.warning('Tilda snapshot source=%s incomplete: %s', self.source, error)
        self.requests_made, self.retries_made = http.requests_made, http.retries_made
        return ProviderResult(list(self._products.values()), errors=len(self.last_errors),
                              skipped=self.last_skipped, complete=complete)

    async def _sitemap_urls(self, http):
        pending = [self.base_url + '/sitemap-store.xml']
        visited, urls = set(), []
        while pending:
            url = pending.pop(0)
            # Explicitly audited category sitemap, not an omitted product page.
            if urlsplit(url).path in self.config.get('category_sitemaps', ()):
                continue
            if url in visited or len(visited) >= 20 or not _same_host(url, self.base_url):
                raise CatalogFetchError('Foreign/repeated/oversized sitemap index: ' + url)
            visited.add(url)
            response = await http.get(url)
            root = ET.fromstring(response.content)
            locations = [node.text.strip() for entry in root for node in entry
                         if node.tag.split('}')[-1] == 'loc' and node.text]
            kind = root.tag.split('}')[-1]
            if kind == 'sitemapindex':
                pending.extend(locations)
            elif kind == 'urlset':
                urls.extend(locations)
            else:
                raise CatalogFetchError('Unrecognized sitemap structure: ' + url)
        return list(dict.fromkeys(u.split('#', 1)[0] for u in urls))

    async def _static_urls(self, http):
        url = self.config['catalog_url']
        response = await http.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        pattern = re.compile(self.config.get('static_product_pattern', r'^/[^/]+_pattern$'))
        urls = []
        for node in soup.select('a[href]'):
            href = urljoin(str(response.url), node['href']).split('#', 1)[0]
            if _same_host(href, self.base_url) and pattern.fullmatch(urlsplit(href).path):
                urls.append(href)
        # A next page/load-more widget means the first page is not a snapshot.
        if soup.select_one('a[rel="next"], .t-store__load-more-btn, .js-store-load-more-btn'):
            raise CatalogFetchError('Static catalog has unresolved pagination')
        return list(dict.fromkeys(urls))

    async def crawl(self, http):
        discovery = self.config.get('discovery', 'store')
        if discovery not in {'store', 'static_catalog'}:
            raise ValueError('Unknown Tilda discovery strategy')
        urls = await (self._static_urls(http) if discovery == 'static_catalog' else self._sitemap_urls(http))
        if not urls or len(urls) > self.max_pages:
            raise CatalogFetchError('Empty catalog or product page limit')
        for url in urls:
            if _non_pattern('', url):
                self.last_skipped += 1
                continue
            try:
                if not _same_host(url, self.base_url):
                    raise CatalogFetchError('Foreign product sitemap URL: ' + url)
                response = await http.get(url)
                self.pages_visited += 1
                product = self.parse_product(response.text, str(response.url))
                if product is None:
                    self.last_skipped += 1
                    continue
                key = product.source_product_id or product.product_url
                if key not in self._products:
                    self._products[key] = product
            except (CatalogFetchError, ValueError, TypeError, KeyError) as error:
                self.last_errors.append(f'{url}: {type(error).__name__}: {error}')
                logger.warning('Tilda product source=%s url=%s error=%s', self.source, url, error)
        return list(self._products.values())

    def parse_product(self, text, url):
        soup = BeautifulSoup(text, 'html.parser')
        data = embedded_tilda_product(text)
        title = plain(data.get('title')) if data else plain(soup.title.get_text() if soup.title else '')
        if _non_pattern(title, url):
            return None
        canonical = _canonical_url(soup, url, self.base_url)
        if data is not None:
            product = tilda_product(self.config, text, canonical)
        else:
            # T744 predates the store API; it exposes its own price/options/gallery.
            root = soup.select_one('.js-product-single')
            if root is not None and root.select_one('.js-product-name'):
                title_node = root.select_one('.js-product-name')
                current = root.select_one('.js-product-price')
                old = root.select_one('[field="price_old"], .js-store-prod-price-old-val')
                images = [n.get('data-original') or n.get('src') for n in root.select('.t-slds__bgimg, .t-slds__img')]
                symbol = root.select_one('.js-product-price-currency')
                currency = {'р.':'RUB', '₽':'RUB', 'руб.':'RUB'}.get(plain(symbol).casefold()) if symbol else None
                product = product_from_values(self.config, name=plain(title_node), url=canonical,
                    key=root.get('data-product-gen-uid') or root.get('data-product-uid') or canonical,
                    price=money(current.get_text()) if current else None,
                    old_price=money(old.get_text()) if old else None, currency=currency,
                    images=images, description=root.select_one('[field="descr"]'))
            else:
                product = tilda_product(self.config, text, canonical)
        if product is None:
            return None
        sizes, heights, facts = list(product.sizes or ()), list(product.heights or ()), []
        difficulty = None
        rows = []
        if data:
            rows.extend(data.get('characteristics') or [])
            rows.extend(data.get('properties') or [])
            for edition in data.get('editions') or []:
                for key, value in edition.items():
                    if 'размер' in key.casefold() or 'рост' in key.casefold():
                        rows.append({'title': key, 'value': value})
        for option in soup.select('.js-product-option'):
            label = option.select_one('.js-product-option-name')
            if label:
                rows.append({'title': plain(label), 'values': [plain(n) for n in option.select('option')]})
        for row in rows:
            label = plain(row.get('title')).casefold()
            values = row.get('values') or row.get('value') or []
            values = values if isinstance(values, list) else [values]
            values = [plain(v) for v in values if isinstance(v, (str, int, float))]
            if 'размер' in label:
                sizes.extend(values)
            elif 'рост' in label:
                heights.extend(values)
            elif 'сложност' in label:
                difficulty = ' / '.join(values) or None
            if any(word in label for word in ['аудитория', 'пол', 'тип выкройки']):
                facts.extend(values)
        audience = audience_for([product.name, *facts], self.config.get('specialization', 'general'))
        return replace(product, source_product_id=product.source_product_id or canonical,
                       product_url=canonical, audience=audience or product.audience,
                       sizes=tuple(dict.fromkeys(sizes)) or None,
                       heights=tuple(dict.fromkeys(heights)) or None,
                       difficulty=difficulty or product.difficulty).normalized()

    def parse_gallery(self, html, product_url):
        product = self.parse_product(html, product_url)
        return (product.image_urls or ()) if product else ()
