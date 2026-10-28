import asyncio
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from bs4 import BeautifulSoup
import httpx

from app.providers.bitrix_catalog import BitrixCatalogProvider


FIXTURES = Path(__file__).parent / 'fixtures' / 'bitrix'


def config(source='patternclo', **options):
    return dict(source=source, display_name='Test manufacturer', base_url='https://example.com',
                catalog_url='https://example.com/catalog/', specialization='general', bitrix=options)


class BitrixCatalogTests(unittest.TestCase):
    def parse(self, source, path='/catalog/product/'):
        return BitrixCatalogProvider(config(source)).parse_detail(
            (FIXTURES / f'{source}.html').read_text(), 'https://example.com' + path)

    def test_patternclo_actual_product_id_not_size_offer(self):
        p = self.parse('patternclo')
        self.assertEqual(p.source_product_id, '1921')
        self.assertEqual(p.name, 'Женские пижамные штаны')
        self.assertEqual(p.price, Decimal('190.00'))
        self.assertEqual(p.audience, 'women')
        self.assertEqual(len(p.image_urls), 4)
        self.assertFalse(p.is_new)
        self.assertFalse(p.is_free)

    def test_easysew_old_current_price_and_explicit_children_section(self):
        p = self.parse('easysew', '/catalogy/3/975/')
        self.assertEqual(p.source_product_id, '975')
        self.assertEqual(p.price, Decimal('45.00'))
        self.assertEqual(p.old_price, Decimal('90.00'))
        self.assertTrue(p.is_sale)
        self.assertEqual(p.audience, 'kids')
        self.assertEqual(p.category, 'Юбки')
        self.assertTrue(p.image_url.endswith('60bc39a631b961e126d5706c45e59a9a.jpg'))

    def test_lspatterns_real_id_sizes_heights_and_main_gallery(self):
        p = self.parse('lspatterns')
        self.assertEqual(p.source_product_id, '204')
        self.assertEqual(p.price, Decimal('400.00'))
        self.assertEqual(p.audience, 'women')
        self.assertIn('38/40', p.sizes)
        self.assertIn('158-164', p.heights)
        self.assertEqual(len(p.image_urls), 8)
        self.assertFalse(p.is_new)

    def test_yasew_free_and_main_id_not_recommendation(self):
        p = self.parse('yasew')
        self.assertEqual(p.source_product_id, '3042')
        self.assertEqual(p.price, 0)
        self.assertTrue(p.is_free)
        self.assertEqual(len(p.image_urls), 3)

    def test_vikroy_single_pattern_not_subscription_price(self):
        p = self.parse('vikroy_ka')
        self.assertEqual(p.source_product_id, '2455')
        self.assertEqual(p.price, 190)
        self.assertFalse(p.is_sale)
        self.assertEqual(p.audience, 'kids')

    def test_kapsule_all_listing_cards_stable_ids_no_audience_guess(self):
        provider = BitrixCatalogProvider(config('kapsulestore'))
        soup = BeautifulSoup((FIXTURES / 'kapsulestore.html').read_text(), 'html.parser')
        rows = [provider.parse_card(c, provider.base_url) for c in provider.cards(soup)]
        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[0].source_product_id, '57')
        self.assertEqual(rows[0].price, 370)
        self.assertEqual(len(rows[0].image_urls), 2)
        self.assertIsNone(rows[0].audience)
        self.assertEqual(rows[0].product_url, 'https://example.com/catalog/plate-majka/')

    def fetch(self, routes, *, source='patternclo', robots='', **options):
        calls = []
        def handler(request):
            path = request.url.raw_path.decode()
            calls.append(path)
            if path == '/robots.txt':
                return httpx.Response(200, text=robots)
            status, body = routes.get(path, (404, 'not found'))
            return httpx.Response(status, text=body)
        provider = BitrixCatalogProvider(config(source, **options), transport=httpx.MockTransport(handler))
        with patch('app.providers.public_http.asyncio.sleep', new=AsyncMock()):
            result = asyncio.run(provider.fetch_products())
        return result, provider, calls

    def test_complete_sitemap_dedup_and_deleted_entry(self):
        detail = (FIXTURES / 'patternclo.html').read_text()
        result, provider, calls = self.fetch({
            '/catalog/': (200, '<h1>Каталог</h1>'),
            '/sitemap.xml': (200, '<sitemapindex><sitemap><loc>https://example.com/products.xml</loc></sitemap><sitemap><loc>https://example.com/products.xml</loc></sitemap></sitemapindex>'),
            '/products.xml': (200, '<urlset><url><loc>https://example.com/catalog/women/pants/</loc></url><url><loc>https://example.com/catalog/men/pants/</loc></url><url><loc>https://example.com/catalog/old/removed/</loc></url></urlset>'),
            '/catalog/women/pants/': (200, detail), '/catalog/men/pants/': (200, detail),
        })
        self.assertTrue(result.complete)
        self.assertEqual(len(result.products), 1)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(calls.count('/products.xml'), 1)

    def test_incomplete_detail_server_failure_discards_partial_snapshot(self):
        result, provider, calls = self.fetch({
            '/catalog/': (200, '<h1>Каталог</h1>'),
            '/sitemap.xml': (200, '<urlset><url><loc>https://example.com/catalog/women/pants/</loc></url><url><loc>https://example.com/catalog/women/shirt/</loc></url></urlset>'),
            '/catalog/women/pants/': (200, (FIXTURES / 'patternclo.html').read_text()),
            '/catalog/women/shirt/': (503, 'temporary error'),
        })
        self.assertFalse(result.complete)
        self.assertEqual(result.products, [])
        self.assertEqual(result.errors, 1)
        self.assertEqual(provider.retries_made, 2)

    def test_robot_blocked_pagination_is_not_requested_and_not_complete(self):
        listing = (FIXTURES / 'kapsulestore.html').read_text() + '<a href="?PAGEN_1=2">2</a>'
        result, _, calls = self.fetch({'/catalog/': (200, listing)}, source='kapsulestore',
                                      robots='User-agent: *\nDisallow: /*PAGEN')
        self.assertFalse(result.complete)
        self.assertEqual(result.products, [])
        self.assertNotIn('/catalog/?PAGEN_1=2', calls)

    def test_listing_pagination_and_repeated_category_product_dedup(self):
        listing = (FIXTURES / 'kapsulestore.html').read_text()
        result, _, calls = self.fetch({
            '/catalog/': (200, listing + '<a href="?PAGEN_1=2">2</a>'),
            '/catalog/?PAGEN_1=2': (200, listing),
        }, source='kapsulestore')
        self.assertTrue(result.complete)
        self.assertEqual(len(result.products), 9)
        self.assertEqual(calls.count('/catalog/?PAGEN_1=2'), 1)

    def test_truncated_sitemap_below_official_total_is_incomplete(self):
        result, _, _ = self.fetch({
            '/catalog/': (200, '<button data-total="2" data-page-count="1"></button>'),
            '/sitemap.xml': (200, '<urlset><url><loc>https://example.com/catalog/women/pants/</loc></url></urlset>'),
            '/catalog/women/pants/': (200, (FIXTURES / 'patternclo.html').read_text()),
        })
        self.assertFalse(result.complete)

    def test_detail_markup_change_does_not_become_free_product(self):
        with self.assertRaises(ValueError):
            BitrixCatalogProvider(config()).parse_detail('<h1>Брюки</h1>', 'https://example.com/catalog/x/y/')


if __name__ == '__main__':
    unittest.main()
