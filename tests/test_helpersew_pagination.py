import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from app.providers.helpersew import HelperSewProvider


class HelperPaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_follows_pages_and_preserves_filter_context(self):
        provider = HelperSewProvider(request_delay=0)
        provider.category_pages = (("/catalog/zhenskie/", "women", None, True, False),)
        fixture = (Path(__file__).parent / "fixtures/helpersew_catalog.html").read_text(encoding="utf-8")
        first = fixture + '<a class="main-ui-pagination-next" href="?PAGEN_1=2">2</a>'
        second = fixture.replace('1034345', '9999999')
        provider._get_page = AsyncMock(side_effect=[first, second])
        result = await provider.fetch_products()
        self.assertTrue(result.complete)
        self.assertEqual(provider._get_page.await_count, 2)
        self.assertTrue(any(p.source_product_id == "9999999" and p.is_beginner for p in result.products))

    async def test_failed_later_page_never_marks_snapshot_complete(self):
        provider = HelperSewProvider(request_delay=0)
        provider.category_pages = (("/catalog/zhenskie/", "women", None),)
        provider._get_page = AsyncMock(side_effect=['<a class="main-ui-pagination-next" href="?PAGEN_1=2">2</a>', None])
        result = await provider.fetch_products()
        self.assertFalse(result.complete)
        self.assertEqual(result.errors, 1)

    async def test_repeated_page_is_incomplete(self):
        provider = HelperSewProvider(request_delay=0)
        provider.category_pages = (("/catalog/zhenskie/", "women", None),)
        provider._get_page = AsyncMock(return_value='<a class="main-ui-pagination-next" href="/catalog/zhenskie/">1</a>')
        result = await provider.fetch_products()
        self.assertFalse(result.complete)
        self.assertEqual(provider._get_page.await_count, 1)

    def test_pagination_cannot_change_host_or_category(self):
        for target in ('https://example.com/', '/catalog/muzhskie/'):
            with self.assertRaises(ValueError):
                HelperSewProvider.next_page_url(f'<a class="main-ui-pagination-next" href="{target}">Next</a>', 'https://helpersew.com/catalog/zhenskie/')
