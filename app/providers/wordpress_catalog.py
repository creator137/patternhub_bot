"""Public WordPress catalogs discovered through complete XML sitemaps.

Never downloads pattern files, calls authenticated REST endpoints or treats a
failed detail page as a successful snapshot. Configuration contains only public
manufacturer URLs and selectors; products remain the shared ParsedProduct DTO.
"""
from __future__ import annotations

import asyncio
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import replace
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from app.providers.public_http import CatalogFetchError, CatalogHTTPError
from app.providers.public_stores import PublicStoreProvider, WooStoreProvider
from app.providers.store_common import money, plain, product_from_values, is_pattern, woo_image_url


def _json_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_nodes(child)


def _image(node):
    return woo_image_url({'src':node.get('data-large_image') or node.get('data-src') or node.get('data-lazy-src') or node.get('src'),
                          'srcset':node.get('srcset')})


def _amount(node):
    if node is None:
        return None
    amount = node.select_one('.woocommerce-Price-amount, .amount') or node
    return money(amount.get('content') or amount.get_text(' ', strip=True))


class WordPressSitemapProvider(PublicStoreProvider):
    """WooCommerce details or explicitly identified pattern blog posts.

    Options: sitemap_url, sitemap_pattern (index-child URL regex), product_path
    (URL path regex), blog, detail_concurrency (1..3), require_pattern_evidence.
    Sitemap limits are independent from the number of returned products.
    """

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)
        self.last_error = None
        self.listed_urls = 0

    async def crawl(self, http):
        pending = [self.config.get('sitemap_url') or self.base_url + '/sitemap_index.xml']
        visited, urls = set(), []
        pattern = self.config.get('sitemap_pattern', r'(?:product-sitemap\d*|sitemap-pt-product-[\d-]+|wp-sitemap-posts-product-\d+)\.xml$')
        while pending:
            url = pending.pop(0)
            if url in visited:
                raise CatalogFetchError('WordPress sitemap repeated')
            if len(visited) >= 200:
                raise CatalogFetchError('WordPress sitemap limit')
            visited.add(url)
            response = await http.get(url)
            try:
                root = ET.fromstring(response.content)
            except ET.ParseError as error:
                raise CatalogFetchError(f'Invalid XML sitemap: {url}') from error
            locations = [n.text.strip() for entry in root for n in entry
                         if n.tag.split('}')[-1] == 'loc' and n.text]
            kind = root.tag.split('}')[-1]
            if kind == 'sitemapindex':
                pending.extend(u for u in locations if re.search(pattern, u))
            elif kind == 'urlset':
                urls.extend(locations)
            else:
                raise CatalogFetchError('Unrecognized WordPress sitemap root')
        path_pattern = self.config.get('product_path', r'^/(?:product|pattern|shop)/.+')
        urls = list(dict.fromkeys(u.split('#', 1)[0] for u in urls
                                 if re.search(path_pattern, unquote(urlsplit(u).path), re.I)))
        self.listed_urls = len(urls)
        if not urls or len(urls) > self.max_pages:
            raise CatalogFetchError(f'WordPress sitemap empty/limit: {len(urls)}')
        semaphore = asyncio.Semaphore(max(1, min(3, self.config.get('detail_concurrency', 2))))

        async def detail(url):
            async with semaphore:
                try:
                    if re.search(r'/(?:testov\w*-tovar|test-product|pechat-vykro)', urlsplit(url).path, re.I):
                        return None
                    response = await http.get(url)
                    return self.parse_detail(response.text, str(response.url))
                except CatalogHTTPError as error:
                    if error.status_code in {404,410}:
                        return None
                    self.last_error = f'{type(error).__name__}: {url}: {error}'
                    raise
                except (CatalogFetchError, ValueError, TypeError, KeyError) as error:
                    self.last_error = f'{type(error).__name__}: {url}: {error}'
                    raise CatalogFetchError(self.last_error) from error

        # Bounded batches do not leave thousands of tasks active on a large blog.
        products = []
        for start in range(0, len(urls), 30):
            rows = await asyncio.gather(*(detail(url) for url in urls[start:start + 30]), return_exceptions=True)
            failures = [row for row in rows if isinstance(row, BaseException)]
            if failures:
                raise failures[0]
            for product in rows:
                self.add(products, product)
        return products

    def parse_detail(self, html, url):
        soup = BeautifulSoup(html, 'html.parser')
        if self.config.get('blog'):
            return self.parse_post(soup, url)
        body = soup.body
        if body and 'single-product' not in body.get('class', []):
            if any(c in body.get('class', []) for c in ['archive', 'home', 'error404']):
                raise CatalogFetchError('Product URL redirected to archive/error page')
        title = soup.select_one('.summary .product_title, .product_title')
        builder = False
        if title is None and body and 'single-product' in body.get('class', []):
            form = soup.select_one('form[data-product_id]')
            own_id = form.get('data-product_id') if form else None
            if not own_id:
                identity = re.search(r'\bpostid-(\d+)\b', ' '.join(body.get('class', [])))
                own_id = identity[1] if identity else None
            own_root = soup.select_one('.post-entry-' + own_id) if own_id and own_id.isdigit() else None
            meta = soup.select_one('meta[property="og:title"][content]')
            if own_root and meta:
                title = soup.new_tag('h1')
                title.string = meta['content'].split(' - Курсы')[0]
                root = own_root
                builder = True
        if title is None:
            raise ValueError('Own product title missing')
        if not builder:
            root = title.find_parent(class_='product')
        if root is None:
            root = soup.select_one('div[id^="product-"]')
        if root is None:
            raise ValueError('Own product container missing')
        if builder:
            # Builder pages place recommendations inside the same content root.
            for recommendation in root.select('.related, .upsells, .avia-content-slider'):
                recommendation.decompose()
        name = plain(title.get_text(' ', strip=True))
        if re.match(r'(?:тариф|колодк|видеокурс|курс\b|абонемент|учебн\w*\s+пособ)', name, re.I):
            return None
        categories = [n.get_text(' ', strip=True) for n in root.select('.product_meta .posted_in a, .product_meta .tagged_as a')]
        own_breadcrumb = soup.select_one('.woocommerce-breadcrumb, .breadcrumbs')
        if own_breadcrumb:
            categories += [n.get_text(' ', strip=True) for n in own_breadcrumb.select('a')][1:]
        description_nodes = root.select('.woocommerce-product-details__short-description, #tab-description')
        if builder:
            description_nodes = root.select('.avia_textblock')
        description = ' '.join(n.get_text(' ', strip=True) for n in description_nodes)
        if not is_pattern(name, categories):
            return None
        evidence = ' '.join([name, description, *categories])
        if self.config.get('require_pattern_evidence', True) and not re.search(r'выкро[йе]|лекал|\bpattern\b', evidence, re.I):
            # A product sitemap may also contain real clothes or haberdashery.
            return None
        key_node = root.get('id', '')
        key = re.search(r'product-(\d+)', key_node)
        if key is None and body:
            key = re.search(r'\bpostid-(\d+)\b', ' '.join(body.get('class', [])))
        canonical = soup.select_one('link[rel="canonical"][href]')
        canonical_url = urljoin(url, canonical['href']) if canonical else url
        if urlsplit(canonical_url).hostname.removeprefix('www.') != urlsplit(self.base_url).hostname.removeprefix('www.'):
            raise ValueError('Foreign canonical product URL')
        summary = root.select_one('.summary') or root
        current = summary.select_one('.price ins')
        old = summary.select_one('.price del')
        if current is None:
            current = next((n for n in summary.select('.price .amount') if n.find_parent('del') is None), None)
        price, old_price = _amount(current), _amount(old)
        form = root.select_one('form[data-product_variations]')
        if form:
            try:
                variants = json.loads(form['data-product_variations'])
            except (ValueError, TypeError):
                variants = None
            if isinstance(variants, list) and variants:
                priced = [v for v in variants if money(v.get('display_price')) is not None]
                if priced:
                    lowest = min(priced, key=lambda v: money(v['display_price']))
                    price, old_price = money(lowest['display_price']), money(lowest.get('display_regular_price'))
        symbol = summary.select_one('.woocommerce-Price-currencySymbol')
        currency = {'₽': 'RUB', 'руб.': 'RUB', 'руб': 'RUB', 'Br': 'BYN', 'BYN': 'BYN', '€': 'EUR'}.get(symbol.get_text(strip=True) if symbol else '')
        images = [_image(n) for n in root.select('.woocommerce-product-gallery img, .woocommerce-product-gallery__image img, .images .wp-post-image')]
        if builder:
            images = [n.get('href') for n in root.select('.avia-gallery a[href]')]
        if not any(images):
            own_image = soup.select_one('meta[property="og:image"][content]')
            images = [own_image['content']] if own_image else []
        sizes, heights = [], []
        for row in root.select('.variations tr, .woocommerce-product-attributes tr'):
            label = row.select_one('label, th')
            if not label:
                continue
            values = [n.get_text(' ', strip=True) for n in row.select('option[value]:not([value=""])')]
            if not values:
                cell = row.select_one('td')
                values = [cell.get_text(' ', strip=True)] if cell else []
            if 'размер' in label.get_text().casefold():
                sizes += values
            if 'рост' in label.get_text().casefold():
                heights += values
        available = not ('outofstock' in root.get('class', []) or summary.select_one('.stock.out-of-stock'))
        product = product_from_values(self.config, key=key[1] if key else canonical_url,
            name=name, url=canonical_url, categories=categories, price=price,
            old_price=old_price if old_price is not None and price is not None and old_price > price else None,
            currency=currency or self.config.get('currency'), images=images,
            sizes=sizes, heights=heights, description=description, available=available)
        if product:
            return replace(product, source_published_at=self.parse_publication_date(html, canonical_url)).normalized()
        return None

    def parse_post(self, soup, url):
        """Only the manufacturer's public article, never PDFs or paid files."""
        heading = soup.select_one('article .entry-title, article h1, .content-area h1')
        if heading is None:
            raise ValueError('Pattern post title missing')
        name = heading.get_text(' ', strip=True)
        if not re.search(r'выкро[йе]|лекал|\bpattern\b', name, re.I) or not is_pattern(name):
            return None
        article = heading.find_parent('article') or heading.parent
        content = article.select_one('.entry-content') or article
        categories = [n.get_text(' ', strip=True) for n in soup.select('.breadcrumbs a, .breadcrumb a, .cat-links a')]
        body_text = content.get_text(' ', strip=True)
        if re.search(r'журнал|книг[аиуы]|подборк\w*\s+(?:выкро|модел)', name, re.I):
            return None
        # No sidebar, recommendations, ads, or technical/PDF attachment icons.
        images = [_image(n) for n in article.select('.post-thumbnail img, .entry-content img')]
        if not images:
            thumbnail = article.select_one('img.wp-post-image')
            images = [_image(thumbnail)] if thumbnail else []
        if not any(images):
            cover = soup.select_one('meta[property="og:image"][content]')
            images = [cover['content']] if cover else []
        images = [image for image in images if image and not re.search(r'/wp-includes/|/themes/|\.svg|^data:|/vk-files/|/patterns/', image)]
        canonical = soup.select_one('link[rel="canonical"][href]')
        product_url = urljoin(url, canonical['href']) if canonical else url
        key = re.search(r'\bpost-(\d+)\b', article.get('id', '') + ' ' + ' '.join(article.get('class', [])))
        if not key and soup.body:
            key = re.search(r'\bpostid-(\d+)\b', ' '.join(soup.body.get('class', [])))
        free = bool(re.search(r'\bбесплатно\b', body_text, re.I))
        product = product_from_values(self.config, key=key[1] if key else product_url,
            name=name, url=product_url, categories=categories, price=money('0') if free else None,
            currency='RUB' if free else None, images=images, description=body_text[:6000])
        if product:
            return replace(product, source_published_at=self.parse_publication_date(str(soup), product_url)).normalized()
        return None

    def parse_gallery(self, html, product_url):
        product = self.parse_detail(html, product_url)
        return product.image_urls or () if product else ()


class WordPressStoreProvider(WooStoreProvider):
    """Named public Store API adapter for WordPress sources with allowed API."""
