# PatternHub Bot

Локальный MVP Telegram-бота-агрегатора выкроек. Бот работает через long polling,
отвечает `Test` на команду `/start` и один раз сохраняет `chat_id` первого
тестового пользователя в SQLite. Повторные запуски и команды `/start` от других
пользователей выбранный `chat_id` не меняют.

Основа общего каталога рассчитана на VikiSews, Grasser, HelperSew, Studio
Yusupova и Sew It Now. Сейчас подключён только HTML-provider VikiSews; остальные
источники зарегистрированы в БД, но отключены и не имеют parser-реализаций.

## Требования

- Python 3.10–3.14
- Telegram-бот и его токен, полученный у [@BotFather](https://t.me/BotFather)

## Установка и запуск

Создайте и активируйте виртуальное окружение:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Установите зависимости:

```bash
pip install -r requirements.txt
```

Создайте локальный файл настроек:

```bash
cp .env.example .env
```

В PowerShell вместо `cp` можно выполнить:

```powershell
Copy-Item .env.example .env
```

Вставьте токен в `.env`:

```env
BOT_TOKEN=ваш_токен_от_BotFather
```

Запустите бота:

```bash
python -m app
```

Затем откройте бота в Telegram и отправьте `/start`. Бот ответит `Test`.
Первый `chat_id` сохранится в `data/patternhub.sqlite3` и переживёт перезапуск.

## Каталог

Запустить синхронизацию VikiSews:

```bash
python -m app parse vikisews
```

Provider читает публичные серверные HTML-страницы каталога с задержкой между
запросами. Закрытый сайтом `/api/` не используется. Повторный запуск обновляет
существующие позиции по паре `source + source_product_id`, а при отсутствии ID —
по `source + product_url`; дубли не создаются.

Статистика каталога:

```bash
python -m app catalog-stats
```

Просмотр нескольких товаров:

```bash
python -m app products --limit 10
```

Каталог и настройки находятся в одной SQLite БД `data/patternhub.sqlite3`.
Основные товарные данные хранятся колонками таблицы `products`; списки размеров
и ростов хранятся как JSON-текст. Из каталога VikiSews сейчас собираются ID
источника, название, бренд, категория, URL, изображение, цена, старая цена,
валюта и признаки скидки/бесплатности. Размеры, рост, сложность и описание
доступны на детальных страницах, но массово не запрашиваются, чтобы не создавать
сотни дополнительных запросов.

## Управление тестовым chat_id

Посмотреть выбранный идентификатор:

```bash
python -m app show-chat-id
```

Сбросить его, чтобы следующий `/start` выбрал нового пользователя:

```bash
python -m app reset-chat-id
```

Установить идентификатор вручную:

```bash
python -m app set-chat-id 123456789
```

Перед управляющими командами токен не требуется, но `.env` загружается, если он
есть. Путь к базе можно изменить параметром `DATABASE_PATH` в `.env`.

## Проверки

```bash
python -m unittest discover -s tests -v
```

## Структура

```text
app/
├── __main__.py          # CLI и точка входа
├── bot.py               # запуск long polling
├── config.py            # загрузка .env
├── database.py          # подключение и схема SQLite
├── models/
│   └── product.py       # общие ParsedProduct/Product и статистика
├── providers/
│   ├── base.py          # общий контракт источника
│   ├── registry.py      # реестр подключённых providers
│   └── vikisews.py      # единственный source-specific модуль
├── handlers/
│   └── start.py         # обработчик /start
├── repositories/
│   ├── products.py      # общий upsert и чтение каталога
│   └── settings.py      # хранение выбранного chat_id
└── services/
    ├── catalog.py       # общая синхронизация любого provider
    └── test_chat.py     # правило «первый пользователь побеждает»
tests/
├── fixtures/            # сохранённые HTML-примеры, без живых запросов
└── test_*.py
```

Следующий этап: подключить каталог к Telegram UI. Остальные источники следует
добавлять позднее отдельными provider-модулями через тот же `ParsedProduct`,
`ProductRepository` и `CatalogService`.
