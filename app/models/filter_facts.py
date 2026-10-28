"""Conservative facts from the source's own product description."""
import re
from bs4 import BeautifulSoup


def description_facts(html: str) -> dict:
    text = BeautifulSoup(html or '', 'html.parser').get_text(' ', strip=True).casefold().replace('ё', 'е')
    facts = {}
    level = re.search(r'(?:уровень\s+сложности|сложность|уровень\s+пошива)\s*[:—\-]?\s*(1(?:\s*(?:из|/)\s*[345])?|начальн\w*|прост\w*|легк\w*|средн\w*|сложн\w*|[2345])\b', text)
    if level:
        facts['is_beginner'] = bool(re.match(r'1\b|начальн|прост|легк', level[1]))
        facts['difficulty'] = level[0]
    elif re.search(r'(?:подходит|подойдет|рекомендуется|выкройка|модель)\s+(?:также\s+)?для\s+начинающ', text) and not re.search(r'не\s+(?:подходит|подойдет|рекомендуется)\s+для\s+начинающ', text):
        facts['is_beginner'] = True
    # Avoid "дублерин на трикотажной основе" and explicit negative recommendations.
    for sentence in re.split(r'[.!?\n]', text):
        if any(word in sentence for word in ('дублерин', 'клеев', 'подклад')):
            continue
        if re.search(r'не\s+(?:рекоменд|подход|использ)|не\s+следует|избег', sentence):
            continue
        if re.search(r'(?:выкройка\s+)?трикотажн\w*\s+(?:плать|юбк|брюк|топ|свитшот|худи|джемпер|футболк)|(?:платье|юбка|брюки|модель|изделие)\s+из\s+трикотаж|(?:подойдут|подойдет|рекомендуются|рекомендуется|выбирать|использовать)\s+(?:\w+[, ]+){0,6}трикотажн', sentence):
            facts['is_knit'] = True
            break
    return facts
