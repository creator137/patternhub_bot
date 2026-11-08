"""Redirect checkout, isolated test/live credentials; never trust the return URL."""
import os
import time
from urllib.parse import urlsplit

import httpx


class YooKassa:
    @property
    def test(self):
        mode = os.getenv('YOOKASSA_MODE', 'test')
        if mode not in {'test', 'live'}:
            raise ValueError('Некорректный режим ЮKassa')
        return mode == 'test'

    def credentials(self, test):
        suffix = '_TEST' if test else ''
        shop = os.getenv('YOOKASSA_SHOP_ID' + suffix, '')
        key = os.getenv('YOOKASSA_SECRET_KEY' + suffix, '')
        if not shop or not key.startswith('test_' if test else 'live_'):
            raise ValueError('Магазин ЮKassa не настроен')
        return shop, key

    def ready(self):
        if os.getenv('PAYMENTS_ENABLED') != 'true':
            return False
        try:
            if not self.test and os.getenv('YOOKASSA_LIVE_APPROVED') != 'true':
                return False
            self.credentials(self.test)
            return True
        except ValueError:
            return False

    async def request(self, path, test, *, body=None, key=None):
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request('POST' if body else 'GET', 'https://api.yookassa.ru/v3/' + path,
                                            auth=self.credentials(test), json=body,
                                            headers={'Idempotence-Key': key} if key else {})
            response.raise_for_status()
            return response.json()

    async def sync(self, service, order):
        if order['provider_id']:
            remote = await self.request('payments/' + order['provider_id'], bool(order['test']))
        else:
            if order['created'] < int(time.time()) - 23 * 3600:
                raise ValueError('Нужна ручная сверка заказа: срок идемпотентности истёк')
            body = {
                'amount': {'value': f"{order['amount'] // 100}.{order['amount'] % 100:02d}", 'currency': 'RUB'},
                'capture': True,
                'confirmation': {'type': 'redirect', 'return_url': order['return_url']},
                'description': 'allsewpattern — доступ к каталогу на 30 дней',
                'metadata': {'order_id': order['id'], 'user_id': str(order['user_id'])},
            }
            remote = await self.request('payments', bool(order['test']), body=body, key=order['id'])
        checkout = remote.get('confirmation', {}).get('confirmation_url')
        if checkout:
            url = urlsplit(checkout)
            if url.scheme != 'https' or url.username or url.password:
                raise ValueError('Некорректный адрес оплаты')
        service.settle(order['id'], remote)
        return service.order(order['id'])
