from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.database import Database
from app.models.categories import category_code, normalize_category
from app.models.product import ParsedProduct, ProductFilter
from app.providers.grasser import GrasserProvider
from app.repositories.products import ProductRepository
from app.services.catalog import CatalogService


FIXTURES = Path(__file__).parent / "fixtures"


class GrasserProviderTests(unittest.TestCase):
    def test_badge_icon_is_not_selected_as_product_photo(self):
        from bs4 import BeautifulSoup
        card = BeautifulSoup('''<div class="catalog-block__image">
            <img src="/local/templates/grasser/images/icon-discount.svg">
            <a class="b-mini-slide"><picture><source srcset="/upload/real.webp"><img src="/upload/real.jpg"></picture></a>
            </div>''', 'html.parser')
        self.assertEqual(GrasserProvider._extract_image_url(card,'https://grasser.ru/'), 'https://grasser.ru/upload/real.webp')
        icon = BeautifulSoup('<div class="catalog-block__image"><img src="/local/templates/grasser/images/icon-popular.svg"></div>', 'html.parser')
        self.assertIsNone(GrasserProvider._extract_image_url(icon,'https://grasser.ru/'))

    def setUp(self) -> None:
        self.provider = GrasserProvider()

    def test_parses_catalog_html_into_shared_products(self) -> None:
        html = (FIXTURES / "grasser_catalog.html").read_text(encoding="utf-8")

        products = self.provider.parse_catalog_page(html, self.provider.catalog_url)

        self.assertEqual(len(products), 2)
        self.assertEqual(self.provider.last_skipped, 1)
        sale, regular = products
        self.assertEqual(sale.source, "grasser")
        self.assertEqual(sale.source_product_id, "153947")
        self.assertEqual(sale.name, "Свитер, выкройка №1380")
        self.assertEqual(sale.brand, "Grasser")
        self.assertIsNone(sale.audience)
        self.assertEqual(sale.category, "Худи, футболки и лонгсливы")
        self.assertEqual(sale.subcategory, "Свитер")
        self.assertEqual(sale.price, Decimal("196.00"))
        self.assertEqual(sale.old_price, Decimal("280.00"))
        self.assertTrue(sale.is_sale)
        self.assertEqual(sale.currency, "RUB")
        self.assertEqual(
            sale.product_url,
            "https://grasser.ru/vykrojki/vse-vykrojki/sviter-vykroyka-1380/",
        )
        self.assertEqual(sale.image_url, "https://grasser.ru/upload/webp_cache/719b77.webp")
        self.assertEqual(regular.category, "Жакеты и жилеты")
        self.assertFalse(regular.is_sale)

    def test_finds_next_page(self) -> None:
        html = (FIXTURES / "grasser_catalog.html").read_text(encoding="utf-8")

        self.assertEqual(self.provider.next_page_number(html), 2)

    def test_parses_quick_filter_listing_flags(self) -> None:
        html = (FIXTURES / "grasser_catalog.html").read_text(encoding="utf-8")

        beginner = self.provider.parse_catalog_page(
            html,
            self.provider.catalog_url,
            page_is_beginner=True,
        )
        knit = self.provider.parse_catalog_page(
            html,
            self.provider.catalog_url,
            page_is_knit=True,
        )

        self.assertTrue(all(product.is_beginner for product in beginner))
        self.assertTrue(all(product.is_knit for product in knit))

    def test_duplicate_quick_filter_flags_are_merged(self) -> None:
        plain = ParsedProduct(
            source="grasser",
            source_product_id="153947",
            name="Свитер, выкройка №1380",
            brand="Grasser",
            audience="women",
            category="Худи, футболки и лонгсливы",
            product_url="https://grasser.ru/vykrojki/vse-vykrojki/sviter-vykroyka-1380/",
        ).normalized()
        flagged = ParsedProduct(
            source="grasser",
            source_product_id="153947",
            name="Свитер, выкройка №1380",
            brand="Grasser",
            audience="women",
            category="Свитер",
            product_url="https://grasser.ru/vykrojki/vse-vykrojki/sviter-vykroyka-1380/",
            is_beginner=True,
            is_knit=True,
        ).normalized()

        merged = self.provider._merge_product(plain, flagged)

        self.assertEqual(merged.category, "Худи, футболки и лонгсливы")
        self.assertTrue(merged.is_beginner)
        self.assertTrue(merged.is_knit)

    def test_parses_optional_detail_fields(self) -> None:
        html = (FIXTURES / "grasser_product.html").read_text(encoding="utf-8")

        product = self.provider.parse_product_page(
            html,
            "https://grasser.ru/vykrojki/vse-vykrojki/sviter-vykroyka-1380/",
        )

        self.assertEqual(product.source_product_id, "153947")
        self.assertEqual(product.price, Decimal("196.00"))
        self.assertEqual(product.old_price, Decimal("280.00"))
        self.assertEqual(product.sizes, ("38", "40"))
        self.assertEqual(product.heights, ("152-158", "158-164"))
        self.assertEqual(product.difficulty, "Сложность: 1 из 5")
        self.assertEqual(
            product.description,
            "Свободный свитер со спущенным плечом и высоким воротником.",
        )

    def test_price_parser(self) -> None:
        self.assertEqual(self.provider._decimal("1 200 Р"), Decimal("1200"))
        self.assertEqual(self.provider._decimal("196,50 Р"), Decimal("196.50"))

    def test_grasser_men_and_kids_keep_product_category(self) -> None:
        men = ParsedProduct(
            source="grasser",
            name="Мужская рубашка, выкройка №1",
            brand="Grasser",
            audience=self.provider._audience_from_url(
                "https://grasser.ru/vykrojki/muzhskie-vykrojki/rubashka/"
            ),
            category=self.provider._category_from_name("Мужская рубашка, выкройка №1"),
            product_url="https://grasser.ru/vykrojki/muzhskie-vykrojki/rubashka/",
        ).normalized()
        kids = ParsedProduct(
            source="grasser",
            name="Брюки для девочки, выкройка №2",
            brand="Grasser",
            audience=self.provider._audience_from_url(
                "https://grasser.ru/vykrojki/detskie-vykrojki/bryuki/"
            ),
            category=self.provider._category_from_name("Брюки для девочки, выкройка №2"),
            product_url="https://grasser.ru/vykrojki/detskie-vykrojki/bryuki/",
        ).normalized()

        self.assertEqual((men.audience, men.category), ("men", "Рубашки, блузки и топы"))
        self.assertEqual((kids.audience, kids.category), ("kids", "Брюки и шорты"))


class CategoryNormalizationTests(unittest.TestCase):
    def test_normalizes_shared_categories(self) -> None:
        self.assertEqual(normalize_category("Платья и сарафаны"), "Платья")
        self.assertEqual(normalize_category("Выкройки верхней одежды"), "Верхняя одежда")
        self.assertEqual(normalize_category("Жакет"), "Жакеты и жилеты")
        self.assertEqual(normalize_category("Блузки и рубашки"), "Рубашки, блузки и топы")
        self.assertEqual(normalize_category("Мужская ветровка-бомбер"), "Верхняя одежда")
        self.assertEqual(normalize_category("Детские лосины"), "Брюки и шорты")
        self.assertEqual(normalize_category("Сорочка для мальчика"), "Рубашки, блузки и топы")
        self.assertEqual(normalize_category("Балаклава"), "Аксессуары")
        self.assertEqual(category_code("Платья и сарафаны"), "dresses")
        self.assertEqual(normalize_category("Мужские"), "Другое")
        self.assertEqual(normalize_category("Детские"), "Другое")


class GrasserRepositoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp_directory.name) / "catalog.sqlite3")
        database.initialize()
        self.repository = ProductRepository(database)
        self.service = CatalogService(self.repository)
        self.grasser_product = ParsedProduct(
            source="grasser",
            source_product_id="153947",
            name="Платье Тест",
            brand="Grasser",
            category="Платья и сарафаны",
            price=Decimal("320"),
            currency="RUB",
            product_url="https://grasser.ru/vykrojki/vse-vykrojki/plate-test/",
        )
        self.vikisews_product = ParsedProduct(
            source="vikisews",
            source_product_id="153947",
            name="Платье Тест",
            brand="VikiSews",
            category="Платья",
            price=Decimal("440"),
            currency="RUB",
            product_url="https://vikisews.com/vykrojki/platja-i-sarafany/plate-test/",
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    async def test_upserts_grasser_without_duplicates(self) -> None:
        self.assertEqual(self.repository.upsert_many([self.grasser_product]), (1, 0))
        self.assertEqual(self.repository.upsert_many([self.grasser_product]), (0, 1))
        self.assertEqual(
            self.repository.count_products(ProductFilter(source="grasser")),
            1,
        )

    async def test_same_names_from_different_sources_do_not_conflict(self) -> None:
        self.repository.upsert_many([self.grasser_product, self.vikisews_product])

        self.assertEqual(self.repository.count_products(), 2)

    async def test_catalog_service_returns_both_sources_in_one_category(self) -> None:
        self.repository.upsert_many([self.grasser_product, self.vikisews_product])

        products = await self.service.get_products(
            filters=ProductFilter(category="Платья")
        )

        self.assertEqual({product.source for product in products}, {"grasser", "vikisews"})


if __name__ == "__main__":
    unittest.main()

class GrasserAudienceRegressionTests(unittest.IsolatedAsyncioTestCase):
    def card(self, name='Брюки', key='123', url='/vykrojki/vse-vykrojki/bryuki/'):
        return f'''<div class="catalog vykrojki"><div class="catalog-block">
            <a class="catalog-block__title" href="{url}">{name}</a>
            <button data-id="{key}"></button></div></div>'''

    def test_generic_product_url_never_implies_women(self):
        provider=GrasserProvider()
        for name in ['Мужские брюки', 'Брюки', 'Детская куртка']:
            p=provider.parse_catalog_page(self.card(name),provider.catalog_url)[0]
            self.assertIsNone(p.audience)
        self.assertIsNone(provider._audience_from_url('https://grasser.ru/vykrojki/verkhnyaya-odezhda/kurtka/'))

    def test_audience_comes_from_listing_even_with_generic_product_url(self):
        provider=GrasserProvider()
        for section,audience in [('vykroyki-dlya-zhenshchin','women'),('muzhskie-vykrojki','men'),('detskie-vykrojki','kids')]:
            p=provider.parse_catalog_page(self.card(),provider.catalog_url+section+'/')[0]
            self.assertEqual(p.audience,audience)
            self.assertEqual(p.category,'Брюки и шорты')

    def test_detail_canonical_overrides_old_wrong_seed(self):
        provider=GrasserProvider()
        seed=ParsedProduct(source='grasser',name='Брюки',audience='women',product_url='https://grasser.ru/vykrojki/vse-vykrojki/bryuki/')
        p=provider.parse_product_page('<link rel="canonical" href="https://grasser.ru/vykrojki/muzhskie-vykrojki/bryuki/">',seed.product_url,seed)
        self.assertEqual(p.audience,'men')

    async def test_section_membership_survives_duplicate_merge_and_repeat_upsert(self):
        from unittest.mock import AsyncMock
        from app.web.catalog import WebCatalogRepository
        provider=GrasserProvider()
        provider.quick_filter_pages=()
        all_cards=self.card('Мужские брюки','123')+self.card('Платье','456', '/vykrojki/vse-vykrojki/plate/')+self.card('Брюки','789','/vykrojki/vse-vykrojki/kids/')
        def response(client,url):
            if '/muzhskie-vykrojki/' in url:return self.card('Мужские брюки','123')
            if '/detskie-vykrojki/' in url:return self.card('Брюки','789','/vykrojki/vse-vykrojki/kids/')
            if '/vykroyki-dlya-zhenshchin/' in url:return self.card('Платье','456','/vykrojki/vse-vykrojki/plate/')
            return all_cards
        provider._get_page=AsyncMock(side_effect=response)
        result=await provider.fetch_products()
        self.assertTrue(result.complete);self.assertEqual(len(result.products),3)
        self.assertEqual({p.source_product_id:p.audience for p in result.products},{'123':'men','456':'women','789':'kids'})
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(Path(tmp)/'catalog.sqlite3');db.initialize();repo=ProductRepository(db)
            old=[ParsedProduct(source='grasser',source_product_id=p.source_product_id,name=p.name,audience='women',product_url=p.product_url) for p in result.products]
            repo.upsert_many(old)
            self.assertEqual(repo.upsert_many(result.products),(0,3))
            self.assertEqual(repo.upsert_many(result.products),(0,3))
            for audience in ('women','men','kids'):
                page=WebCatalogRepository(db).page({'source':'grasser','audience':audience})
                self.assertEqual(page['total'],1)
                self.assertEqual(page['items'][0]['audience'],audience)

    async def test_failed_or_empty_audience_section_is_incomplete(self):
        from unittest.mock import AsyncMock
        for empty in (None,'<html></html>'):
            provider=GrasserProvider();provider.quick_filter_pages=()
            def response(client,url):
                return empty if '/muzhskie-vykrojki/' in url else self.card()
            provider._get_page=AsyncMock(side_effect=response)
            self.assertFalse((await provider.fetch_products()).complete)

    def test_conflicting_audience_evidence_is_conservative(self):
        provider=GrasserProvider()
        self.assertEqual(provider._resolve_audience({'women','men'}),'unisex')
        self.assertIsNone(provider._resolve_audience({'kids','men'}))
        self.assertIsNone(provider._resolve_audience(set()))

    def test_real_generic_urls_use_audience_context_and_ads_are_not_errors(self):
        html=(FIXTURES/'grasser_audiences.html').read_text()
        provider=GrasserProvider()
        products=provider.parse_catalog_page(html,provider.catalog_url)
        self.assertEqual(len(products),3)
        self.assertEqual(provider.last_card_errors,0)
        self.assertTrue(all(p.audience is None for p in products))
        men=provider.parse_catalog_page(html,provider.catalog_url+'muzhskie-vykrojki/')
        self.assertEqual(men[1].name,'Мужские брюки, выкройка №1326')
        self.assertEqual((men[1].audience,men[1].category),('men','Брюки и шорты'))
