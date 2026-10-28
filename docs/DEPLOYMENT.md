# allsewpattern: эксплуатация

Приложение: `/opt/allsewpattern` на VPS `2.56.240.132`.
Бот: `@allsewpattern_bot`.
Mini App: `https://allsewpattern.2.56.240.132.sslip.io/`.
Техническое DNS-имя указывает на IP сервера, отдельная покупка домена не нужна.
Работа этого имени зависит от внешнего DNS-сервиса sslip.io.

## Сервисы

```bash
systemctl status allsewpattern-bot allsewpattern-web
journalctl -u allsewpattern-bot -n 50 --no-pager
journalctl -u allsewpattern-web -n 50 --no-pager
systemctl restart allsewpattern-bot allsewpattern-web
```

Оба процесса работают от отдельного пользователя `allsewpattern`, имеют
автоперезапуск, пишут в одну БД и используют новый токен из `.env`.
Backend слушает только `127.0.0.1:8017`, снаружи доступен через nginx и HTTPS.
Certbot автоматически продлевает сертификат. Проверка: `certbot renew --dry-run`.

Токен хранится только в `/opt/allsewpattern/.env`, файл `root:allsewpattern 640`.
Не публикуйте `.env`, дампы БД и заголовки Telegram initData.

## Администраторы

В production заданы `ADMIN_USERNAMES=shanniwaby,tatiana_svetlic`.
Откройте приложение кнопкой «Каталог» из соответствующего Telegram-аккаунта:
после проверки подписи появится кнопка «Управление» вверху справа.
При первом входе подтверждённый username привязывается к постоянному ID в БД.
Открытие обычной браузерной ссылки не даёт административного доступа.

## Обновление каталога

Ежедневный таймер: 01:00 UTC (06:00 Екатеринбург), случайная задержка до 10 минут.
Он последовательно запускает зарегистрированные adapters активных поставщиков через общий CatalogService.
Поставщики без подключённого адаптера остаются в справочнике со ссылкой на сайт.
Подробности: [SUPPLIERS_AUDIT.md](SUPPLIERS_AUDIT.md).
Отключённые в админке источники пропускаются. Ошибка одного не мешает остальным.
Неполный snapshot не запускает деактивацию отсутствующих товаров.

```bash
systemctl list-timers allsewpattern-refresh.timer
systemctl start --no-block allsewpattern-refresh.service
journalctl -u allsewpattern-refresh.service -f
```

Повторный одновременный запуск защищён `flock`. Ошибка или неполный snapshot
отражаются ненулевым кодом завершения сервиса, подробности находятся в журнале.
Это обновление listing-данных. Обложки регистрируются в очереди автоматически;
отдельные `allsewpattern-media.timer` и `allsewpattern-galleries.timer` каждые
пять минут после предыдущего прохода готовят фото и обогащают галереи небольшими
порциями. Подробнее: [MEDIA_PIPELINE.md](MEDIA_PIPELINE.md).

Перед каждым обновлением создаётся SQLite backup в `data/backups`, сохраняются
семь последних копий. Эти копии находятся на том же VPS: от удаления сервера
защищает только отдельная внешняя резервная копия.

## Оформление

`app/branding.py` содержит имя, описание и приветствие; картинки:
`app/assets/avatar.jpg`, `app/assets/welcome.jpg`.
`python -m app.branding` применяет имя, описание, команды и аватарку к боту
из текущего `.env`. Приветственная картинка отправляется при `/start`.
Картинка в описании до `/start` настраивается владельцем через BotFather,
если она требуется дополнительно: Edit Description Picture.

При переносе на другой токен очищайте в копии БД `telegram_file_id` и
`image_status`: Telegram-кэш фотографий привязан к конкретному боту.
Исходные product/image URL сохраняются.

## Обновление кода

Сначала выполните Python-тесты и frontend build. Архив кода не должен содержать
`.env`, БД, `ТЗ .docx`, `.git` или `node_modules`. Сохраните SQLite backup,
распакуйте новый код, установите зависимости, затем перезапустите два сервиса.
Не заменяйте действующую БД старой локальной копией при обычном обновлении кода.
`deploy/install.sh` предназначен для первоначальной установки подготовленного
архива из `/root/allsewpattern-transfer`; существующую БД он не перезаписывает.
