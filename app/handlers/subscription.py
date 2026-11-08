from aiogram import BaseMiddleware, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from app.miniapp import miniapp_entry_url
from urllib.parse import urljoin
from app.services.subscriptions import SubscriptionService
from app.services.yookassa import YooKassa
from app.web.auth import WebSettings


def subscription_keyboard(url):
    if not url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text='Подписка · 7 дней бесплатно',
        web_app=WebAppInfo(url=miniapp_entry_url(url, 'subscription')),
    )]])


class SubscriptionGuard(BaseMiddleware):
    def __init__(self, service, miniapp_url):
        self.service = service
        self.url = miniapp_url

    async def __call__(self, handler, event, data):
        if not self.service.plan()['enabled']:
            return await handler(event, data)
        user = event.from_user
        settings = WebSettings.from_env()
        allowed = user is not None and user.id in settings.admin_ids
        if user:
            with self.service.db.connect() as c:
                for name in settings.admin_usernames:
                    row = c.execute('SELECT value FROM settings WHERE key=?', ('miniapp.admin.' + name,)).fetchone()
                    allowed = allowed or (row is not None and row[0] == str(user.id))
        if allowed or (user and self.service.status(user.id, test=YooKassa().test)['has_access']):
            return await handler(event, data)
        message = event.message if isinstance(event, CallbackQuery) else event
        if isinstance(event, CallbackQuery):
            await event.answer()
        if message:
            await message.answer('Откройте «Подписку»: первые 7 дней бесплатно, затем продление на 30 дней. Автосписаний нет.',
                                 reply_markup=subscription_keyboard(self.url))


def create_subscription_router(service: SubscriptionService, url):
    router = Router(name='subscription')

    async def show(message: Message):
        plan = service.plan()
        price = f"{plan['price_kopecks'] / 100:g} ₽" if plan['price_kopecks'] else 'цена пока не установлена'
        await message.answer('allsewpattern — подписка на каталог выкроек\n\n'
                             f'Первые 7 дней бесплатно. Далее {price} за 30 дней. '
                             'Продление вручную, без автосписаний. Файлы выкроек приобретаются отдельно у производителей.',
                             reply_markup=subscription_keyboard(url))

    router.message.register(show, Command('subscription'))
    router.message.register(show, CommandStart(deep_link=True), lambda message: message.text == '/start subscription')

    @router.message(Command('paysupport', 'support', 'terms'))
    async def support(message: Message):
        plan = service.plan()
        await message.answer('Условия подписки: ' + urljoin(url or '', plan['terms_url']) +
                             '\nПоддержка и возвраты: ' + urljoin(url or '', plan['support_url']))
    return router
