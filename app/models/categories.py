from __future__ import annotations

import re
import zlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CategoryDefinition:
    code: str
    name: str
    aliases: tuple[str, ...]


CATEGORIES: tuple[CategoryDefinition, ...] = (
    CategoryDefinition(
        "dresses",
        "Платья",
        (
            "Платья",
            "Платья и сарафаны",
            "Выкройки платьев и сарафанов",
            "Платье",
            "Сарафан",
            "Платья Лето",
            "Платья Весна/Осень",
            "Платья нарядные",
            "Платья из трикотажа",
        ),
    ),
    CategoryDefinition(
        "pants",
        "Брюки и шорты",
        (
            "Брюки",
            "Брюки и шорты",
            "Брюки, шорты, комбинезоны",
            "Брюки, шорты",
            "Брюки, джинсы, шорты",
            "Легинсы и велосипедки",
            "Лосины",
            "Джинсы",
            "Шорты",
            "Брюки из трикотажа",
            "Легинсы",
            "Юбка-брюки",
        ),
    ),
    CategoryDefinition("skirts", "Юбки", ("Юбки", "Юбка")),
    CategoryDefinition(
        "jackets",
        "Жакеты и жилеты",
        (
            "Жакеты",
            "Жилеты",
            "Жакеты и жилеты",
            "Жакеты и кардиганы",
            "Жакеты, кардиганы, жилеты",
            "Жакет",
            "Жилет",
        ),
    ),
    CategoryDefinition(
        "outerwear",
        "Верхняя одежда",
        (
            "Верхняя одежда",
            "Выкройки верхней одежды",
            "Пальто и жакеты",
            "Верхняя одежда для мужчин",
            "Пальто",
            "Куртка",
            "Ветровка",
            "Бомбер",
            "Бомберы",
            "Пуховики",
            "Дубленка",
            "Шуба",
            "Бушлат",
            "Плащ",
            "Тренч",
            "Тренчкоты",
        ),
    ),
    CategoryDefinition(
        "shirts_tops",
        "Рубашки, блузки и топы",
        (
            "Рубашки, блузки и топы",
            "Рубашки, блузки, корсажи",
            "Блузки и рубашки",
            "Рубашки и блузы",
            "Блузка",
            "Рубашка",
            "Сорочка",
            "Топ",
            "Блузы",
            "Боди",
            "Майка",
            "Майки и топы",
            "Водолазки, лонгсливы, боди, футболки, топы, майки",
            "Водолазки и лонгсливы",
        ),
    ),
    CategoryDefinition(
        "hoodies_sweatshirts",
        "Худи, футболки и лонгсливы",
        (
            "Худи, футболки и лонгсливы",
            "Свитшоты, худи, толстовки, свитеры, джемперы, кардиганы",
            "Свитшоты, худи и свитеры",
            "Свитшоты, толстовки, худи",
            "Худи и свитшоты",
            "Футболки и лонгсливы",
            "Футболки и топы",
            "Свитер",
            "Свитшот",
            "Толстовка",
            "Худи",
            "Футболка",
            "Лонгслив",
            "Джемпер",
            "Кардиган",
            "Свитшоты/лонгсливы/футболки",
        ),
    ),
    CategoryDefinition("jumpsuits", "Комбинезоны", ("Комбинезоны", "Комбинезон")),
    CategoryDefinition(
        "accessories",
        "Аксессуары",
        (
            "Аксессуары",
            "Выкройки аксессуаров",
            "Выкройки головных уборов",
            "Женские аксессуары",
            "Головные уборы",
            "Балаклава",
            "Тапки",
            "Прочее",
        ),
    ),
    CategoryDefinition(
        "lingerie_loungewear",
        "Бельё и домашняя одежда",
        (
            "Бельё и домашняя одежда",
            "Нижнее белье и купальники",
            "Нижнее бельё и купальники",
            "Домашняя одежда",
            "Купальники",
            "Лифы",
            "Трусы",
        ),
    ),
    CategoryDefinition(
        "base_patterns",
        "Базовые лекала",
        ("Базовые лекала для моделирования и шаблоны", "Базовые лекала"),
    ),
    CategoryDefinition(
        "gift_certificates",
        "Подарочные сертификаты",
        ("Подарочные сертификаты",),
    ),
    CategoryDefinition("other", "Другое", ("Другое",)),
)


def category_code(category: str) -> str:
    normalized = normalize_category(category) or category
    for definition in CATEGORIES:
        if definition.name == normalized:
            return definition.code
    return f"c{zlib.crc32(normalized.encode('utf-8')):08x}"


def category_name_by_code(code: str) -> str | None:
    for definition in CATEGORIES:
        if definition.code == code:
            return definition.name
    return None


def normalize_category(category: str | None) -> str | None:
    if category is None:
        return None
    cleaned = _clean(category)
    if not cleaned:
        return None
    if cleaned in {"мужские", "мужские выкройки", "женские", "детские", "детские выкройки"}:
        return "Другое"
    for definition in CATEGORIES:
        if cleaned == _clean(definition.name):
            return definition.name
        if any(cleaned == _clean(alias) for alias in definition.aliases):
            return definition.name
    return _infer_from_text(cleaned) or category.strip()


def _infer_from_text(value: str) -> str | None:
    checks: tuple[tuple[tuple[str, ...], str], ...] = (
        (("сарафан", "плать"), "Платья"),
        (("юбка-брюк", "брюк", "шорт", "джинс", "велосипедк", "лосин", "леггинс", "легинс"), "Брюки и шорты"),
        (("юбк",), "Юбки"),
        (("жакет", "жилет", "пиджак"), "Жакеты и жилеты"),
        (("пальто", "куртк", "ветровк", "бомбер", "дубленк", "шуб", "бушлат", "плащ", "тренч", "парк", "накидк"), "Верхняя одежда"),
        (("блузк", "рубашк", "сорочк", "майк", "топ", "боди", "водолазк"), "Рубашки, блузки и топы"),
        (("свитер", "свитшот", "толстовк", "худи", "футболк", "лонгслив", "джемпер", "кардиган"), "Худи, футболки и лонгсливы"),
        (("комбинезон",), "Комбинезоны"),
        (("бель", "купальник", "бюстгальтер", "бралетт", "трус", "плавк", "пеньюар", "халат", "кимоно", "лиф бикини", "туник"), "Бельё и домашняя одежда"),
        (("шапк", "шляп", "шлем", "балаклав", "бейсболк", "панам", "картуз", "капор", "косынк", "воротник", "капюшон", "манишк", "галстук", "маск", "рукавиц", "рюкзак", "чехол", "органайзер", "пояс", "рюш", "баск", "шарф", "тапк", "трафарет", "нагрудник"), "Аксессуары"),
        (("шаблон", "лекал"), "Базовые лекала"),
        (("сертификат",), "Подарочные сертификаты"),
        (("выкройк",), "Другое"),
    )
    for markers, category in checks:
        if any(marker in value for marker in markers):
            return category
    return None


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold().replace("ё", "е")
