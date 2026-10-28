# Поставщики: завершение интеграции 28.10.2026

Из согласованного XLSX выделены 90 уникальных адресов. **88 включённых поставщиков имеют товары в общей БД и рабочий provider**. Два перепрофилированных домена отключены. XLSX, ТЗ, пароли и токены в Git не включены.

## Production

На VPS: **54,500 записей; 54,395 available; 105 unavailable**. Публичная проверка `/api/suppliers`: 88/88 с товарами. `integrity_check=ok`, нарушений внешних ключей нет. Перед миграцией создана SQLite backup.

Скидки: 13459; подтверждённые новые по дате: 1096; бесплатные: 987; для начинающих: 991; трикотаж: 2352; непустых категорий: 13; без цены: 25347; без URL фото: 1.

Аудитория: women 15935; men 1607; kids 6158; unisex 50; unknown 30645. Неизвестная аудитория не превращается в women. Технический счётчик не показывается в UI.

## Импорт и идентификация

Дополнительно подключены 46 оставшихся каталогов: 45 полных проверенных snapshot и EasySew с неполным snapshot. Новые полные выгрузки: 40 736 записей. Повторный импорт всех 45: **Added 0, Updated 40 736, Errors 0**. Дополнительное уточнение аудитории также Added 0.

EasySew: Found 219, Added 219 при первом импорте; при повторном Added 0 / Updated 219. В текущих карточках подтверждены 66 удалённых detail URL, их записи unavailable. Доступны 153. Complete=False, Errors=72: пять страниц пагинации возвращают 404, ещё 67 detail не читаются (66 HTTP404 и одна пустая HTTP200). Reconciliation отсутствующих товаров не запускается. Длительности реальных серверных прогонов: 31,12 и 30,57 секунды.

У Рыбчинской рубашка Kimberly и брюки Kimberly имеют разные Tilda UID, но один URL страницы комплекта. Общая модель теперь использует source + source_product_id; уникальность source + URL применяется только как fallback без ID. Миграция транзакционно сохраняет IDs, дополнительные колонки, индексы, AUTOINCREMENT, избранное, overrides и ссылки медиа. Неполные snapshots по-прежнему не могут массово скрыть товары.

## Протоколы

- WooCommerce: публичный Store API с проверкой totals, уникальных IDs и всех страниц; page_size настраивается для нестабильных серверов. Woo HTML/XML используется там, где API недоступен.
- WordPress-блоги: публичные posts JSON и массовое получение featured_media. Обложки восстановлены у 9 167 записей Vikroim и 4 207 Sew Lane. Документы выкроек не скачиваются. Большие обходы имеют checkpoint и фиксированную границу публикации.
- Tilda: публичный магазинный JSON, HTML/embedded JSON, sitemap-store либо старый статический каталог. JSON с text/html Content-Type не ошибочно отбрасывается. Сверяются part UID, totals, pagination, дубли. Курсы и выпуски не выдаются за отдельные модели.
- OpenCart: публичные каталоги/sitemap и product HTML. Bitrix: sitemap или реальные разделы и PAGEN; сортировочные параметры нормализуются, пустые категории не становятся товарами.
- PatternEasy: Laravel paginator, 604 позиции (599 available). Цена берётся из priceInfo, вложенный нулевой placeholder не означает бесплатную выкройку.
- Шкатулка: публичный read-only POST формы каталога до реального пустого ответа; 1 282 модели. Повтор страницы или изменение разметки означает incomplete.
- Taplink: SSR + публичный load-more по cursor + собственные product pages. Выгружены все 17, включая позиции за пределами первых 12.
- Leko/Latelye: реальные каталожные номера, все разделы/страницы, объединение по ID; регистрация, заказ, мерки и PDF не запрашиваются. Превью не путаются с баннерами.
- Burda: 536 страниц, 12 839 моделей, 539 запросов, 2 retries, 2 188,71 секунды (36,5 минуты). Максимум три параллельных запроса; каждый проверенный ответ сохраняется сжато. Номер текущей страницы, число страниц, IDs и дубли проверяются. Реальная массовая акция подтверждена HTML: 270 ₽ → 99 ₽, скидки не выдуманы.
- Marymake: собственный ручной каталог, 16 уникальных моделей. Дубли вариантов Amber с/без видео объединяются по публичному URL; 600/3000 ₽ не превращаются в ложную скидку. Gallery URL берётся по реальному правилу Vigbo 1000-имя, preview URLs нормализуются.

Для ранее подтверждённых владельцем разрешений добавлены точные исключения robots только на публичные read-only маршруты витрин. По умолчанию правила строгие; account/admin/cart, закрытые API, аутентификация и скачивание файлов выкроек не используются. Один HTTP client на источник, ограниченная параллельность, timeout/retry сетевых и временных серверных ошибок. Повторные 404 не ретраятся.

## Фото и интерфейс

Все источники поступают через ParsedProduct → ProductRepository/CatalogService → Product. Telegram handlers не менялись и не импортируют providers. Бренды остаются по алфавиту. Фильтры поиска, бренда, типа изделия, аудитории, скидок, бесплатных/1 ₽, для начинающих, трикотажа и сортировки сохранены. Отдельный фильтр «За последние 60 дней» и техническая надпись unknown audience не возвращались.

Крупные оригиналы WooCommerce заменяются опубликованными srcset-версиями подходящего размера, без угадывания URL и без снижения защиты от чрезмерных размеров. Так исправлена обложка «Асимметричная юбка Ницца» Loko: оригинал превышал 25 MP. Для обложки есть ограниченный переход к другим реальным фото того же товара, общий кэш/проверки URL/дедупликация параллельных запросов сохранены. Лимит media-кэша 768 MB, свободно больше 9 GB.

Проверка после подключения всех поставщиков: **174/176** выбранных входных обложек успешно подготовлены. Два сбоя — EasySew: «Анорак детский 28-92» (42942) и «Анорак подростковый 38-158» (42616). Проверенные исходные URLs фотографий возвращают HTTP404 и на самом сайте. Это ограничение источника, а не потеря URL парсером. Проверка выборочная, не гарантия 100% всех фото. Ещё у одной старой позиции Laforme (0104) Store API вообще не отдаёт изображение; собственная detail-страница показывает Woo placeholder.

## Реальные доступные каталоги

| Поставщик | URL | Адаптер | Available | Статус нового обхода |
|---|---|---|---:|---|
| alena kochkareva | https://alenakochkareva.ru | tilda_sitemap | 35 | Ранее подключён |
| all-sew | https://all-sew.ru | vigbo | 199 | Ранее подключён |
| angela-molodets.ru | https://angela-molodets.ru | vigbo | 8 | Ранее подключён |
| Ansews | https://ansews.ru | ansews | 211 | Полный |
| aspatterns | https://aspatterns.ru | taplink | 17 | Полный |
| aurorasew.ru | https://aurorasew.ru | tilda_sitemap | 3 | Ранее подключён |
| baysews | https://baysews.ru | tilda_sitemap | 96 | Ранее подключён |
| belenochka | https://belenochka.ru | wordpress_sitemap | 56 | Полный |
| Dress you | https://dress-layout.ru | tilda_sitemap | 22 | Ранее подключён |
| Easy sews | https://easysew.info | easysew | 153 | Неполный: сайт отдаёт 404 |
| Elenapatternstudio | https://elenapatternstudio.ru | wordpress_sitemap | 103 | Полный |
| fancysmth | https://fancysmth.com | tilda_extended | 51 | Полный |
| Grasser | https://grasser.ru | existing | 1319 | Ранее подключён |
| HelperSew | https://helpersew.com | existing | 593 | Ранее подключён |
| ivahm-patterns | https://ivahm-patterns.ru | vigbo | 111 | Ранее подключён |
| juliastefanello | https://juliastefanello.com | tilda_api | 22 | Полный |
| kapsulestore | https://kapsulestore.ru | bitrix_catalog | 9 | Полный |
| Kids Patterns | https://kids-patterns.ru | vigbo | 36 | Ранее подключён |
| LaForme | https://laforme.ru | woo_store | 402 | Полный |
| laviedelalingerie | https://laviedelalingerie-shop.com | woo_store | 43 | Ранее подключён |
| Lebovi выкройки | https://lebovi.by | woo_store | 11 | Ранее подключён |
| lekalo-kids | https://lekalo-kids.ru | vigbo | 120 | Ранее подключён |
| leko mail | https://leko-mail.ru | lekala_legacy | 3226 | Полный |
| lirapattern.ru | https://lirapattern.ru | woo_store | 85 | Ранее подключён |
| Loko pattern | https://lokopatterns.ru | loko | 65 | Полный |
| lspatterns.ru | https://lspatterns.ru | bitrix_catalog | 233 | Полный |
| lubimchiki-style.ru | https://lubimchiki-style.ru | tilda_sitemap | 181 | Ранее подключён |
| Marymake | https://marymake.ru | marymake | 16 | Полный |
| masterskayakorol.ru | https://masterskayakorol.ru | tilda_api | 60 | Полный |
| mialine | https://mialine.ru | tilda_sitemap | 106 | Ранее подключён |
| Mint mom | https://mintmoon.ru | vigbo | 53 | Ранее подключён |
| Modety | https://modety.ru | virtuemart | 160 | Полный |
| morozovamarie.ru | https://morozovamarie.ru | vigbo | 17 | Ранее подключён |
| neovima.com | https://neovima.com | woo_html | 5758 | Ранее подключён |
| oldem-sew.ru | https://oldem-sew.ru | woo_store | 117 | Ранее подключён |
| One Pattern | https://helenpatterns.ru | woo_store | 69 | Полный |
| onesews.com | https://onesews.com | woo_store | 76 | Ранее подключён |
| PA2TERN | https://pa2tern.com | tilda_sitemap | 54 | Ранее подключён |
| Perchik Patterns | https://perchikpatterns.ru | vigbo | 73 | Ранее подключён |
| SELFTAILOR | https://selftailor.ru | wordpress_sitemap | 37 | Полный |
| settembre.ru | https://settembre.ru | vigbo | 11 | Полный |
| sew-light.com | https://sew-light.com | woo_store | 84 | Ранее подключён |
| sew-line | https://sew-lane.ru | wordpress_posts | 4207 | Полный |
| SewFreedom | https://sewfreedom.ru | independent_html | 211 | Полный |
| SewItNow | https://sewitnow.ru | existing | 534 | Ранее подключён |
| SewLevel | https://sewlevel.ru | independent_html | 150 | Полный |
| shape in space | https://shapeinspace.ru | shape | 18 | Полный |
| shvej-shop | https://shvej-shop.by | woo_store | 86 | Полный |
| shveyaholic.ru | https://shveyaholic.ru | tilda_sitemap | 11 | Ранее подключён |
| starkova-art.ru | https://starkova-art.ru | tilda_sitemap | 84 | Ранее подключён |
| Studio Yusupova | https://studio-yusupova.ru | existing | 289 | Ранее подключён |
| tashamorozova | https://tashamorozova.ru | tilda_extended | 2 | Полный |
| tifinapatterns | https://tifinapatterns.ru | vigbo | 60 | Ранее подключён |
| unikroj.ru | https://unikroj.ru | woo_store | 84 | Ранее подключён |
| VikiSews | https://vikisews.com | existing | 787 | Ранее подключён |
| vikroy-ka.ru | https://vikroy-ka.ru | bitrix_catalog | 138 | Полный |
| Whitewater | https://whitewaterdress.ru | tilda_sitemap | 210 | Ранее подключён |
| WomaNew | https://womanew.ru | woo_store | 105 | Полный |
| You Sew Dress | https://yousewdress.ru | woo_store | 42 | Ранее подключён |
| Your Tailor | https://your-tailor.ru | vigbo | 154 | Полный |
| Бурда | https://burdastyle.ru | burda | 12839 | Полный |
| Все лекала | https://vselekala.com | woo_html | 311 | Ранее подключён |
| выкроим | https://vikroim.ru | wordpress_posts | 9167 | Полный |
| Выкройки легко | https://patterneasy.com | patterneasy | 599 | Полный |
| Диана Брагар | https://bragar.shop | tilda_sitemap | 31 | Ранее подключён |
| Дмитрий Зорин | https://wmtailorschool.ru | woo_html | 18 | Ранее подключён |
| Елена Пленкина | https://elena-plenkina.ru | woo_store | 494 | Полный |
| Желток | https://zheltokbaby.com | tilda_api | 126 | Полный |
| Каминская | https://kaminskaya-sews.ru | tilda_sitemap | 241 | Ранее подключён |
| Катя Мхитарян | https://vikroyki-katya-mkhitaryan.ru | opencart | 231 | Полный |
| Кейт pattern | https://katie-patterns.ru | vigbo | 49 | Полный |
| Латели | https://latelye.ru | lekala_legacy | 3179 | Полный |
| Лекало онлайн | https://lekalo.online | opencart | 208 | Полный |
| ЛекалоЛинджери | https://lekalolingerie.com | opencart | 426 | Полный |
| Лекамаркет | https://lekamarket.ru | woo_store | 591 | Ранее подключён |
| мама шила малышу | https://mamashilamalishu.ru | october | 740 | Полный |
| моделирую и шью | https://modeliruishey.ru | vigbo | 28 | Ранее подключён |
| ПатернКло | https://patternclo.ru | bitrix_catalog | 425 | Полный |
| Рыбчинская | https://tailorgirl.net | tilda_api | 25 | Полный |
| Скроила | https://www.skroila.ru | woo_store | 147 | Полный |
| соу изи | https://seweeasy.com | tilda_extended | 15 | Полный |
| Творилка | https://tvorilkamom.ru | woo_html | 219 | Ранее подключён |
| Хочу и шью | https://wantandsew.online | bitrix_catalog | 211 | Полный |
| Хочу шить | https://wanttosew.ru | independent_html | 207 | Полный |
| шкатулка выкройки | https://shkatulka-sew.ru | shkatulka | 1282 | Полный |
| Шьюниверс | https://sewniverse.ru | woo_html | 55 | Ранее подключён |
| Элина Патыкова | https://elina-patykova.ru | woo_store | 734 | Ранее подключён |
| Я шью | https://yasew.ru | bitrix_catalog | 524 | Полный |

## Проверки и обновление

292 Python-теста прошли, включая миграцию со связанными пользовательскими таблицами и сохранением AUTOINCREMENT, реальные fixtures, incomplete snapshot, resume после сбоя, публичные API, цены, галереи и резервную обложку. Vue/TypeScript build прошёл.

Публичные browser E2E на production: каталог/карточка/возврат, фильтры и их сочетания, сохранение трикотажа при сортировке, все 88 импортированных поставщиков, алфавит, «Берет Рика», карусель/lightbox/zoom, избранное; отдельно размеры 320/390/768/1440 px с изображениями 4000×8000. Административный E2E намеренно пропущен на production: реальных подписанных initData администраторов не подделывали.

Существующий ежедневный refresh включает все 88 adapters и продолжает остальные источники после сбоя одного. Большие каталоги возобновляются из контрольных точек незавершённого обхода. Timeout сервиса увеличен до 6 часов для расширенного списка; бот и web — отдельные процессы. EasySew остаётся явным incomplete, а не маскируется успешным статусом. Все 88 одновременно повторно не обходились: новые источники проверены реальными полными обходами, оригинальные 42 сохранены; повторный перенос проверенных snapshot не нагружает производителей заново.

andrianova-pattern.ru (казино) и sew-garmentfactory.ru (финансовый блог) отключены. Новых адресов вне согласованного списка не добавляли. Дата первого импорта не считается датой публикации; неизвестные цена, сложность, материал, аудитория не подменяются догадками. Самостоятельное добавление произвольного URL в админке не создаёт парсер автоматически.
