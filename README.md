# PatternHub Bot

Локальный MVP Telegram-бота-агрегатора выкроек. Бот работает через long polling,
показывает каталог на команду `/start` и один раз сохраняет `chat_id` первого
тестового пользователя в SQLite. Повторные запуски и команды `/start` от других
пользователей выбранный `chat_id` не меняют.

Основа общего каталога рассчитана на VikiSews, Grasser, HelperSew, Studio
Yusupova и SewItNow. Все пять источников подключены как отдельные providers и
сохраняют товары в единую таблицу каталога.

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

Затем откройте бота в Telegram и отправьте `/start`. Бот покажет главное меню.
Первый `chat_id` сохранится в `data/patternhub.sqlite3` и переживёт перезапуск.

## Каталог

Запустить синхронизацию источника:

```bash
python -m app parse vikisews
python -m app parse grasser
python -m app parse helpersew
python -m app parse studio_yusupova
python -m app parse sewitnow
```

Providers читают публичные серверные HTML/JSON-данные каталога. Закрытые сайтом
служебные endpoints не используются. Повторный запуск обновляет существующие
позиции по паре `source + source_product_id`, а при отсутствии ID — по
`source + product_url`; дубли не создаются. Если provider получил полный
snapshot источника, товары, исчезнувшие из текущего полного импорта,
помечаются `is_available = False` и пропадают из пользовательского каталога без
удаления из SQLite.

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
и ростов хранятся как JSON-текст. Из каталогов сейчас собираются ID источника,
название, бренд, нормализованная общая категория, URL, изображение, цена, старая
цена, валюта, аудитория, доступность и признаки скидки/бесплатности/новинки.
Размеры, рост, сложность и описание доступны на детальных страницах. Для
источников, где быстрый listing не содержит надежных признаков, можно запускать
отдельное обогащение уже сохраненных товаров:

```bash
python -m app enrich-details vikisews
```

Оно не заменяет обычный импорт и не запускает lifecycle reconciliation; это
maintenance-команда для дозаписи detail-признаков вроде трикотажа. Результаты
сохраняются пачками, размер пачки можно менять через `--batch-size`.

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
│   ├── categories.py    # общий справочник нормализации категорий
│   └── product.py       # общие ParsedProduct/Product и статистика
├── providers/
│   ├── base.py          # общий контракт источника
│   ├── registry.py      # реестр подключённых providers
│   ├── grasser.py       # source-specific provider Grasser
│   ├── helpersew.py     # source-specific provider HelperSew
│   ├── sewitnow.py      # source-specific provider SewItNow
│   ├── studio_yusupova.py
│   └── vikisews.py      # source-specific provider VikiSews
├── handlers/
│   ├── catalog.py       # Telegram UI общего каталога
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

Новые источники следует добавлять отдельными provider-модулями через тот же
`ParsedProduct`, `ProductRepository` и `CatalogService`.
