import asyncio
import logging
import os
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.subscriptions import SubscriptionService
from app.services.yookassa import YooKassa
from app.web.auth import require_admin, require_user

logger = logging.getLogger(__name__)


class PlanInput(BaseModel):
    model_config = {'extra': 'forbid'}
    enabled: bool = False
    price_kopecks: int = Field(0, ge=0, le=70000000, strict=True)
    terms_url: str = Field('', max_length=500)
    support_url: str = Field('', max_length=500)

    @field_validator('terms_url', 'support_url')
    @classmethod
    def safe_link(cls, value):
        url = urlsplit(value)
        if value and (url.scheme != 'https' or not url.hostname or url.username or url.password):
            raise ValueError('Нужна HTTPS-ссылка')
        return value

    @model_validator(mode='after')
    def enabled_plan(self):
        if self.enabled and (self.price_kopecks < 100 or not self.terms_url or not self.support_url):
            raise ValueError('Укажите цену от 1 ₽, условия и контакт поддержки')
        return self


class CheckoutInput(BaseModel):
    accepted_terms: bool
    price_kopecks: int
    terms_url: str


class NotificationObject(BaseModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9-]{1,80}$')
    payment_id: str | None = Field(None, pattern=r'^[a-zA-Z0-9-]{1,80}$')


class Notification(BaseModel):
    event: str
    object: NotificationObject


def service(request):
    return request.app.state.subscriptions


def require_access(request: Request):
    billing = service(request)
    if not billing.plan()['enabled']:
        return
    try:
        require_admin(request)
        return
    except HTTPException:
        pass
    user_id = require_user(request)
    if not billing.status(user_id, test=request.app.state.yookassa.test)['has_access']:
        raise HTTPException(402, 'Пробный доступ завершён или ещё не активирован. Откройте раздел «Подписка».')


router = APIRouter()


@router.get('/api/subscription/plan')
def public_plan(request: Request):
    provider = request.app.state.yookassa
    return service(request).plan() | {'trial_days': 7, 'period_days': 30, 'currency': 'RUB',
                                     'payments_ready': provider.ready(), 'test': provider.test}


@router.get('/api/subscription')
def status(request: Request, user_id: int = Depends(require_user)):
    return service(request).status(user_id, test=request.app.state.yookassa.test)


@router.post('/api/subscription/trial')
def trial(request: Request, user_id: int = Depends(require_user)):
    if not service(request).plan()['enabled']:
        raise HTTPException(409, 'Пробный период будет доступен после запуска подписки')
    service(request).start_trial(user_id)
    return status(request, user_id)


@router.get('/api/admin/subscription', dependencies=[Depends(require_admin)])
def admin_plan(request: Request):
    return public_plan(request)


@router.put('/api/admin/subscription', dependencies=[Depends(require_admin)])
def save_plan(body: PlanInput, request: Request):
    if body.enabled and not request.app.state.yookassa.ready():
        raise HTTPException(409, 'Сначала настройте магазин ЮKassa и PAYMENTS_ENABLED')
    service(request).save_plan(body.model_dump())
    return public_plan(request)


@router.post('/api/subscription/payments')
async def checkout(body: CheckoutInput, request: Request, user_id: int = Depends(require_user)):
    billing, provider = service(request), request.app.state.yookassa
    plan = billing.plan()
    if not plan['enabled'] or not provider.ready():
        raise HTTPException(409, 'Приём платежей пока не включён')
    if not body.accepted_terms or body.price_kopecks != plan['price_kopecks'] or body.terms_url != plan['terms_url']:
        raise HTTPException(409, 'Подтвердите актуальные условия и стоимость подписки')
    username = os.getenv('BOT_USERNAME', '')
    import re
    if not re.fullmatch(r'[a-zA-Z0-9_]{5,32}', username):
        raise HTTPException(503, 'Возврат в Telegram не настроен')
    order_id = billing.new_order(user_id, provider.test, f'https://t.me/{username}?start=subscription')
    order = billing.order(order_id)
    if order['amount'] != body.price_kopecks or order['terms_url'] != body.terms_url:
        raise HTTPException(409, 'Есть незавершённый платёж по прежнему тарифу. Проверьте его в истории или дождитесь истечения часа.')
    try:
        order = await provider.sync(billing, order)
    except Exception:
        raise HTTPException(503, 'Не удалось связаться с ЮKassa. Повторите попытку: новый заказ не будет создан.') from None
    return payment_view(order)


def payment_view(order):
    return {key: order[key] for key in ('id', 'amount', 'days', 'test', 'created', 'status', 'checkout_url', 'refunded')}


@router.get('/api/subscription/payments')
def history(request: Request, user_id: int = Depends(require_user)):
    with service(request).db.connect() as c:
        rows = c.execute('SELECT * FROM subscription_orders WHERE user_id=? ORDER BY created DESC LIMIT 50', (user_id,)).fetchall()
    return [payment_view(dict(row)) for row in rows]


@router.post('/api/subscription/payments/{order_id}/check')
async def check(order_id: UUID, request: Request, user_id: int = Depends(require_user)):
    billing = service(request)
    try:
        order = billing.order(str(order_id), user_id)
    except ValueError:
        raise HTTPException(404, 'Платёж не найден') from None
    try:
        return payment_view(await request.app.state.yookassa.sync(billing, order))
    except Exception:
        raise HTTPException(503, 'Не удалось проверить платёж. Попробуйте позже.') from None


@router.post('/api/webhooks/yookassa')
async def webhook(body: Notification, request: Request):
    # The payload is only a notification. All financial facts come from authenticated GET.
    if body.event not in {'payment.succeeded', 'payment.canceled', 'refund.succeeded'}:
        return {'ok': True}
    provider_id = body.object.payment_id if body.event == 'refund.succeeded' else body.object.id
    billing = service(request)
    with billing.db.connect() as c:
        row = c.execute('SELECT * FROM subscription_orders WHERE provider_id=?', (provider_id,)).fetchone()
    if row:
        try:
            await request.app.state.yookassa.sync(billing, dict(row))
        except Exception:
            raise HTTPException(503, 'Повторите уведомление') from None
    # If notification arrived before creation completed, the recovery loop reconciles it.
    return {'ok': True}


async def reconcile(billing, provider):
    while True:
        for order in billing.pending():
            try:
                await provider.sync(billing, order)
            except Exception:
                logger.warning('Subscription reconciliation deferred: %s', order['id'])
            finally:
                billing.mark_checked(order['id'])
        await asyncio.sleep(30)


def install(app, database):
    app.state.subscriptions = SubscriptionService(database)
    app.state.subscriptions.initialize()
    app.state.yookassa = YooKassa()
    app.include_router(router)
