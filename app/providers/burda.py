"""Burda's public paginated catalog with resumable, bounded page batches."""
import asyncio
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
from bs4 import BeautifulSoup
from app.providers.independent_catalogs import IndependentListingProvider
from app.providers.public_http import CatalogFetchError

class BurdaProvider(IndependentListingProvider):
    async def crawl(self, http):
        cache=Path(self.config.get('crawl_checkpoint','data/provider_crawls/burdastyle'))
        cache.mkdir(parents=True,exist_ok=True)
        first=await http.get(self.base_url+'/vikroyki/?per-page=24&page=1')
        soup=BeautifulSoup(first.content,'html.parser')
        nav=soup.select_one('#pagination-container[data-page-count][data-current-page]')
        if nav is None or int(nav['data-current-page'])!=1:
            raise CatalogFetchError('Burda public pagination metadata missing')
        total=int(nav['data-page-count'])
        if not 1<=total<=self.max_pages:
            raise CatalogFetchError('Burda page limit')
        now=datetime.now(timezone.utc)
        state_path=cache/'state.json'
        state=json.loads(state_path.read_text()) if state_path.exists() else {}
        fresh=(state.get('total')==total and not state.get('complete') and state.get('observed_at')
            and 0<=(now-datetime.fromisoformat(state['observed_at'])).total_seconds()<86400)
        if not fresh:
            for p in cache.glob('page-*.html.gz'): p.unlink()
            state={'total':total,'observed_at':now.isoformat(),'complete':False}
            state_path.write_text(json.dumps(state))
        (cache/'page-1.html.gz').write_bytes(gzip.compress(first.content))
        gate=asyncio.Semaphore(3)
        async def read(number):
            path=cache/f'page-{number}.html.gz'
            async with gate:
                if path.exists():
                    html=gzip.decompress(path.read_bytes())
                else:
                    r=await http.get(self.base_url+f'/vikroyki/?per-page=24&page={number}')
                    html=r.content
                s=BeautifulSoup(html,'html.parser')
                nav=s.select_one('#pagination-container[data-current-page][data-page-count]')
                cards=s.select('.item--pattern[data-id]')
                if (not nav or int(nav['data-current-page'])!=number or int(nav['data-page-count'])!=total or not cards):
                    raise CatalogFetchError('Burda truncated/repeated/changed page: '+str(number))
                path.write_bytes(gzip.compress(html))
                return [self.parse_card(c,self.base_url+'/vikroyki/') for c in cards]
        products,seen=[],set()
        for offset in range(1,total+1,12):
            rows=await asyncio.gather(*(read(n) for n in range(offset,min(offset+12,total+1))),return_exceptions=True)
            failures=[row for row in rows if isinstance(row,BaseException)]
            if failures:raise failures[0]
            for batch in rows:
                for p in batch:
                    if p and p.source_product_id in seen:
                        raise CatalogFetchError('Burda catalog changed: duplicate product across pages')
                    if p:seen.add(p.source_product_id)
                    self.add(products,p)
        state['complete']=True
        state_path.write_text(json.dumps(state))
        return products
