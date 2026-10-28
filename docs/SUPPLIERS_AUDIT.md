# Поставщики: аудит и расширение 28.10.2026

Полный список из согласованного XLSX: 90 уникальных адресов после устранения повторов. Публично включены 88. Два перепрофилированных домена отключены. Закрытые строки и строки без рабочего адреса не создают фиктивных поставщиков. Исходный XLSX и ТЗ в Git не включаются.

## Интерфейс

Два раздела: «Выкройки» и «Поставщики». Общие публичные фильтры: поиск по названию, бренд, тип изделия. Бренды и справочник сортируются по алфавиту (русская locale в интерфейсе). Ненадёжные общие признаки аудитории, новизны, материалов, сложности, бесплатности и скидок скрыты вместе с сортировками по дате/цене. Импортированные факты сохранены в БД и доступны внутреннему API, публичные контролы их не предлагают. Старые сохранённые фильтры браузера очищаются.

Каждый поставщик имеет переход на исходный сайт. Кнопка «Выкройки» появляется только при наличии реально импортированных доступных товаров. Нулевой счётчик не маскируется под успешный импорт. Добавление URL в админке добавляет запись справочника, а не автоматически создаёт новый парсер.

## Адаптеры

Существующие пять providers сохранены. Новые сайты используют общие адаптеры WooCommerce Store API, WooCommerce HTML, Tilda sitemap + HTML и Vigbo HTML. Все возвращают ParsedProduct в существующий CatalogService, отдельные handlers и таблицы не создаются.

- WooCommerce: публичный Store API, заголовки X-WP-Total/X-WP-TotalPages и стабильный product ID. HTML применяется там, где API недоступен. [Официальная документация Store API](https://developer.woocommerce.com/docs/apis/store-api/).
- Tilda: sitemap-store.xml на домене поставщика, публичная HTML-карточка, embedded JSON или собственная разметка товара. CDN store.tildacdn.com, чей robots запрещает обход, не используется. Закрытые Members area и страницы курсов пропускаются. [Каталог Tilda](https://help-ru.tilda.cc/online-store/catalog).
- Vigbo: серверные карточки data-productid и штатная next-пагинация.
- Один HTTP-клиент на источник, последовательные страницы, минимальный интервал 0,2 с, ограниченные сетевые/429/5xx retries, robots перед обходом; внешний origin/закрытые endpoints не обходятся.
- Ошибка страницы, неизвестная пагинация, повтор страниц или лимит → incomplete, частичный набор отклоняется, старые товары не деактивируются. Complete допускается после подтверждения конца каталога.
- Курсы, сертификаты, игрушки и прочие очевидные не-выкройки исключаются; аксессуары и настоящие сумки остаются.

## Результат публичных crawl

37 новых полных каталогов: 10 018 валидных записей, из них 10 007 доступны в источнике. Часть кожевенных/бесплатных материалов Neovima не публикует цену в listing: отсутствие цены не превращается в 0 ₽. Честная категория «Другое» сохраняется там, где тип изделия нельзя подтвердить.

Снимки предварительного обхода переносятся через `python -m app.snapshots FILE`: проверяются происхождение URL, уникальность, complete, дата наблюдения не старше 24 ч; далее обычный upsert/media queue/reconciliation. Время наблюдения не становится датой публикации изделия. Первый перенос: Added 10 020; повтор: Added 0, Updated 10 020; ошибок 0. При заключительной проверке исключены ещё две позиции (услуга печати и тестовый товар): сохранены как unavailable после complete snapshot. Финальный актуальный snapshot содержит 10 018 записей; повторная загрузка Added 0.

## Все адреса

| Бренд | Сайт | Специализация | Каталог | Записей в новом snapshot |
|---|---|---|---|---:|
| alena kochkareva | https://alenakochkareva.ru | lingerie | tilda_sitemap | 35 |
| all-sew | https://all-sew.ru | general | vigbo | 199 |
| Andrianova pattern | https://andrianova-pattern.ru | general | Отключён: Домен переиспользован: текущее содержимое не относится к выкройкам. | — |
| angela-molodets.ru | https://angela-molodets.ru | general | vigbo | 8 |
| Ansews | https://ansews.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| aspatterns | https://aspatterns.ru | kids | Ссылка на сайт; полный импорт не подтверждён | — |
| aurorasew.ru | https://aurorasew.ru | general | tilda_sitemap | 3 |
| baysews | https://baysews.ru | general | tilda_sitemap | 96 |
| belenochka | https://belenochka.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Dress you | https://dress-layout.ru | general | tilda_sitemap | 22 |
| Easy sews | https://easysew.info | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Elenapatternstudio | https://elenapatternstudio.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| fancysmth | https://fancysmth.com | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Grasser | https://grasser.ru | general | Ранее подключён | — |
| HelperSew | https://helpersew.com | general | Ранее подключён | — |
| ivahm-patterns | https://ivahm-patterns.ru | general | vigbo | 111 |
| juliastefanello | https://juliastefanello.com | lingerie | Ссылка на сайт; полный импорт не подтверждён | — |
| kapsulestore | https://kapsulestore.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Kids Patterns | https://kids-patterns.ru | kids | vigbo | 36 |
| LaForme | https://laforme.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| laviedelalingerie | https://laviedelalingerie-shop.com | lingerie | woo_store | 43 |
| Lebovi выкройки | https://lebovi.by | general | woo_store | 11 |
| lekalo-kids | https://lekalo-kids.ru | kids | vigbo | 120 |
| leko mail | https://leko-mail.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| lirapattern.ru | https://lirapattern.ru | general | woo_store | 85 |
| Loko pattern | https://lokopatterns.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| lspatterns.ru | https://lspatterns.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| lubimchiki-style.ru | https://lubimchiki-style.ru | general | tilda_sitemap | 181 |
| Marymake | https://marymake.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| masterskayakorol.ru | https://masterskayakorol.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| mialine | https://mialine.ru | general | tilda_sitemap | 106 |
| Mint mom | https://mintmoon.ru | general | vigbo | 53 |
| Modety | https://modety.ru | kids | Ссылка на сайт; полный импорт не подтверждён | — |
| morozovamarie.ru | https://morozovamarie.ru | general | vigbo | 17 |
| neovima.com | https://neovima.com | general | woo_html | 5758 |
| oldem-sew.ru | https://oldem-sew.ru | general | woo_store | 117 |
| One Pattern | https://helenpatterns.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| onesews.com | https://onesews.com | general | woo_store | 76 |
| PA2TERN | https://pa2tern.com | general | tilda_sitemap | 54 |
| Perchik Patterns | https://perchikpatterns.ru | lingerie | vigbo | 73 |
| SELFTAILOR | https://selftailor.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| settembre.ru | https://settembre.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| sew-garmentfactory.ru | https://sew-garmentfactory.ru | general | Отключён: Домен переиспользован: текущее содержимое не относится к выкройкам. | — |
| sew-light.com | https://sew-light.com | general | woo_store | 84 |
| sew-line | https://sew-lane.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| SewFreedom | https://sewfreedom.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| SewItNow | https://sewitnow.ru | general | Ранее подключён | — |
| SewLevel | https://sewlevel.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| shape in space | https://shapeinspace.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| shvej-shop | https://shvej-shop.by | lingerie | Ссылка на сайт; полный импорт не подтверждён | — |
| shveyaholic.ru | https://shveyaholic.ru | general | tilda_sitemap | 11 |
| starkova-art.ru | https://starkova-art.ru | general | tilda_sitemap | 84 |
| Studio Yusupova | https://studio-yusupova.ru | general | Ранее подключён | — |
| tashamorozova | https://tashamorozova.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| tifinapatterns | https://tifinapatterns.ru | general | vigbo | 60 |
| unikroj.ru | https://unikroj.ru | general | woo_store | 84 |
| VikiSews | https://vikisews.com | general | Ранее подключён | — |
| vikroy-ka.ru | https://vikroy-ka.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Whitewater | https://whitewaterdress.ru | general | tilda_sitemap | 210 |
| WomaNew | https://womanew.ru | lingerie | Ссылка на сайт; полный импорт не подтверждён | — |
| You Sew Dress | https://yousewdress.ru | general | woo_store | 42 |
| Your Tailor | https://your-tailor.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Бурда | https://burdastyle.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Все лекала | https://vselekala.com | general | woo_html | 311 |
| выкроим | https://vikroim.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Выкройки легко | https://patterneasy.com | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Диана Брагар | https://bragar.shop | general | tilda_sitemap | 31 |
| Дмитрий Зорин | https://wmtailorschool.ru | general | woo_html | 18 |
| Елена Пленкина | https://elena-plenkina.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Желток | https://zheltokbaby.com | kids | Ссылка на сайт; полный импорт не подтверждён | — |
| Каминская | https://kaminskaya-sews.ru | general | tilda_sitemap | 241 |
| Катя Мхитарян | https://vikroyki-katya-mkhitaryan.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Кейт pattern | https://katie-patterns.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Латели | https://latelye.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Лекало онлайн | https://lekalo.online | kids | Ссылка на сайт; полный импорт не подтверждён | — |
| ЛекалоЛинджери | https://lekalolingerie.com | lingerie | Ссылка на сайт; полный импорт не подтверждён | — |
| Лекамаркет | https://lekamarket.ru | general | woo_store | 602 |
| мама шила малышу | https://mamashilamalishu.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| моделирую и шью | https://modeliruishey.ru | general | vigbo | 28 |
| ПатернКло | https://patternclo.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Рыбчинская | https://tailorgirl.net | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Скроила | https://www.skroila.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| соу изи | https://seweeasy.com | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Творилка | https://tvorilkamom.ru | general | woo_html | 219 |
| Хочу и шью | https://wantandsew.online | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Хочу шить | https://wanttosew.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| шкатулка выкройки | https://shkatulka-sew.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |
| Шьюниверс | https://sewniverse.ru | general | woo_html | 55 |
| Элина Патыкова | https://elina-patykova.ru | general | woo_store | 734 |
| Я шью | https://yasew.ru | general | Ссылка на сайт; полный импорт не подтверждён | — |

## Ограничения и актуальность

- Elena Plenkina: полный Store API отвечает нестабильно/ReadTimeout; первые ответы не являются полным импортом.
- Tailorgirl: маршрут товара уходит на другой origin; не обходим ограничение и не публикуем неполный snapshot.
- Shvej Shop: robots запрещает следующую страницу; карточки первой страницы не выдаются за полный каталог.
- Часть остальных сайтов — индивидуальные платформы, блокировки/недоступность или закрытые API: пока доступны ссылками.
- У ряда добавленных сайтов аудитория не доказана: None, без автоматического присвоения women/kids. Аудитория скрыта в общем публичном меню.
- Marymake: ошибочная ранняя ссылка на SewItNow заменена фактическим marymake.ru; повторы wanttosew, yasew, dress-layout объединены.
- andrianova-pattern.ru — казино; sew-garmentfactory.ru — финансовый блог. Не публикуются.
- Сумки и рюкзаки — общая категория bags; старые подходящие аксессуары переведены один раз, пользовательские overrides не затрагиваются. Специализация pets подготовлена для будущих адресов, поставщики животных не выдуманы.
- Ежедневный refresh перебирает активные adapters из registry. Поставщики только со ссылкой не имитируют импорт. Медиа остаётся в ограниченном кэше 768 MB; неизвестные произвольные домены не становятся доверенными автоматически.

## Production-проверка

28.10.2026: 13 545 записей всего, 13 529 available и 16 unavailable. 42 источника с товарами, 88 ссылок поставщиков. 338/338 проверенных входных обложек успешно скачаны и подготовлены; это выборочная проверка по первым карточкам каждого источника, не обещание 100% всех фотографий. Фоновые очереди и лимит 768 MB сохранены.

Проверенные новые crawl: 1471 HTTP-запрос, 14 retries; сумма длительностей последовательного выполнения около 21,8 минуты (исследование выполнялось с ограниченной параллельностью разных сайтов). В registry активны 42 проверенных product providers; три неподтверждённых адаптера отмечены candidate_adapter и не запускаются таймером.

Проверки: 215 Python-тестов; 8 публичных browser E2E на production; 3 административных E2E на отдельной локальной БД с тестовым токеном. Сборка Vue/TypeScript прошла. Реальные production-учётные данные для имитации администраторов не использовались.
