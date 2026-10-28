"""Public VirtueMart listing cards with offset pagination."""
from dataclasses import replace
import re
from urllib.parse import parse_qs,urljoin,urlsplit

from bs4 import BeautifulSoup

from app.providers.public_http import CatalogFetchError
from app.providers.public_stores import PublicStoreProvider
from app.providers.store_common import money,product_from_values


class VirtueMartProvider(PublicStoreProvider):
    async def crawl(self,http):
        pending,visited,products,seen=[self.config['catalog_url']],set(),[],set()
        for _ in range(self.max_pages):
            if not pending:
                return products
            url=pending.pop(0)
            if url in visited:
                continue
            visited.add(url)
            r=await http.get(url)
            soup=BeautifulSoup(r.content,'html.parser')
            # The listing has four recommendation cards outside the product grid.
            cards=soup.select('.product-wrap.grid .product-block')
            if not cards:
                raise CatalogFetchError('VirtueMart product grid missing')
            keys={m[1] for c in cards if (m:=re.search(r'\bproduct-id(\d+)\b',' '.join(c.get('class',[]))))}
            if not keys or keys<=seen:
                raise CatalogFetchError('VirtueMart pagination repeated')
            for card in cards:
                p=self.parse_card(card,str(r.url))
                if p and p.source_product_id not in seen:
                    self.add(products,p);seen.add(p.source_product_id)
            current=int(parse_qs(urlsplit(url).query).get('start',['0'])[0])
            for a in soup.select('.pagination a[href]'):
                target=urljoin(str(r.url),a['href'])
                q=parse_qs(urlsplit(target).query)
                if q.get('start') and int(q['start'][0])>current and target not in visited and target not in pending:
                    pending.append(target)
            pending.sort(key=lambda u:int(parse_qs(urlsplit(u).query).get('start',['0'])[0]))
        raise CatalogFetchError('VirtueMart pagination limit')

    def parse_card(self,card,url):
        identity=re.search(r'\bproduct-id(\d+)\b',' '.join(card.get('class',[])))
        title=card.select_one('.product-name a[href]')
        if not identity or not title:
            raise ValueError('VirtueMart product title/ID missing')
        price=card.select_one('[itemprop="price"]')
        old=card.select_one('.price-crossed .PricebasePriceWithTax')
        images=[n.get('content') or n.get('src') for n in card.select('[itemprop="image"],.product-image img')]
        p=product_from_values(self.config,key=identity[1],name=title.get_text(' ',strip=True),
            url=urljoin(url,title['href']),price=money(price.get('content')) if price else None,
            old_price=money(old.get_text()) if old else None,currency='RUB',images=images,
            categories=[n.get('alt','') for n in card.select('.product-image img')])
        if p:
            difficulty=card.select_one('.difficulty')
            level=re.search(r'\bdifficulty-(\d+)\b',' '.join(difficulty.get('class',[]))) if difficulty else None
            return replace(p,difficulty=level[1] if level else None).normalized()
        return None
