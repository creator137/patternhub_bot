import asyncio
import json
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
from bs4 import BeautifulSoup

from app.providers.public_http import PublicCatalogHTTP, RobotsRules, CatalogFetchError
from app.providers.public_stores import WooStoreProvider, WooHTMLProvider, TildaSitemapProvider, VigboProvider
from app.providers.store_common import money, category_for, audience_for, embedded_tilda_product, tilda_product, is_pattern


CONFIG = {'source':'grasser','display_name':'Test supplier','base_url':'https://example.com',
          'catalog_url':'https://example.com/shop/','specialization':'general'}


def woo_row(key=1, **changes):
    return {'id':key,'name':'Выкройка платья','permalink':f'https://example.com/product/{key}/',
            'type':'simple','parent':0,'prices':{'price':'25000','regular_price':'35000','currency_code':'RUB','currency_minor_unit':2},
            'images':[{'src':'https://example.com/cover.jpg'}],'categories':[{'name':'Женские платья'}],
            'is_in_stock':True, **changes}


class PublicStoreTests(unittest.TestCase):
    def test_robots_wildcards_longest_allow_and_specific_agents(self):
        rules = RobotsRules('User-agent: *\nDisallow: /private\nAllow: /private/public\nDisallow: /*?secret=\n')
        self.assertFalse(rules.allows('https://example.com/private/a'))
        self.assertTrue(rules.allows('https://example.com/private/public/a'))
        self.assertFalse(rules.allows('https://example.com/a?secret=1'))
        self.assertTrue(rules.allows('https://example.com/a?page=2'))
        self.assertFalse(RobotsRules('Disallow: /\nHost: https://store.tildacdn.com').allows('https://store.tildacdn.com/api/'))
        self.assertTrue(RobotsRules('User-agent: *\nDisallow: /\nUser-agent: PatternHubBot\nAllow: /').allows('https://example.com/'))

    def test_only_network_and_transient_server_errors_retry(self):
        calls=[]
        def handler(request):
            calls.append(request.url.path)
            if request.url.path=='/robots.txt':return httpx.Response(200,text='User-agent: *\nAllow: /')
            return httpx.Response(503 if calls.count('/catalog')<3 else 200,text='ready')
        async def run():
            async with PublicCatalogHTTP(CONFIG['base_url'],transport=httpx.MockTransport(handler)) as http:
                response=await http.get('https://example.com/catalog')
                self.assertEqual(response.text,'ready'); self.assertEqual(http.retries_made,2)
        with patch('app.providers.public_http.asyncio.sleep',new=AsyncMock()):asyncio.run(run())

    def test_public_client_does_not_follow_foreign_or_disallowed_urls(self):
        calls=[]
        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(200,text='User-agent: *\nDisallow: /private') if request.url.path=='/robots.txt' else httpx.Response(302,headers={'Location':'http://127.0.0.1/private'})
        async def run():
            async with PublicCatalogHTTP(CONFIG['base_url'],transport=httpx.MockTransport(handler)) as http:
                with self.assertRaises(CatalogFetchError):await http.get('https://example.com/private')
                with self.assertRaises(CatalogFetchError):await http.get('https://example.com/redirect')
        asyncio.run(run())
        self.assertEqual(len(calls),2)

    def test_woo_prices_flags_categories_and_gallery(self):
        product=WooStoreProvider(CONFIG).parse_product(woo_row())
        self.assertEqual(product.source,'grasser');self.assertEqual(product.source_product_id,'1')
        self.assertEqual(product.price,Decimal('250.00'));self.assertEqual(product.old_price,Decimal('350.00'))
        self.assertTrue(product.is_sale);self.assertFalse(product.is_free);self.assertFalse(product.is_new)
        self.assertEqual(product.category,'Платья');self.assertEqual(product.audience,'women')
        self.assertEqual(product.image_url,'https://example.com/cover.jpg')
        self.assertEqual(product.image_urls,('https://example.com/cover.jpg',))

    def test_no_price_no_image_and_free_are_distinct(self):
        provider=WooStoreProvider(CONFIG)
        unknown=provider.parse_product(woo_row(prices={},images=[]))
        self.assertIsNone(unknown.price);self.assertIsNone(unknown.image_url);self.assertFalse(unknown.is_free)
        free=provider.parse_product(woo_row(prices={'price':'0','regular_price':'0','currency_minor_unit':0,'currency_code':'RUB'}))
        self.assertTrue(free.is_free);self.assertFalse(free.is_sale)
        self.assertIsNone(money(''));self.assertIsNone(money('-1'));self.assertEqual(money('1 234,50 ₽'),Decimal('1234.50'))

    def test_courses_and_gift_certificates_are_not_patterns(self):
        provider=WooStoreProvider(CONFIG)
        for name in ['Подарочный сертификат','Журнал о шитье','Запись ВЕБИНАРА «Монетизация»','Видеокурс шитья']:
            self.assertIsNone(provider.parse_product(woo_row(name=name)))
        self.assertIsNotNone(provider.parse_product(woo_row(name='Выкройка брюк + видеоинструкция')))
        self.assertIsNotNone(provider.parse_product(woo_row(name='Платье Кукла')))
        self.assertIsNone(provider.parse_product(woo_row(type='variation',parent=99)))

    def test_woo_complete_pagination_and_duplicate_guard(self):
        def handler(request):
            if request.url.path=='/robots.txt':return httpx.Response(200,text='User-agent: *\nAllow: /')
            page=int(request.url.params.get('page','1'))
            return httpx.Response(200,json=[woo_row(page)],headers={'X-WP-Total':'2','X-WP-TotalPages':'2'})
        provider=WooStoreProvider(CONFIG,transport=httpx.MockTransport(handler))
        result=asyncio.run(provider.fetch_products());self.assertTrue(result.complete);self.assertEqual(len(result.products),2)
        def repeat(request):
            if request.url.path=='/robots.txt':return handler(request)
            return httpx.Response(200,json=[woo_row()],headers={'X-WP-Total':'2','X-WP-TotalPages':'2'})
        result=asyncio.run(WooStoreProvider(CONFIG,transport=httpx.MockTransport(repeat)).fetch_products())
        self.assertFalse(result.complete);self.assertEqual(result.products,[])

    def test_tilda_embedded_json_is_parsed_without_executing_scripts(self):
        data={'uid':123,'title':'Сумка Лето','price':'300.00','priceold':'400',
              'gallery':json.dumps([{'img':'https://example.com/bag.jpg'}]),
              'json_options':json.dumps([{'title':'Размер','values':['40','42']}])}
        text='<script>var product={title:untrusted}; var product='+json.dumps(data)+';</script><div class="t-store__prod-popup__price-currency">₽</div>'
        self.assertEqual(embedded_tilda_product(text)['uid'],123)
        product=tilda_product(CONFIG,text,'https://example.com/tproduct/123-bag')
        self.assertEqual(product.source_product_id,'123');self.assertEqual(product.price,Decimal('300.00'))
        self.assertEqual(product.category,'Сумки и рюкзаки');self.assertEqual(product.sizes,('40','42'))
        self.assertTrue(product.is_sale);self.assertEqual(product.image_url,'https://example.com/bag.jpg')

    def test_tilda_sitemap_does_not_follow_embedded_image_locations(self):
        product='<script>var product='+json.dumps({'uid':7,'title':'Выкройка юбки','price':'0','gallery':'[]'})+';</script>'
        def handler(request):
            if request.url.path=='/robots.txt':return httpx.Response(200,text='User-agent: *\nAllow: /')
            if request.url.path=='/sitemap-store.xml':return httpx.Response(200,text='''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"><url><loc>https://example.com/tproduct/7</loc><image:image><image:loc>https://external.invalid/photo</image:loc></image:image></url></urlset>''')
            return httpx.Response(200,text=product)
        result=asyncio.run(TildaSitemapProvider(CONFIG,transport=httpx.MockTransport(handler)).fetch_products())
        self.assertTrue(result.complete);self.assertEqual(len(result.products),1);self.assertTrue(result.products[0].is_free)

    def test_woo_html_uses_current_not_decorative_old_price(self):
        soup=BeautifulSoup('''<ul class="products"><li class="product post-12"><a class="woocommerce-LoopProduct-link" href="/product/12"><h2 class="woocommerce-loop-product__title">Выкройка рубашки</h2><img src="/shirt.jpg"></a><span class="price"><del><span class="amount">500 ₽</span></del><ins><span class="amount">350 ₽</span></ins><span class="woocommerce-Price-currencySymbol">₽</span></span></li></ul>''','html.parser')
        product=WooHTMLProvider(CONFIG).parse_page(soup,CONFIG['base_url'])[0]
        self.assertEqual(product.source_product_id,'12');self.assertEqual(product.price,350);self.assertEqual(product.old_price,500)
        self.assertTrue(product.is_sale);self.assertEqual(product.product_url,'https://example.com/product/12')

    def test_vigbo_stable_id_images_and_no_false_audience(self):
        card=BeautifulSoup('''<div class="static-grid-item" data-productid="88"><a class="product" href="/shop/shirt"><div class="image"><img data-src="//cdn.example.com/shirt.jpg"></div><div class="product-name">Рубашка 88</div><span class="product-price-min">300 pуб.</span></a></div>''','html.parser').div
        product=VigboProvider(CONFIG).parse_card(card,CONFIG['base_url'])
        self.assertEqual(product.source_product_id,'88');self.assertEqual(product.price,300)
        self.assertEqual(product.image_url,'https://cdn.example.com/shirt.jpg');self.assertIsNone(product.audience)

    def test_unknown_categories_do_not_become_new_taxonomy_buttons(self):
        self.assertEqual(category_for('Модель 123',['Текущая коллекция']),'Другое')
        self.assertEqual(category_for('Пижама Айрис',['Брюки','Рубашки']),'Бельё и домашняя одежда')
        self.assertEqual(audience_for(['Все изделия женщины'],'general'),'women')
        self.assertEqual(audience_for(['Мужские','Женские'],'general'),None)

    def test_login_only_courses_and_toys_are_not_imported(self):
        self.assertFalse(is_pattern('Печать выкройки'))
        self.assertFalse(is_pattern('Тестовый товар'))
        self.assertIsNone(tilda_product(CONFIG,'<title>Members area</title>','https://example.com/private'))
        self.assertIsNone(tilda_product(CONFIG,'<title>Other title</title>','https://example.com/coursewlbra'))
        self.assertIsNone(tilda_product(CONFIG,'<title>Выкройка игрушки Гусь SUSY</title>','https://example.com/susy'))

    def test_legacy_product_seo_fallback_preserves_unknown_price(self):
        manual='<meta property="og:image" content="https://example.com/cover.jpg"><div class="js-store-product" data-product-gen-uid="9"><h1 class="js-product-name">Рубашка</h1></div>'
        self.assertEqual(tilda_product(CONFIG,manual,'https://example.com/shirt').image_url,'https://example.com/cover.jpg')
        html='''<title>Тапочки Фродо</title><link rel="canonical" href="https://example.com/frodo"><meta property="og:title" content="Тапочки Фродо"><meta property="og:image" content="https://example.com/frodo.jpg">'''
        product=tilda_product(CONFIG,html,'https://example.com/frodo')
        self.assertIsNone(product.price);self.assertFalse(product.is_free)
        self.assertIsNone(product.source_product_id);self.assertEqual(product.image_url,'https://example.com/frodo.jpg')
