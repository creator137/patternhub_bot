"""Extract only the product's own gallery, not recommendations or reviews."""
import json
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup


def clean_images(values, product_url):
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        url = urljoin(product_url, value.strip())
        parts = urlsplit(url)
        if parts.scheme in {'http', 'https'} and not parts.path.lower().endswith(('.svg', '.gif', '.mp4')) and url not in result:
            result.append(url)
    return tuple(result)


def html_gallery(html: str, product_url: str, selector: str = '') -> tuple[str, ...]:
    soup = BeautifulSoup(html, 'html.parser')
    values = []
    if selector:
        for node in soup.select(selector):
            value = next((node.get(key) for key in ('data-large_image', 'data-src', 'src', 'href') if node.get(key)), None)
            if value:
                values.append(value)
    if values:
        return clean_images(values, product_url)
    def walk(node):
        if isinstance(node, list):
            for entry in node:
                walk(entry)
        elif isinstance(node, dict):
            if node.get('@type') == 'Product' or 'Product' in (node.get('@type') if isinstance(node.get('@type'), list) else []):
                images = node.get('image') or []
                for image in images if isinstance(images, list) else [images]:
                    values.append(image.get('url') or image.get('contentUrl') if isinstance(image, dict) else image)
            if '@graph' in node:
                walk(node['@graph'])
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(node.string or node.text))
        except (ValueError, TypeError):
            continue
    if not values:
        meta = soup.select_one('meta[property="og:image"]')
        kind = soup.select_one('meta[property="og:type"]')
        if meta and kind and kind.get('content') in {'product', 'product.item'}:
            values.append(meta.get('content'))
    return clean_images(values, product_url)
