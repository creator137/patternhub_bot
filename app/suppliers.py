"""Audited supplier directory, independent of product import implementation."""
from functools import lru_cache
import json
from pathlib import Path


SPECIALIZATIONS = {
    'general':'Выкройки одежды', 'lingerie':'Нижнее бельё', 'kids':'Детские выкройки',
    'bags':'Сумки', 'pets':'Для животных',
}


@lru_cache(maxsize=1)
def supplier_definitions():
    return tuple(json.loads((Path(__file__).parent / 'providers' / 'suppliers.json').read_text()))


def supplier_definition(source):
    return next((dict(item) for item in supplier_definitions() if item['source'] == source), None)
