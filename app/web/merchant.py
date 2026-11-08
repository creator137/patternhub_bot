"""Public merchant pages: no Telegram login or administrator credentials required."""
import json
import re
from html import escape

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator

from app.web.auth import require_admin


class Merchant(BaseModel):
    model_config = {'extra': 'forbid', 'str_strip_whitespace': True}
    full_name: str = Field('', max_length=200)
    inn: str = Field('', pattern=r'^(?:[0-9]{12})?$')
    email: str = Field('', max_length=254)

    @field_validator('email')
    @classmethod
    def email_format(cls, value):
        if value and not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', value):
            raise ValueError('Укажите рабочий email')
        return value


def merchant(database):
    with database.connect() as c:
        row = c.execute("SELECT value FROM settings WHERE key='merchant.public'").fetchone()
    return Merchant.model_validate_json(row[0]) if row else Merchant()


router = APIRouter()


@router.get('/api/admin/merchant', dependencies=[Depends(require_admin)])
def get_merchant(request: Request):
    return merchant(request.app.state.database)


@router.put('/api/admin/merchant', dependencies=[Depends(require_admin)])
def save_merchant(body: Merchant, request: Request):
    with request.app.state.database.connect() as c:
        c.execute("INSERT INTO settings(key,value) VALUES('merchant.public',?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",
                  (body.model_dump_json(),))
    return body


def page(title, body):
    return HTMLResponse('''<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>''' + escape(title) + ''' — allsewpattern</title>
<style>body{margin:0;background:#f8f7f4;color:#23352c;font:17px/1.65 system-ui,sans-serif}
main{max-width:740px;margin:40px auto;padding:24px}article{background:white;border:1px solid #deded8;border-radius:20px;padding:28px}
nav,footer{display:flex;gap:20px;flex-wrap:wrap;margin:24px 0}a{color:#35543e}h1{line-height:1.2;font-size:30px}
dt{font-weight:600;margin-top:20px}dd{margin:4px 0;overflow-wrap:anywhere}.price{font-size:28px;font-weight:700}
.button{display:inline-block;background:#35543e;color:white;padding:12px 20px;border-radius:12px;text-decoration:none}
.notice{padding:12px;background:#f5f0de;border-radius:10px}small{color:#59665d}@media(max-width:480px){main{padding:16px;margin:12px auto}article{padding:20px}}</style></head><body><main>
<nav><a href="/">allsewpattern · Каталог</a><a href="/subscription">Подписка</a><a href="/seller">Реквизиты</a></nav>
<article>''' + body + '''</article><footer><a href="/seller">Реквизиты и контакты</a><a href="/subscription">Стоимость и получение доступа</a><a href="/terms">Условия подписки</a></footer>
</main></body></html>''', headers={'Cache-Control': 'no-store'})


@router.get('/terms', response_class=HTMLResponse)
def terms(request: Request):
    plan = request.app.state.subscriptions.plan()
    data = merchant(request.app.state.database)
    amount = plan['price_kopecks']
    price = f'{amount / 100:.2f}'.replace('.', ',') + ' ₽' if amount else 'ещё не установлена'
    return page('Условия подписки', '<h1>Условия подписки allsewpattern</h1>'
                '<h2>Что входит в подписку</h2><p>Доступ к каталогу выкроек: поиск, фильтры, избранное и ссылки на сайты производителей. '
                'Подписка не включает файлы выкроек и покупки на сторонних сайтах. Наличие, цены и условия покупки выкроек определяются производителями.</p>'
                '<h2>Пробный период и стоимость</h2><p>Первые 7 дней бесплатно, один раз на Telegram-аккаунт. '
                'Пробный период начинается после нажатия кнопки активации. Привязка карты не требуется.</p>'
                '<p>Текущая стоимость доступа на 30 дней: <strong>' + price + '</strong>. '
                'Цена показывается перед оформлением заказа и фиксируется для этого заказа. Изменение тарифа не меняет уже оплаченный срок.</p>'
                '<h2>Оплата и доступ</h2><p>Оплата через ЮKassa. Подписка продлевается вручную: автоматических списаний и сохранения карты для автоплатежей нет. '
                'Доступ открывается после подтверждения оплаты платёжной системой для Telegram-аккаунта, оформившего заказ. '
                'При досрочном продлении 30 дней добавляются к оставшемуся сроку. После окончания срока каталог закрывается до продления; избранное сохраняется.</p>'
                '<h2>Поддержка и возвраты</h2><p>Если оплата прошла, а доступ не появился, нажмите «Проверить платёж» в истории платежей. '
                'Для обращения используйте контакт на <a href="/seller">странице продавца</a>, укажите номер заказа и описание проблемы. '
                'Не передавайте данные банковской карты. Обращения о возврате рассматривает продавец с учётом обстоятельств покупки и применимых требований законодательства. '
                'При возврате оплаты соответствующий оплаченный период доступа прекращается.</p>'
                '<h2>Продавец</h2><p>' + escape(data.full_name or 'Данные пока не опубликованы') + ', ИНН ' + escape(data.inn or 'не указан') +
                '. <a href="/seller">Реквизиты и контакт поддержки</a>.</p>'
                '<p>Перед оплатой пользователь подтверждает ознакомление с условиями подписки.</p>')


@router.get('/seller', response_class=HTMLResponse)
def seller(request: Request):
    data = merchant(request.app.state.database)
    contact = ('<a href="mailto:' + escape(data.email, quote=True) + '">' + escape(data.email) + '</a>') if data.email else 'Контакт поддержки будет опубликован до начала приёма платежей.'
    return page('Реквизиты продавца', '<h1>Реквизиты продавца</h1><p>Сервис allsewpattern — агрегатор выкроек.</p><dl>'
                '<dt>Продавец · самозанятая</dt><dd>' + escape(data.full_name or 'Данные пока не опубликованы') +
                '</dd><dt>ИНН</dt><dd>' + escape(data.inn or 'Не указан') +
                '</dd><dt>Поддержка и обращения по оплате</dt><dd>' + contact + '</dd></dl>'
                '<p>Продавец предоставляет доступ к агрегатору. Выкройки приобретаются отдельно на сайтах производителей.</p>')


@router.get('/subscription', response_class=HTMLResponse)
def subscription(request: Request):
    plan = request.app.state.subscriptions.plan()
    data = merchant(request.app.state.database)
    amount = plan['price_kopecks']
    price = f'{amount // 100:,}'.replace(',', ' ') + (f',{amount % 100:02d}' if amount % 100 else '') + ' ₽ за 30 дней' if amount else 'Стоимость пока не установлена'
    terms = '<p><a href="' + escape(plan['terms_url'], quote=True) + '">Условия подписки</a></p>' if plan['terms_url'] else '<p>Условия договора будут опубликованы до начала приёма платежей.</p>'
    notice = '' if plan['enabled'] else '<p class="notice">Приём оплаты подписки пока не запущен. Каталог доступен без оплаты.</p>'
    return page('Подписка на каталог выкроек', '<h1>Подписка на каталог выкроек</h1>'
                '<p>Поиск выкроек по брендам и категориям, фильтры, избранное и переходы к производителям в allsewpattern.</p>'
                '<p class="price">' + price + '</p><p>Первые 7 дней бесплатно, один раз на Telegram-аккаунт. '
                'Пробный период начинается по кнопке пользователя. Затем — ручное продление на 30 дней, без автоматических списаний.</p>'
                '<h2>Как получить доступ</h2><p>Откройте бота @allsewpattern_bot и Mini App, затем раздел «Подписка». '
                'После запуска оплаты доступ предоставляется тому Telegram-аккаунту, который оформил заказ, после подтверждения платежа ЮKassa. '
                'Досрочное продление добавляет 30 дней к оставшемуся сроку.</p>'
                '<p>Доставка не требуется. Файлы выкроек не входят в подписку и приобретаются отдельно у производителей.</p>'
                + notice + '<a class="button" href="https://t.me/allsewpattern_bot?start=subscription">Открыть подписку в Telegram</a>'
                + terms + '<p>Продавец: ' + escape(data.full_name or 'Данные пока не опубликованы') +
                '. ИНН: ' + escape(data.inn or 'не указан') + '.</p><p><a href="/seller">Контакты и реквизиты продавца</a></p>')
