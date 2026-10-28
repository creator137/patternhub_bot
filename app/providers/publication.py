"""Publication dates only from a product's own explicit metadata."""
import json
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from app.models.catalog_policy import publication_datetime


def product_publication_date(html: str, product_url: str):
    soup = BeautifulSoup(html, 'html.parser')
    product_parts = urlsplit(product_url)
    path = product_parts.path.rstrip('/')
    heading = soup.select_one('h1')
    title = heading.get_text(' ',strip=True).casefold() if heading else None
    def walk(node):
        if isinstance(node, list):
            for child in node:
                found = walk(child)
                if found:
                    return found
        elif isinstance(node, dict):
            kinds = node.get('@type') or []
            if isinstance(kinds, str):
                kinds = [kinds]
            candidate = node.get('url') or node.get('@id')
            if candidate:
                candidate_parts = urlsplit(str(candidate))
                matches = (candidate_parts.path.rstrip('/') == path and
                           (not candidate_parts.hostname or
                            candidate_parts.hostname == product_parts.hostname))
            else:
                matches = bool(title and str(node.get('name') or '').strip().casefold() == title)
            if 'Product' in kinds and matches:
                return publication_datetime(node.get('datePublished'))
            if '@graph' in node:
                return walk(node['@graph'])
        return None
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            date = walk(json.loads(script.string or script.text))
            if date:
                return date
        except (ValueError, TypeError):
            continue
    kind = soup.select_one('meta[property="og:type"]')
    meta = soup.select_one('meta[property="product:published_time"]')
    if kind and kind.get('content') in {'product', 'product.item'} and meta:
        return publication_datetime(meta.get('content'))
    return None
