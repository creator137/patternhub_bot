"""EasySew's live catalog, including broken pages without false completeness."""
import logging
import asyncio
from dataclasses import replace
import re
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup
from app.providers.bitrix_catalog import BitrixCatalogProvider
from app.providers.base import ProviderResult
from app.providers.public_http import PublicCatalogHTTP,CatalogFetchError,CatalogHTTPError

logger=logging.getLogger(__name__)
class EasySewProvider(BitrixCatalogProvider):
    async def fetch_products(self):
        products,errors={},[]
        self.last_skipped=0
        http=PublicCatalogHTTP(self.base_url,transport=self.transport,robots_allow=self.config.get('robots_allow',()))
        try:
            async with http:
                for section in [1,2,3]:
                    root=self.base_url+f'/catalogy/{section}/'
                    try:
                        r=await http.get(root)
                        soup=BeautifulSoup(r.content,'html.parser')
                        cards=self.cards(soup)
                        if not cards:raise CatalogFetchError('EasySew catalog markup missing: '+root)
                        for c in cards:
                            p=self.parse_card(c,root)
                            if p:products[p.source_product_id]=p
                        nav=[]
                        for a in soup.select('a[href]'):
                            target=urljoin(root,a['href'])
                            match=re.search(r'[?&](PAGEN_\d+)=(\d+)',target)
                            if match and urlsplit(target).path==urlsplit(root).path:nav.append((match[1],int(match[2])))
                        last=max([n for _,n in nav],default=1)
                        if last>self.max_pages:raise CatalogFetchError('EasySew listing limit')
                        key=nav[0][0] if nav else None
                        for n in range(2,last+1):
                            url=root+f'?{key}={n}'
                            try:
                                r=await http.get(url)
                                cards=self.cards(BeautifulSoup(r.content,'html.parser'))
                                if not cards:raise CatalogFetchError('EasySew empty catalog page: '+url)
                                for c in cards:
                                    p=self.parse_card(c,url)
                                    if p:products[p.source_product_id]=p
                            except (CatalogFetchError,ValueError,KeyError) as e:
                                errors.append(str(e));logger.warning('%s',e)
                    except (CatalogFetchError,ValueError,KeyError) as e:
                        errors.append(str(e));logger.warning('%s',e)
                if self.config.get('enrich_details'):
                    gate=asyncio.Semaphore(2)
                    async def detail(product):
                        async with gate:
                            try:
                                response=await http.get(product.product_url)
                                return self.parse_detail(response.text,str(response.url))
                            except (CatalogFetchError,ValueError,KeyError) as error:
                                # Keep the live listing card when the site's
                                # own detail URL is broken or returns empty 200.
                                errors.append(str(error));logger.warning('%s',error)
                                if isinstance(error,CatalogHTTPError) and error.status_code in {404,410}:
                                    return replace(product,is_available=False)
                                return None
                    values=list(products.values())
                    for start in range(0,len(values),20):
                        for product in await asyncio.gather(*(detail(p) for p in values[start:start+20])):
                            if product:products[product.source_product_id]=product
        except CatalogFetchError as e:errors.append(str(e))
        self.requests_made,self.retries_made=http.requests_made,http.retries_made
        self.last_errors=errors
        return ProviderResult(list(products.values()),errors=len(errors),complete=bool(products) and not errors)
