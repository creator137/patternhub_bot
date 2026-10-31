# Сверка с сервером, 31 октября 2026

Рабочий проект нового бота расположен в `/opt/allsewpattern`.
Сервисы `allsewpattern-bot` и `allsewpattern-web` запущены из этой папки.
Файл `REVISION` указывает `f7a6e37cd9f527d74fe7136d837979739d68bdae`.
Эта ревизия уже присутствовала в GitHub `main` до сверки.

## Что сохранено

Ветка [archive/server-20261031](https://github.com/creator137/patternhub_bot/tree/archive/server-20261031/server-snapshots/2026-10-31),
коммит `e9a4f6c`, содержит:

- `source.tar.gz`: 148 файлов исходников, шаблонов конфигурации и тестов сервера;
- `active-build.tar.gz`: фактически используемые index.html и связанные с ним JS/CSS.

SHA-256 архивов:

```text
source.tar.gz       277048d72ca9a8a67d146338176e55082169ae5b39c157641f2de5d6eb1e178d
active-build.tar.gz 8fbd2910c65f0ac3ec3ac01a10900d08d8a981d7c7274d41d24b552b382e17e4
```

Секретный `.env`, рабочая база, data/media, окружения, кеши и временные релизы
в архивы не включены. Проверка типовых токенов бота и закрытых ключей в исходниках
совпадений не выявила. SSH использовался для чтения; сервер не обновлялся.

## Результат сравнения

Из 148 файлов 134 совпадают с Git `f7a6e37`, включая все 69 файлов backend
в `app/` (при сравнении текста нормализованы CRLF/LF). Новых исходников,
отсутствующих в Git, на сервере не обнаружено. Различаются 14 файлов:

```text
.env.example
frontend/package.json
frontend/package-lock.json
frontend/src/App.vue
frontend/src/Admin.vue
frontend/src/Suppliers.vue
frontend/src/api.ts
frontend/e2e/catalog.spec.ts
frontend/e2e/live-filters.spec.ts
frontend/e2e/section-navigation.spec.ts
tests/test_suppliers.py
tests/test_start_handler.py
tests/test_grasser_provider.py
tests/test_web.py
```

Ещё 27 файлов из Git на сервере отсутствуют — дополнительные frontend-модули,
тесты, fixtures и лицензии шрифтов. Это неполная копия репозитория для выкладки.

Серверный `frontend/dist/index.html` подключает `index-BrjWqt7j.js` и
`index-CUC81lh-.css`. В активном JS есть статистика, смена аватарки, кнопка
«Наверх» и название раздела «Производители». Свободно лежащие Vue-исходники
на том же сервере этих функций не содержат и используют старое «Поставщики».
Git main содержит соответствующие новые модули и функции.

Поэтому слепая замена main файлами серверного `frontend/src` убрала бы функции
работающей сборки. Main сохранён как поддерживаемый исходный код; точное состояние
сервера независимо сохранено в архивной ветке. Побайтовая идентичность локальной
пересборки активному JS сервера не утверждается: имена полученных assets различаются.
При следующей выкладке следует доставлять исходники и сборку из одного checkout.

## Локальная проверка

Рабочая папка `D:\projects\patternhub_bot` переведена на актуальный main.
Скачанная копия файлов оставлена отдельно в `D:\projects\patternhub-server-sync-20261031`.

- `npm ci` и `npm run build`: успешно, TypeScript и Vite проходят.
- `python -X utf8 -m unittest discover -s tests`: 315 тестов, OK, 57.006 секунды.
- На Windows нужен UTF-8 mode: часть существующих fixtures читается без явного
  encoding; при системной CP1251 исходный прогон выдавал ошибки декодирования.
- `npm ci` сообщает о трёх moderate advisories в текущем lockfile; зависимости
  в рамках сверки с сервером не обновлялись.
