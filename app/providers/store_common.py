"""Shared normalization for audited public storefront adapters."""
import json
import html
import re
from urllib.parse import urlsplit
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup

from app.models.audience import normalize_audience
from app.models.categories import CATEGORIES, normalize_category
from app.models.product import ParsedProduct
from app.providers.gallery import clean_images


CATEGORY_NAMES = {c.name for c in CATEGORIES}


def plain(value) -> str:
    text = str(value or '')
    return BeautifulSoup(text, 'html.parser').get_text(' ', strip=True) if '<' in text else html.unescape(text).strip()


def money(value, *, minor_unit=0):
    if value is None or isinstance(value, bool) or not str(value).strip():
        return None
    text = re.sub(r'[^0-9,.-]', '', str(value)).replace(',', '.')
    try:
        number = Decimal(text) / (Decimal(10) ** minor_unit)
        return number if number.is_finite() and number >= 0 else None
    except InvalidOperation:
        return None


def category_for(name, categories=(), specialization='general'):
    # Unknown source labels must not create thousands of one-product categories.
    if specialization == 'lingerie':
        return 'Бельё и домашняя одежда'
    if re.search(r'базов\w*\s+(?:основ|лекал)', plain(name), re.I):
        return 'Базовые лекала'
    for raw in [name, *categories]:
        category = normalize_category(plain(raw))
        if category in CATEGORY_NAMES - {'Другое','Базовые лекала','Подарочные сертификаты'}:
            return category
    if specialization == 'bags':
        return 'Аксессуары'
    return 'Другое'


def audience_for(categories, specialization):
    values = {normalize_audience(plain(value)) for value in categories} - {None}
    text = ' '.join(plain(value).casefold() for value in categories)
    for pattern, audience in [(r'\b(?:женск|женщин)', 'women'), (r'\b(?:мужск|мужчин)', 'men'),
                              (r'\b(?:детск|дети|девоч|мальчик|подрост)', 'kids'), (r'\bунисекс\b','unisex')]:
        if re.search(pattern, text):
            values.add(audience)
    if 'unisex' in values:
        return 'unisex'
    if len(values) == 1:
        return values.pop()
    # A supplier's specialization is not evidence about every individual model.
    return None


def is_pattern(name, categories=()):
    title = plain(name).casefold().replace('ё','е')
    toy = re.search(r'\b(?:игрушк|кукл)\w*', title)
    if toy:
        garment_before = re.search(r'плать|брюк|юбк|рубаш|блуз|свит|футбол|сумк|сумоч|рюкзак|кошел|шапк|берет|трус|бюст',title[:toy.start()])
        if not garment_before or re.search(r'(?:для|на)\s+кукл',title):
            return False
    excluded = (r'подарочн\w*\s+сертификат|сертификат\s+на|'
                r'^\s*(?:видеокурс|онлайн.курс|курс\b|мастер.класс|журнал\b|книга\b|'
                r'ткань\b|фурнитура\b|резинка\b|молния\b|набор\s+фурнитуры|'
                r'кукла\b|игрушка\b|пошив\s+на\s+заказ|подарочн\w*\s+карта|'
                r'запись\b|вебинар\b|интенсив\b|практикум\b|консультац\w*|подписк\w*|'
                r'видеоурок\w*|видеоинструкц\w*|участие\b|'
                r'печать\s+(?:выкро|лекал)|тестов\w*\s+товар)')
    if re.search(excluded, title):
        return False
    sections = ' '.join(plain(c).casefold() for c in categories)
    if re.search(r'ткани|фурнитура|оборудован|сертификат|видеокурс|мастер.класс|обучение', sections) and not re.search(r'выкрой|лекал', title):
        return False
    return bool(title)


def product_from_values(config, *, name, url, key=None, price=None, old_price=None,
                        currency=None, categories=(), images=(), description=None,
                        available=True, sizes=None, heights=None):
    name = plain(name)
    if not is_pattern(name, categories):
        return None
    images = clean_images(images, url)
    return ParsedProduct(source=config['source'], source_product_id=str(key) if key else None,
        name=name, brand=config['display_name'], product_url=url,
        category=category_for(name, categories, config.get('specialization','general')),
        subcategory=' / '.join(plain(c) for c in categories) or None,
        audience=audience_for(categories, config.get('specialization','general')),
        price=price, old_price=old_price, currency=currency,
        is_free=price == 0 or bool(re.search(r'\bбесплатно\b', name.casefold())),
        image_url=images[0] if images else None, image_urls=images or None,
        description=plain(description)[:6000] or None,
        sizes=tuple(sizes) if sizes else None, heights=tuple(heights) if heights else None,
        is_available=available).normalized()


def embedded_tilda_product(text):
    for match in re.finditer(r'\bvar\s+product\s*=\s*(?=\{)', text):
        try:
            value, _ = json.JSONDecoder().raw_decode(text[match.end():])
        except ValueError:
            continue
        if isinstance(value, dict) and value.get('uid'):
            return value
    return None


def tilda_product(config, text, url):
    soup = BeautifulSoup(text, 'html.parser')
    if re.match(r'^/(?:courses?|webinar|members)(?:[a-z0-9_/-]|$)', urlsplit(url).path, re.I):
        return None
    heading = soup.select_one('meta[property="og:title"]')
    heading = heading.get('content','') if heading else soup.title.get_text(' ',strip=True) if soup.title else ''
    if heading.casefold().strip() in {'members area','личный кабинет','зона участников'}:
        return None  # Explicit login-only content; never attempt to access it.
    if heading and not is_pattern(heading):
        return None
    data = embedded_tilda_product(text)
    if data:
        gallery = data.get('gallery') or []
        if isinstance(gallery, str):
            gallery = json.loads(gallery)
        sizes, heights = [], []
        options = data.get('json_options') or []
        if isinstance(options, str):
            options = json.loads(options)
        for option in options:
            label = str(option.get('title') or '').casefold()
            if 'размер' in label:
                sizes.extend(str(v) for v in option.get('values', []) if isinstance(v,(str,int)))
            elif 'рост' in label:
                heights.extend(str(v) for v in option.get('values', []) if isinstance(v,(str,int)))
        return product_from_values(config, key=data['uid'], name=data.get('title'), url=url,
            price=money(data.get('price')), old_price=money(data.get('priceold')),
            currency=tilda_currency(soup, config),
            images=[g.get('img') for g in gallery if isinstance(g,dict)],
            description=data.get('text') or data.get('descr'), sizes=sizes, heights=heights,
            available=str(data.get('quantity','')).strip() != '0')
    root = soup.select_one('.js-store-product, [itemscope][itemtype$="/Product"]')
    if root is None:
        own_title = soup.select_one('h1.js-product-name')
        if own_title:
            root = own_title.find_parent(class_='js-product') or own_title.find_parent(attrs={'data-record-type':True})
    title = root.select_one('.js-product-name, [itemprop="name"]') if root else None
    if root is None or title is None:
        canonical = soup.select_one('link[rel="canonical"][href]')
        cover = soup.select_one('meta[property="og:image"]')
        # A few legacy public product pages expose only their own SEO card.
        # Accept a recognizable garment/accessory, not a generic site homepage.
        if (canonical and cover and urlsplit(canonical['href']).path.rstrip('/') == urlsplit(url).path.rstrip('/')
                and category_for(heading) != 'Другое'):
            description = soup.select_one('meta[property="og:description"]')
            return product_from_values(config, name=heading, url=url, images=[cover.get('content')],
                description=description.get('content') if description else None)
        raise ValueError('Tilda product markup missing')
    price_node = root.select_one('.js-product-price')
    old_node = root.select_one('.js-store-prod-price-old-val')
    images = [n.get('data-original') or n.get('data-img-zoom-url') or n.get('src')
              for n in root.select('.t-slds__bgimg, .t-slds__img')]
    if not any(images):
        cover = soup.select_one('meta[property="og:image"]')
        images = [cover.get('content')] if cover else []
    return product_from_values(config, key=root.get('data-product-gen-uid') or root.get('data-product-uid'),
        name=title.get('content') or title.get_text(' ',strip=True), url=url,
        price=money(price_node.get('data-product-price-def') or price_node.get_text()) if price_node else None,
        old_price=money(old_node.get_text()) if old_node else None,
        currency=tilda_currency(soup, config), images=images,
        description=root.select_one('.js-store-prod-all-text') or root.select_one('[field="descr"]'))


def tilda_currency(soup, config):
    node = soup.select_one('[itemprop="priceCurrency"]')
    if node and node.get('content'):
        return node['content']
    node = soup.select_one('.js-product-price-currency, .t-store__prod-popup__price-currency')
    symbol = node.get_text(strip=True).casefold() if node else ''
    return {'₽':'RUB','руб.':'RUB','руб':'RUB','р.':'RUB','р':'RUB','€':'EUR','$':'USD','br':'BYN'}.get(symbol) or config.get('currency')
