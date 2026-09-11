from __future__ import annotations

import re


AUDIENCES = ("women", "men", "kids", "unisex")
AUDIENCE_TITLES = {
    "women": "👗 Женские",
    "men": "👔 Мужские",
    "kids": "🧒 Детские",
    "unisex": "👕 Унисекс",
}


def normalize_audience(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _clean(value)
    aliases = {
        "women": {"women", "woman", "female", "zhenskie", "женские", "женщины"},
        "men": {"men", "man", "male", "muzhskie", "мужские", "мужчины"},
        "kids": {
            "kids",
            "children",
            "child",
            "detskie",
            "podrostki",
            "детские",
            "дети",
            "подростки",
        },
        "unisex": {"unisex", "унисекс"},
    }
    for audience, values in aliases.items():
        if cleaned in values:
            return audience
    return None


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold().replace("ё", "е")
