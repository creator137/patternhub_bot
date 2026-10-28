"""Regression coverage for the newly audited public catalog protocols."""
import asyncio
from dataclasses import replace
from datetime import datetime,timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock,patch
import httpx
from bs4 import BeautifulSoup
from app.providers.public_http import PublicCatalogHTTP,CatalogFetchError,CatalogHTTPError
from app.providers.marymake import MarymakeProvider
from app.providers.taplink import TaplinkProvider,embedded_data
from app.providers.tilda_api import TildaAPIProvider
from app.providers.wordpress_posts import WordPressPostsProvider
from app.providers.wordpress_catalog import WordPressSitemapProvider
from app.providers.independent_catalogs import PatternEasyProvider,IndependentListingProvider
from app.providers.shkatulka import ShkatulkaProvider
from app.providers.virtuemart import VirtueMartProvider
from app.providers.lekala_legacy import LekalaLegacyProvider
from app.providers.insales_catalog import ShapeCatalogProvider,AnsewsCatalogProvider
from app.providers.easysew import EasySewProvider
from app.providers.burda import BurdaProvider
from app.providers.registry import available_providers,create_provider
from app.models.product import ParsedProduct
from app.models.categories import normalize_category

FIX=json.loads((Path(__file__).parent/'fixtures/public_catalogs/cards.json').read_text())
CFG=dict(source='test',display_name='Test',base_url='https://example.com',catalog_url='https://example.com/catalog')

def soup(key):return BeautifulSoup(FIX[key],'html.parser')

def fetch(cls,routes,config=None,**kwargs):
    calls=[]
    def handler(req):
        calls.append(req)
        if req.url.path=='/robots.txt':return httpx.Response(200,text='User-agent: *\nAllow: /')
        response=routes(req)
        return response if isinstance(response,httpx.Response) else httpx.Response(200,text=response)
    p=cls(CFG|dict(config or {}),transport=httpx.MockTransport(handler),**kwargs)
    with patch('app.providers.public_http.asyncio.sleep',new=AsyncMock()):r=asyncio.run(p.fetch_products())
    return r,calls,p

class CatalogCompletionTests(unittest.TestCase):
    def test_every_enabled_supplier_has_a_real_provider(self):
        self.assertEqual(len(available_providers()),88)
        for source in available_providers():self.assertEqual(create_provider(source).source,source)

    def test_marymake_options_are_not_sale_or_duplicate(self):
        rows=MarymakeProvider(CFG).parse_listing(FIX['marymake'],CFG['catalog_url'])
        self.assertEqual(len(rows),1);p=rows[0]
        self.assertEqual(p.price,Decimal('600'));self.assertFalse(p.is_sale)
        self.assertEqual(p.product_url,'https://example.com/coat')
        self.assertEqual(p.image_url,'https://cdn-st2.vigbo.com/gallery/1000-coat.jpg')

    def test_marymake_free_and_explicit_difficulty(self):
        html=FIX['marymake'].split("<div class='row'>")[1]
        p=MarymakeProvider(CFG).parse_listing("<div class='row'>"+html.replace('3000 RUB','Бесплатно'),CFG['catalog_url'])[0]
        self.assertTrue(p.is_free);self.assertTrue(p.is_beginner)

    def test_marymake_structure_and_foreign_url_fail_closed(self):
        p=MarymakeProvider(CFG)
        for html in ['<html>Blocked</html>',FIX['marymake'].replace("href='/coat'","href='https://evil.invalid/coat'")]:
            with self.assertRaises(CatalogFetchError):p.parse_listing(html,CFG['catalog_url'])

    def test_taplink_only_json_is_decoded(self):
        with self.assertRaises(CatalogFetchError):embedded_data('<script>window.data = alert(1)</script>')
        self.assertEqual(embedded_data('window.data = {"data":{"products":[]}};'),{'products':[]})

    def test_taplink_product_real_id_and_all_photos(self):
        row=dict(product_id=255,title='Детские брюки',price='250',price_compare='300',is_active=1,is_visible=1,is_sellable=1,pictures=[{'filename':'a.jpg'},{'filename':'b.jpg'}])
        p=TaplinkProvider(CFG).parse_detail('<title>Детские выкройки</title>window.data = '+json.dumps({'data':{'product':row}}),'https://example.com/o/ff/')
        self.assertEqual(p.source_product_id,'255');self.assertEqual(p.audience,'kids');self.assertTrue(p.is_sale)
        self.assertEqual(p.image_urls,('https://taplink.st/p/a.jpg','https://taplink.st/p/b.jpg'))

    def test_tilda_price_options_do_not_become_free_or_false_sale(self):
        row=dict(uid=5,title='Выкройка платья',url='/dress',price=0,gallery=json.dumps([{'img':'/front.jpg'}]),editions=[{'price':'800','priceold':'1000'},{'price':'400','priceold':'400'}])
        p=TildaAPIProvider(CFG).parse_row(row)
        self.assertEqual(p.price,Decimal('400'));self.assertFalse(p.is_free);self.assertFalse(p.is_sale)
        self.assertEqual(p.source_product_id,'5');self.assertEqual(p.image_url,'https://example.com/front.jpg')

    def test_tilda_excludes_courses_not_pattern_video_bundles(self):
        p=TildaAPIProvider(CFG)
        self.assertIsNone(p.parse_row(dict(uid=1,title='Марафон по шитью',url='/marathon')))
        self.assertIsNotNone(p.parse_row(dict(uid=2,title='Выкройка платья с видео',url='/dress')))

    def test_tilda_public_api_requires_explicit_authorization(self):
        r,_,_=fetch(TildaAPIProvider,lambda r:'',{})
        self.assertFalse(r.complete);self.assertEqual(r.errors,1)

    def test_tilda_foreign_identity_and_gallery_schema(self):
        p=TildaAPIProvider(CFG)
        for row in [dict(uid=1,title='Платье',url='https://evil.invalid/a'),dict(uid=1,title='Платье',url='/a',gallery={1:2})]:
            with self.assertRaises(CatalogFetchError):p.parse_row(row)

    def test_shkatulka_post_pagination_until_empty(self):
        def routes(req):
            if req.method=='GET':return '<form class="dfilter"><input name="q" value=""></form>'
            self.assertEqual(req.headers['x-requested-with'],'XMLHttpRequest')
            return FIX['shkatulka'] if req.url.params['page']=='1' else ''
        r,c,_=fetch(ShkatulkaProvider,routes)
        self.assertTrue(r.complete);self.assertEqual(len(r.products),1)
        p=r.products[0];self.assertTrue(p.is_sale);self.assertEqual(len(p.image_urls),2)
        self.assertEqual([x.method for x in c],['GET','GET','POST','POST'])

    def test_shkatulka_repeated_page_never_reconciles(self):
        r,_,_=fetch(ShkatulkaProvider,lambda r:'<form class="dfilter"></form>' if r.method=='GET' else FIX['shkatulka'])
        self.assertFalse(r.complete)

    def test_shkatulka_nonempty_error_not_end_of_catalog(self):
        r,_,_=fetch(ShkatulkaProvider,lambda r:'<form class="dfilter"></form>' if r.method=='GET' else '<h1>Server error</h1>')
        self.assertFalse(r.complete)

    def test_virtuemart_own_grid_id_category_audience(self):
        p=VirtueMartProvider(CFG).parse_card(soup('modety').select_one('.product-block'),CFG['catalog_url'])
        self.assertEqual(p.source_product_id,'2356');self.assertEqual(p.audience,'kids')
        self.assertEqual(p.category,'Платья');self.assertTrue(p.is_sale)
        self.assertEqual(p.image_url,'https://example.com/front.jpg')

    def test_virtuemart_recommendations_not_imported(self):
        r,_,_=fetch(VirtueMartProvider,lambda r:FIX['modety']+'<div class="product-block">Recommendation</div>')
        self.assertTrue(r.complete);self.assertEqual(len(r.products),1)

    def test_legacy_real_model_identity_ignores_banner(self):
        ps=LekalaLegacyProvider(CFG).parse_page(soup('legacy'),'https://example.com/mod-p.php','Брюки и шорты','men',False)
        self.assertEqual(len(ps),1);self.assertEqual(ps[0].source_product_id,'1234')
        self.assertEqual(ps[0].audience,'men');self.assertEqual(ps[0].category,'Брюки и шорты')
        self.assertEqual(len(ps[0].image_urls),2);self.assertFalse(ps[0].is_free)

    def test_legacy_free_only_from_explicit_section(self):
        p=LekalaLegacyProvider(CFG).parse_page(soup('legacy'),'https://example.com/mod-p.php',None,'men',True)[0]
        self.assertTrue(p.is_free);self.assertEqual(p.price,Decimal('0'))

    def test_wordpress_scoped_product_price_and_gallery(self):
        p=WordPressSitemapProvider(CFG).parse_detail(FIX['wordpress'],'https://example.com/product/dress')
        self.assertEqual(p.source_product_id,'42');self.assertTrue(p.is_sale)
        self.assertEqual(p.price,Decimal('500'));self.assertEqual(p.image_url,'https://example.com/front.jpg')

    def test_wordpress_blog_uses_actual_dates_not_import_time(self):
        p=WordPressPostsProvider(CFG).parse_post(dict(id=42,link='https://example.com/p',date_gmt='2023-01-01T12:00:00',title={'rendered':'Детская блузка'},content={'rendered':'<p>Выкройка детской блузки</p><img src="/front.jpg">'}))
        self.assertEqual(p.source_published_at.year,2023);self.assertEqual(p.audience,'kids')
        self.assertFalse(p.is_free);self.assertFalse(p.is_new)

    def test_wordpress_blog_skips_size_tables_and_magazines(self):
        p=WordPressPostsProvider(CFG)
        for title in ['Размер выкройки Евро, США','Таблица размеров','Журнал выкроек']:
            self.assertIsNone(p.parse_post(dict(id=42,link='https://example.com/p',title={'rendered':title},content={'rendered':'Выкройка'})))

    def test_wordpress_bulk_featured_media_only_images(self):
        async def run():
            p=WordPressPostsProvider(CFG);p._featured={'1':11,'2':12}
            class HTTP:
                async def get(self,url):return httpx.Response(200,json=[dict(id=11,source_url='https://example.com/front.webp',mime_type='image/webp'),dict(id=12,source_url='https://example.com/pattern.pdf',mime_type='application/pdf')])
            ps=[ParsedProduct(source='test',source_product_id=str(n),name='Платье',product_url=f'https://example.com/{n}') for n in [1,2]]
            ps=await p.enrich_covers(HTTP(),ps,'2026-01-01T00:00:00Z')
            self.assertTrue(ps[0].image_url.endswith('.webp'));self.assertIsNone(ps[1].image_url)
        asyncio.run(run())

    def test_wordpress_post_truncated_totals_incomplete(self):
        def route(req):return httpx.Response(200,json=[],headers={'X-WP-Total':'10'})
        r,_,_=fetch(WordPressPostsProvider,route)
        self.assertFalse(r.complete)

    def test_shape_uses_only_actual_gallery_not_size_table(self):
        p=ShapeCatalogProvider(CFG).parse_product(FIX['shape'],'https://example.com/model/42',['Женские выкройки'])
        self.assertEqual(p.source_product_id,'42');self.assertEqual(p.audience,'women')
        self.assertEqual(p.sizes,('44',));self.assertEqual(len(p.image_urls),1)

    def test_ansews_requires_own_jsonld_and_stable_id(self):
        with self.assertRaises(CatalogFetchError):AnsewsCatalogProvider(CFG).parse_product('<h1>Платье</h1>','https://example.com/products/a')

    def test_patterneasy_outer_price_not_nested_placeholder_zero(self):
        row=dict(id=42,title='Выкройка платья',link_type='ready_pattern',ready_pattern={'slug':'dress','price':0,'size_type':'woman'},status=1,priceInfo={'current':500,'full':700},image={'path_big_img':'/front.jpg'})
        p=PatternEasyProvider(CFG).parse_row(row)
        self.assertEqual(p.price,Decimal('500'));self.assertFalse(p.is_free);self.assertTrue(p.is_sale)
        self.assertEqual(p.product_url,'https://example.com/ready-patterns/dress');self.assertEqual(p.audience,'women')

    def test_patterneasy_no_next_with_wrong_total_incomplete(self):
        payload={'paginator':{'current_page':1,'last_page':1,'total':10,'data':[],'next_page_url':None}}
        html='<catalog :data=\''+json.dumps(payload)+'\'></catalog>'
        r,_,_=fetch(PatternEasyProvider,lambda r:html)
        self.assertFalse(r.complete)

    def test_easysew_broken_page_preserves_products_without_reconciliation(self):
        def routes(req):
            if req.url.query:return httpx.Response(404)
            section=req.url.path.strip('/').split('/')[-1]
            return FIX['easysew'].replace('/1/42/',f'/{section}/{section}42/')+'<a href="?PAGEN_2=2">2</a>'
        r,_,_=fetch(EasySewProvider,routes,{'source':'easysew'})
        self.assertFalse(r.complete);self.assertEqual(r.errors,3);self.assertEqual(len(r.products),3)
        self.assertEqual({p.audience for p in r.products},{'women','men','kids'})

    def test_audited_routes_do_not_authorize_account_or_foreign_origin(self):
        async def run():
            def handler(req):return httpx.Response(200,text='User-agent: *\nDisallow: /' if req.url.path=='/robots.txt' else 'ok')
            async with PublicCatalogHTTP('https://example.com',transport=httpx.MockTransport(handler),robots_allow=[r'/catalog/\?page=\d+']) as h:
                self.assertEqual((await h.get('https://example.com/catalog/?page=2')).text,'ok')
                for u in ['https://example.com/account','https://evil.invalid/catalog/?page=2','https://example.com/catalog/?page=2&token=secret']:
                    with self.assertRaises(CatalogFetchError):await h.get(u)
        with patch('app.providers.public_http.asyncio.sleep',new=AsyncMock()):asyncio.run(run())

    def test_http_typed_404_not_retried(self):
        async def run():
            def handler(req):return httpx.Response(200,text='') if req.url.path=='/robots.txt' else httpx.Response(404)
            async with PublicCatalogHTTP('https://example.com',transport=httpx.MockTransport(handler)) as h:
                with self.assertRaises(CatalogHTTPError) as e:await h.get('https://example.com/gone')
                self.assertEqual(e.exception.status_code,404);self.assertEqual(h.requests_made,2)
        asyncio.run(run())

    def test_new_garment_words_share_existing_taxonomy(self):
        for word,category in [('Штанишки','Брюки и шорты'),('Джоггеры','Брюки и шорты'),('Косуха','Верхняя одежда'),('Ромпер','Комбинезоны'),('Блуза Луна','Рубашки, блузки и топы'),('Берет Рика','Аксессуары')]:
            self.assertEqual(normalize_category(word),category)

    def test_tilda_public_json_without_json_content_type_paginates(self):
        def routes(req):
            if req.url.host=='example.com':return '<script>var options={storepart:"42"}</script>'
            n=int(req.url.params['slice'])
            return httpx.Response(200,json={'partuid':'42','total':2,'products':[dict(uid=n,title='Выкройка платья',url=f'https://example.com/p/{n}',price='100')]},headers={'content-type':'text/html'})
        r,_,_=fetch(TildaAPIProvider,routes,{'public_api_authorized':True})
        self.assertTrue(r.complete);self.assertEqual(len(r.products),2)

    def test_tilda_truncated_or_repeated_api_never_complete(self):
        def routes(req):
            if req.url.host=='example.com':return '<script>var options={storepart:"42"}</script>'
            return httpx.Response(200,json={'partuid':'42','total':2,'products':[dict(uid=1,title='Выкройка платья',url='https://example.com/p/1')]})
        r,_,_=fetch(TildaAPIProvider,routes,{'public_api_authorized':True})
        self.assertFalse(r.complete)

    def test_burda_checkpoint_resumes_without_losing_old_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            def page(n):return f'<div id="pagination-container" data-page-count="3" data-current-page="{n}"></div><div class="item--pattern" data-id="{n}" data-name="Платье" data-price="100"><a class="pattern-link" href="/p/{n}"></a><div class="image"><img src="/p{n}.jpg"></div></div>'
            def first(req):
                n=int(req.url.params['page'])
                return httpx.Response(503) if n==2 else page(n)
            cfg={'template':'burda','crawl_checkpoint':folder}
            r,_,_=fetch(BurdaProvider,first,cfg)
            self.assertFalse(r.complete)
            self.assertTrue((Path(folder)/'page-3.html.gz').exists())
            def second(req):
                n=int(req.url.params['page'])
                self.assertNotEqual(n,3)
                return page(n)
            r,_,_=fetch(BurdaProvider,second,cfg)
            self.assertTrue(r.complete);self.assertEqual(len(r.products),3)
            self.assertTrue(json.loads((Path(folder)/'state.json').read_text())['complete'])

    def test_burda_page_repetition_is_not_success(self):
        def routes(req):return '<div id="pagination-container" data-page-count="2" data-current-page="1"></div><div class="item--pattern" data-id="1" data-name="Платье" data-price="100"><a class="pattern-link" href="/p/1"></a></div>'
        with tempfile.TemporaryDirectory() as folder:
            r,_,_=fetch(BurdaProvider,routes,{'template':'burda','crawl_checkpoint':folder})
            self.assertFalse(r.complete)

    def test_tilda_explicit_beginner_not_from_garment_name(self):
        p=ParsedProduct(source='test',name='Платье',product_url='https://example.com/p',description='Уровень сложности: новичок').normalized()
        self.assertTrue(p.is_beginner)
        p=replace(p,description='Не подходит для новичков',is_beginner=None).normalized()
        self.assertIsNone(p.is_beginner)

    def test_ansews_literal_flight_variants_and_jsonld_identity(self):
        schema={'@type':'Product','name':'Выкройка платья','url':'https://example.com/products/dress','image':['/front.jpg'],'category':'Женские выкройки','offers':{'@type':'Offer','price':'500','priceCurrency':'RUB','availability':'https://schema.org/InStock'}}
        flight='1:'+json.dumps({'productId':'real-123','productSlug':'dress'},separators=(',',':'))+'\n'+json.dumps({'id':'v1','productId':'real-123','attributesJson':{'pa_razmer':'44','pa_rost':'164'}},separators=(',',':'))
        html='<script type="application/ld+json">'+json.dumps(schema)+'</script><script>self.__next_f.push('+json.dumps([1,flight])+')</script>'
        p=AnsewsCatalogProvider(CFG).parse_product(html,'https://example.com/products/dress')
        self.assertEqual(p.source_product_id,'real-123');self.assertEqual(p.price,Decimal('500'))
        self.assertEqual(p.sizes,('44',));self.assertEqual(p.heights,('164',));self.assertEqual(p.audience,'women')

    def test_extended_tilda_static_page_preserves_actual_gallery(self):
        from app.providers.tilda_extended import ExtendedTildaProvider
        html='<link rel="canonical" href="https://example.com/dress"><div class="js-product-single" data-product-uid="42"><h1 class="js-product-name">Выкройка детского платья</h1><span class="js-product-price">250</span><span class="js-product-price-currency">₽</span><img class="t-slds__img" data-original="/front.jpg"><img class="t-slds__img" data-original="/back.jpg"></div>'
        p=ExtendedTildaProvider(CFG).parse_product(html,'https://example.com/dress')
        self.assertEqual(p.source_product_id,'42');self.assertEqual(p.price,Decimal('250'))
        self.assertEqual(p.audience,'kids');self.assertEqual(len(p.image_urls),2)

    def test_wordpress_media_failure_makes_full_import_incomplete(self):
        row=dict(id=42,link='https://example.com/p',featured_media=123,title={'rendered':'Выкройка платья'},content={'rendered':'Выкройка платья'})
        def route(req):
            if '/media' in req.url.path:return httpx.Response(503)
            return httpx.Response(200,json=[row],headers={'X-WP-Total':'1'})
        r,_,_=fetch(WordPressPostsProvider,route)
        self.assertFalse(r.complete)

    def test_wordpress_incomplete_checkpoint_resumes_without_refetching_pages(self):
        row=dict(id=42,link='https://example.com/p',featured_media=123,title={'rendered':'Выкройка платья'},content={'rendered':'Выкройка платья'})
        with tempfile.TemporaryDirectory() as folder:
            def first(req):
                if '/media' in req.url.path:return httpx.Response(503)
                return httpx.Response(200,json=[row],headers={'X-WP-Total':'1'})
            r,_,_=fetch(WordPressPostsProvider,first,{'crawl_checkpoint':folder})
            self.assertFalse(r.complete)
            def second(req):
                self.assertTrue('/media' in req.url.path)
                return httpx.Response(200,json=[dict(id=123,source_url='https://example.com/cover.jpg',mime_type='image/jpeg')])
            r,_,_=fetch(WordPressPostsProvider,second,{'crawl_checkpoint':folder})
            self.assertTrue(r.complete);self.assertEqual(r.products[0].image_url,'https://example.com/cover.jpg')

    def test_easysew_deleted_detail_is_unavailable_but_timeout_is_not_removal(self):
        def routes(req):
            if req.url.path.count('/')>3:return httpx.Response(404)
            section=req.url.path.strip('/').split('/')[-1]
            return FIX['easysew'].replace('/1/42/',f'/{section}/{section}42/')
        r,_,_=fetch(EasySewProvider,routes,{'source':'easysew','enrich_details':True})
        self.assertFalse(r.complete);self.assertEqual(len(r.products),3)
        self.assertTrue(all(not p.is_available for p in r.products))

    def test_polo_word_does_not_classify_striped_suits(self):
        self.assertEqual(normalize_category('Костюм полосатый'),'Костюм полосатый')
        self.assertEqual(normalize_category('Поло детское'),'Худи, футболки и лонгсливы')

    def test_woo_uses_advertised_native_derivative_instead_of_huge_original(self):
        from app.providers.store_common import woo_image_url
        image={'src':'https://example.com/huge.png','srcset':'https://example.com/huge.png 4500w, https://example.com/small.png 210w, https://example.com/detail.png 1436w'}
        self.assertEqual(woo_image_url(image),'https://example.com/detail.png')
        self.assertEqual(woo_image_url({'src':image['src']}),image['src'])
        self.assertEqual(woo_image_url({'src':image['src'],'srcset':'invalid'}),image['src'])

    def test_source_section_audience_survives_flat_product_urls(self):
        cfg=CFG|{'template':'sewfreedom','section_labels':{'/detyam/':'Детские выкройки'}}
        html='<div class="card-model"><input name="good_id" value="42"><a class="card-model__title" href="/model/dress">Платье</a></div>'
        p=IndependentListingProvider(cfg).parse_card(BeautifulSoup(html,'html.parser').div,'https://example.com/katalog/detyam')
        self.assertEqual(p.audience,'kids')

    def test_october_shopaholic_own_id_price_gallery_and_sizes(self):
        from app.providers.insales_catalog import OctoberCatalogProvider
        html='<h1 ymecommerce-field="name">Выкройка детского платья</h1><div class="product-card" data-product-id="42"><span ymecommerce-field="category" value="Детские выкройки"></span><span class="product-card__price">250 ₽</span><del class="product-card__old-price">300 ₽</del><div class="product-card__gallery-top"><img src="/front.jpg"></div><select name="size"><option value="92">92</option></select></div>'
        p=OctoberCatalogProvider(CFG).parse_product(html,'https://example.com/catalog/dresses/42')
        self.assertEqual(p.source_product_id,'42');self.assertTrue(p.is_sale);self.assertEqual(p.audience,'kids')
        self.assertEqual(p.sizes,('92',));self.assertEqual(p.image_url,'https://example.com/front.jpg')

    def test_audience_uses_explicit_title_words_without_garment_guessing(self):
        from app.providers.store_common import product_from_values
        def product(name,**kw):return product_from_values(CFG,name=name,url='https://example.com/p',**kw)
        self.assertIsNone(product('Рубашка').audience)
        self.assertEqual(product('Мужская рубашка').audience,'men')
        self.assertEqual(product('Брюки для детей').audience,'kids')
        self.assertEqual(product('Рубашка',categories=['Женские выкройки']).audience,'women')
