import asyncio
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.providers.opencart import OpenCartProvider
from app.providers.public_http import CatalogFetchError

FIXTURES = Path(__file__).parent / 'fixtures' / 'opencart'
HTML = (FIXTURES / 'product.html').read_text()
XML = (FIXTURES / 'sitemap.xml').read_text()
CONFIG = dict(source='lekalo', display_name='Лекало онлайн', base_url='https://example.com',
              catalog_url='https://example.com/women', specialization='general')


class OpenCartTests(unittest.TestCase):
    def fetch(self, routes, **options):
        requests = []
        def handler(request):
            requests.append(str(request.url))
            if request.url.path == '/robots.txt':
                return httpx.Response(200, text=routes.get('/robots.txt', 'User-agent: *\nAllow: /'))
            relative = request.url.path + ('?' + request.url.query.decode() if request.url.query else '')
            body = routes.get(str(request.url), routes.get(relative, routes.get(request.url.path)))
            if isinstance(body, httpx.Response):
                return body
            return httpx.Response(200, text=body) if body is not None else httpx.Response(404)
        config = dict(CONFIG, **options.pop('config', {}))
        provider = OpenCartProvider(config, transport=httpx.MockTransport(handler), **options)
        with patch('app.providers.public_http.asyncio.sleep', new=AsyncMock()):
            result = asyncio.run(provider.fetch_products())
        return result, requests, provider

    def test_real_fields_price_old_price_and_actual_gallery(self):
        p = OpenCartProvider(CONFIG).parse_product(HTML, 'https://example.com/women/coat')
        self.assertEqual(p.source_product_id, '123')
        self.assertEqual(p.source, 'lekalo')
        self.assertEqual(p.name, 'Выкройка пальто Луна')
        self.assertEqual(p.brand, 'Лекало онлайн')
        self.assertEqual(p.product_url, 'https://example.com/women/coat')
        self.assertEqual(p.price, Decimal('750.00'))
        self.assertEqual(p.old_price, Decimal('1000.00'))
        self.assertEqual(p.currency, 'RUB')
        self.assertTrue(p.is_sale)
        self.assertFalse(p.is_new)
        self.assertFalse(p.is_free)
        self.assertTrue(p.is_available)
        self.assertEqual(p.category, 'Верхняя одежда')
        self.assertEqual(p.audience, 'women')
        self.assertEqual(p.sizes, ('42', '44'))
        self.assertEqual(p.heights, ('164',))
        self.assertEqual(p.image_url, 'https://example.com/image/coat.jpg')
        self.assertEqual(len(p.image_urls), 2)
        self.assertFalse(any('logo' in image for image in p.image_urls))

    def test_free_unavailable_and_unknown_audience(self):
        html = HTML.replace('750.00', '0').replace('InStock', 'OutOfStock').replace('Женские выкройки', 'Каталог')
        p = OpenCartProvider(CONFIG).parse_product(html, 'https://example.com/women/coat')
        self.assertTrue(p.is_free)
        self.assertFalse(p.is_available)
        self.assertIsNone(p.audience)

    def test_no_price_does_not_mean_free_and_no_false_sale(self):
        html = HTML.replace('<meta itemprop="price" content="750.00"/>', '').replace('class="price"', 'class="removed"').replace('class="price-new"', 'class="removed"')
        p = OpenCartProvider(CONFIG).parse_product(html, 'https://example.com/women/coat')
        self.assertIsNone(p.price)
        self.assertFalse(p.is_free)
        self.assertFalse(p.is_sale)
        p = OpenCartProvider(CONFIG).parse_product(HTML.replace('1 000,00', '500,00'), 'https://example.com/women/coat')
        self.assertFalse(p.is_sale)

    def test_invalid_identity_canonical_or_challenge_fails(self):
        provider = OpenCartProvider(CONFIG)
        for html in [HTML.replace('value="123"', 'value=""'), '<h1>Check your browser</h1>',
                     HTML.replace('href="https://example.com/women/coat"', 'href="http://127.0.0.1/private"'),
                     HTML.replace('href="https://example.com/women/coat"', 'href="https://example.com/index.php?product_id=55"')]:
            with self.assertRaises(CatalogFetchError):
                provider.parse_product(html, 'https://example.com/women/coat')

    def test_context_audience_only_from_explicit_section(self):
        html = HTML.replace('Женские выкройки', 'Каталог')
        config = dict(CONFIG, section_labels={'detskaya-odezhda': 'Детская одежда'})
        p = OpenCartProvider(config).parse_product(html, 'https://example.com/women/coat', ['https://example.com/detskaya-odezhda/coat'])
        self.assertEqual(p.audience, 'kids')
        self.assertIsNone(OpenCartProvider(dict(CONFIG, specialization='kids')).parse_product(html, 'https://example.com/women/coat').audience)

    def test_sitemap_complete_no_image_urls_requested_and_repeatable(self):
        routes = {'/index.php?route=extension/feed/google_sitemap': XML,
                  '/women/coat': HTML}
        result, calls, _ = self.fetch(routes)
        self.assertTrue(result.complete)
        self.assertEqual(len(result.products), 1)
        self.assertEqual(len(calls), 3)
        self.assertFalse(any('/image/' in url for url in calls))
        again, _, _ = self.fetch(routes)
        self.assertEqual(result.products, again.products)

    def test_page_limit_or_detail_error_discards_partial(self):
        for options in [dict(max_pages=1), {}]:
            result, _, _ = self.fetch({'/index.php?route=extension/feed/google_sitemap': XML}, **options)
            self.assertFalse(result.complete)
            self.assertEqual(result.products, [])
            self.assertEqual(result.errors, 1)

    def test_duplicate_sitemap_and_duplicate_product_ids(self):
        xml = XML.replace('</urlset>', '<url><loc>https://example.com/alias</loc><image:image><image:loc>https://example.com/image.jpg</image:loc></image:image></url></urlset>')
        result, _, _ = self.fetch({'/index.php?route=extension/feed/google_sitemap': xml,
                                  '/women/coat': HTML, '/alias': HTML})
        self.assertTrue(result.complete)
        self.assertEqual(len(result.products), 1)

    def test_sitemap_index_and_loop_guard(self):
        index = '<sitemapindex><sitemap><loc>https://example.com/products.xml</loc></sitemap></sitemapindex>'
        routes = {'/index.php?route=extension/feed/google_sitemap': index, '/products.xml': XML, '/women/coat': HTML}
        result, _, _ = self.fetch(routes)
        self.assertTrue(result.complete)
        routes['/products.xml'] = index
        result, _, _ = self.fetch(routes)
        self.assertFalse(result.complete)

    def test_robots_disallowed_detail_not_requested(self):
        result, calls, _ = self.fetch({'/robots.txt': 'User-agent: *\nDisallow: /women/coat',
            '/index.php?route=extension/feed/google_sitemap': XML})
        self.assertFalse(result.complete)
        self.assertFalse(any(url.endswith('/women/coat') for url in calls))

    def test_sitemap_courses_skipped_not_downloaded(self):
        xml = XML.replace('</urlset>', '<url><loc>https://example.com/course</loc><image:image><image:caption>Курс шитья</image:caption></image:image></url></urlset>')
        result, calls, _ = self.fetch({'/index.php?route=extension/feed/google_sitemap': xml, '/women/coat': HTML})
        self.assertTrue(result.complete)
        self.assertEqual(result.skipped, 1)
        self.assertFalse(any(url.endswith('/course') for url in calls))

    @staticmethod
    def listing(next_page=False, second=False):
        return '<div id="content"><div class="name-actions"><div class="name"><a href="/women/coat">Пальто Луна</a></div></div></div>' + ('<ul class="pagination"><li class="active">1</li><li><a href="/catalog?page=2">&gt;</a></li></ul>' if next_page else '')

    def test_listing_complete_and_shared_categories_no_duplicates(self):
        result, _, _ = self.fetch({'/catalog': self.listing(), '/another': self.listing(), '/women/coat': HTML},
                                  config=dict(listing_urls=['/catalog', '/another']))
        self.assertTrue(result.complete)
        self.assertEqual(len(result.products), 1)
        result, _, _ = self.fetch({'/catalog': self.listing(), '/women/coat': HTML}, config=dict(listing_urls=['/catalog']))
        self.assertTrue(result.complete)
        self.assertEqual(len(result.products), 1)

    def test_repeated_listing_page_and_missing_next_are_incomplete(self):
        for html in [self.listing(next_page=True), self.listing() + '<ul class="pagination"><li class="active">1</li><a href="/catalog?page=2">2</a></ul>']:
            result, _, _ = self.fetch({'/catalog': html, '/catalog?page=2': html, '/women/coat': HTML}, config=dict(listing_urls=['/catalog']))
            self.assertFalse(result.complete)

    def test_listing_total_protects_missing_pagination(self):
        result, _, _ = self.fetch({'/catalog': self.listing() + '<p>Показано с 1 по 1 из 15</p>', '/women/coat': HTML}, config=dict(listing_urls=['/catalog']))
        self.assertFalse(result.complete)


if __name__ == '__main__':
    unittest.main()
