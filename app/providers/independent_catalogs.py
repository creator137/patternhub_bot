"""Public Laravel/Yii/MODX/UMI storefronts through the common product DTO."""
import asyncio
import json
import re
from dataclasses import replace
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from app.models.catalog_policy import publication_datetime
from app.providers.public_http import CatalogFetchError
from app.providers.public_stores import PublicStoreProvider
from app.providers.store_common import money, plain, product_from_values


def text(node):
    return node.get('content') or node.get_text(' ', strip=True) if node else None


def page_number(url):
    query = parse_qs(urlsplit(url).query)
    if query.get('page'):
        return int(query['page'][0])
    match = re.search(r'/page(\d+)/?$', urlsplit(url).path)
    return int(match[1]) if match else 1


class PatternEasyProvider(PublicStoreProvider):
    """The catalog embeds Laravel paginator JSON in its Vue component."""
    async def crawl(self, http):
        url, products, seen, expected = self.config['catalog_url'], [], set(), None
        for page in range(1, self.max_pages + 1):
            response = await http.get(url)
            soup = BeautifulSoup(response.content, 'html.parser')
            node = soup.select_one('catalog')
            if node is None or not node.get(':data'):
                raise CatalogFetchError('PatternEasy embedded catalog missing')
            data = json.loads(node[':data'])['paginator']
            if int(data['current_page']) != page:
                raise CatalogFetchError('PatternEasy pagination repeated')
            if expected is None:
                expected = int(data['total'])
            elif expected != int(data['total']):
                raise CatalogFetchError('PatternEasy collection changed during crawl')
            for row in data['data']:
                key = str(row['id'])
                if key in seen:
                    raise CatalogFetchError('PatternEasy repeated product')
                seen.add(key)
                self.add(products, self.parse_row(row))
            if not data.get('next_page_url'):
                if len(seen) != expected or page != int(data['last_page']):
                    raise CatalogFetchError('PatternEasy truncated collection')
                return products
            url = urljoin(self.base_url + '/', data['next_page_url'])
        raise CatalogFetchError('PatternEasy pagination limit')

    def parse_row(self, row):
        model = row.get('ready_pattern')
        if row.get('link_type') != 'ready_pattern' or not isinstance(model, dict):
            return None
        if not model.get('slug'):
            raise ValueError('PatternEasy canonical slug missing')
        info = row.get('priceInfo') or {}
        image = row.get('image') or {}
        drawing = row.get('tehris') or {}
        images = [item.get('path_big_img') or item.get('path_normal_img') for item in [image, drawing]]
        product = product_from_values(self.config, key=row['id'], name=row['title'],
            url=self.base_url + '/ready-patterns/' + model['slug'], currency='RUB',
            price=money(info.get('current', row.get('price'))), old_price=money(info.get('full')),
            images=images, description=row.get('short_text'),
            available=bool(row.get('status')) and not bool(model.get('is_archive')))
        if product:
            audience = {'woman':'women','woman_with_tall':'women','man':'men','man_with_tall':'men',
                        'child':'kids','children':'kids','boy':'kids','girl':'kids'}.get(model.get('size_type')) or product.audience
            return replace(product, audience=audience, difficulty=plain(model.get('difficulty')) or None,
                source_published_at=publication_datetime(row.get('published_at'))).normalized()
        return None


class IndependentListingProvider(PublicStoreProvider):
    """Audited server-rendered product cards and their actual next-page links."""
    SELECTORS = {'burda':'.item--pattern[data-id]', 'wanttosew':'.catalog__item',
        'sewfreedom':'.card-model', 'sewlevel':'.uss_eshop_item'}

    async def crawl(self, http):
        kind = self.config['template']
        if kind not in self.SELECTORS:
            raise ValueError('Unknown public listing template')
        starts = self.config.get('listing_urls') or [self.config['catalog_url']]
        products, visited = [], set()
        for start in starts:
            pending, fingerprints = [urljoin(self.base_url + '/', start)], set()
            while pending:
                url = pending.pop(0)
                if url in visited:
                    continue
                if len(visited) >= self.max_pages:
                    raise CatalogFetchError('Public listing page limit')
                visited.add(url)
                response = await http.get(url)
                soup = BeautifulSoup(response.content, 'html.parser')
                cards = soup.select(self.SELECTORS[kind])
                if not cards:
                    raise CatalogFetchError('Public listing has no recognized products')
                fingerprint = tuple(str(c.get('data-id') or c.get_text(' ',strip=True)) for c in cards)
                if fingerprint in fingerprints:
                    raise CatalogFetchError('Public listing pagination repeated')
                fingerprints.add(fingerprint)
                for card in cards:
                    product = self.parse_card(card, str(response.url))
                    if product and kind == 'wanttosew' and self.config.get('detail_prices'):
                        detail = await http.get(product.product_url)
                        ds = BeautifulSoup(detail.content, 'html.parser')
                        price = ds.select_one('[itemprop="price"], .product__price')
                        old = ds.select_one('.product__price-old, .old_price')
                        description = ds.select_one('[itemprop="description"], .product__description')
                        product = replace(product, price=money(text(price)), old_price=money(text(old)),
                            description=text(description)).normalized()
                    self.add(products, product)
                current = page_number(url)
                links = []
                for anchor in soup.select('.pagination a[href], .pages a[href], .uss_pagenator a[href]'):
                    target = urljoin(str(response.url), anchor['href'])
                    if page_number(target) > current:
                        links.append(target)
                pending.extend(u for u in dict.fromkeys(links) if u not in visited and u not in pending)
                pending.sort(key=page_number)
        return products

    def parse_card(self, card, url):
        kind = self.config['template']
        categories, key, old = [], None, None
        if kind == 'burda':
            link = card.select_one('a.pattern-link[href], .image a[href]')
            name = card.get('data-name') or card.get('data-ga-ec-name')
            key = card['data-id']
            price = money(card.get('data-price'))
            cost = card.select_one('.cost.has-discount .currency-item')
            old = money(text(cost))
            images = [n.get('src') for n in card.select('.image img')]
            categories = [card.get('data-category') or '']
        elif kind == 'wanttosew':
            links = card.select('a.catalog__item-title[href]')
            link = next((n for n in links if n.get_text(strip=True)), links[0] if links else None)
            name = text(link)
            identity = card.select_one('[data-data-id]')
            key = identity.get('data-data-id') if identity else None
            price = None
            images = [n.get('src') for n in card.select('.catalog__item-photo img')]
        elif kind == 'sewfreedom':
            link = card.select_one('.card-model__title[href]')
            name = text(link)
            identity = card.select_one('input[name="good_id"]')
            key = identity.get('value') if identity else None
            price = money(text(card.select_one('.card-model__price')))
            old = money(text(card.select_one('.card-model__old-price')))
            images = [n.get('src') for n in card.select('.card-model__img')]
        else:
            link = card.select_one('.uss_shop_name a[href]')
            name = text(link)
            node = card.select_one('[onclick*="addWish"]')
            match = re.search(r'addWish\(this,(\d+)', node['onclick']) if node else None
            key = match[1] if match else None
            price = money(text(card.select_one('.actual_price .price_class')))
            old = money(text(card.select_one('.old_price .price_class')))
            images = [n.get('src') for n in card.select('img.pos_main_img')]
        if link is None or not name:
            raise ValueError('Public listing own product title/link missing')
        target = urljoin(url, link['href'])
        if re.search(r'/store/(?:material|tkan|furnitur)|/pechatnye-vykroyki/', urlsplit(target).path, re.I):
            return None
        # Only explicit section names/URL labels determine audience.
        context = urlsplit(target).path.rstrip('/')+'/'+' '+urlsplit(url).path.rstrip('/')+'/'
        for needle, label in self.config.get('section_labels', {}).items():
            if needle in context:
                categories.append(label)
        return product_from_values(self.config, key=key, name=name, url=target,
            price=price, old_price=old, currency='RUB', images=images, categories=categories)
