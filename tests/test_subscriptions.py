import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.database import Database
from app.services.subscriptions import SubscriptionService, DAY
from app.services.yookassa import YooKassa
from app.web.auth import WebSettings
from app.web.main import create_app


def auth(user_id=123):
    values = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': user_id})}
    secret = hmac.new(b'WebAppData', b'test-token', hashlib.sha256).digest()
    values['hash'] = hmac.new(secret, '\n'.join(f'{k}={v}' for k, v in sorted(values.items())).encode(), hashlib.sha256).hexdigest()
    return {'X-Telegram-Init-Data': urlencode(values)}


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'test.sqlite3')
        self.db.initialize()
        self.s = SubscriptionService(self.db)
        self.s.initialize()
        self.s.save_plan({'enabled': True, 'price_kopecks': 29900, 'terms_url': 'https://example.com/terms', 'support_url': 'https://t.me/help'})

    def tearDown(self):
        self.temp.cleanup()

    def order(self, user=123):
        return self.s.order(self.s.new_order(user, True, 'https://t.me/patternhub_bot?start=subscription'))

    def remote(self, order):
        return {'id': 'provider-' + order['id'], 'amount': {'value': '299.00', 'currency': 'RUB'},
                'test': True, 'metadata': {'order_id': order['id'], 'user_id': str(order['user_id'])},
                'status': 'succeeded', 'paid': True}

    def test_trial_once_persists_and_expires(self):
        self.s.start_trial(123, now=100)
        self.s.start_trial(123, now=200)
        restarted = SubscriptionService(self.db)
        self.assertEqual(restarted.status(123, now=101)['trial_end'], 100 + 7 * DAY)
        self.assertFalse(restarted.status(123, now=100 + 7 * DAY)['has_access'])
        self.assertFalse(restarted.status(123, now=100 + 7 * DAY)['trial_available'])

    def test_repeat_checkout_uses_same_snapshot(self):
        a = self.order()
        self.s.save_plan(self.s.plan() | {'price_kopecks': 50000})
        self.assertEqual(self.order()['id'], a['id'])
        self.assertEqual(self.order()['amount'], 29900)

    def test_duplicate_success_and_early_renewal(self):
        self.s.start_trial(123)
        trial_end = self.s.status(123)['trial_end']
        order = self.order()
        self.s.settle(order['id'], self.remote(order))
        self.s.settle(order['id'], self.remote(order))
        self.assertEqual(self.s.status(123, test=True)['access_until'], trial_end + 30 * DAY)
        second = self.order()
        self.s.settle(second['id'], self.remote(second))
        self.assertEqual(self.s.status(123, test=True)['access_until'], trial_end + 60 * DAY)

    def test_test_payment_never_grants_live_access(self):
        order = self.order()
        self.s.settle(order['id'], self.remote(order))
        self.assertTrue(self.s.status(123, test=True)['has_access'])
        self.assertFalse(self.s.status(123, test=False)['has_access'])

    def test_mismatched_remote_never_credits(self):
        order = self.order()
        for field, value in [('test', False), ('test', 1), ('amount', {'value': '1.00', 'currency': 'RUB'}),
                             ('amount', {'value': '299.00', 'currency': 'USD'}),
                             ('metadata', {'order_id': order['id'], 'user_id': '999'})]:
            remote = self.remote(order)
            remote[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.s.settle(order['id'], remote)
        self.assertFalse(self.s.status(123, test=True)['has_access'])

    def test_pending_and_cancel_never_grant(self):
        order = self.order()
        remote = self.remote(order) | {'status': 'pending', 'paid': False}
        self.s.settle(order['id'], remote)
        self.assertFalse(self.s.status(123, test=True)['has_access'])
        self.s.settle(order['id'], remote | {'status': 'canceled'})
        self.assertEqual(self.s.order(order['id'])['status'], 'canceled')

    def test_refund_revokes_and_cannot_be_undone_by_stale_success(self):
        order = self.order()
        remote = self.remote(order)
        self.s.settle(order['id'], remote)
        self.s.settle(order['id'], remote | {'refunded_amount': {'value': '299.00', 'currency': 'RUB'}})
        self.s.settle(order['id'], remote)
        self.assertFalse(self.s.status(123, test=True)['has_access'])

    def test_api_access_ownership_and_admin(self):
        client = TestClient(create_app(self.db, WebSettings('test-token', frozenset({42}))))
        self.assertEqual(client.get('/api/products').status_code, 401)
        self.assertEqual(client.get('/api/products', headers=auth()).status_code, 402)
        self.assertEqual(client.get('/api/suppliers', headers=auth()).status_code, 402)
        self.assertEqual(client.get('/api/products', headers=auth(42)).status_code, 200)
        self.assertEqual(client.get('/api/admin/subscription', headers=auth()).status_code, 403)
        self.assertEqual(client.post('/api/subscription/trial', headers=auth()).status_code, 200)
        self.assertEqual(client.get('/api/products', headers=auth()).status_code, 200)
        order = self.order()
        self.assertEqual(client.post('/api/subscription/payments/'+order['id']+'/check', headers=auth(999)).status_code, 404)
        self.assertEqual(client.get('/api/subscription/payments', headers=auth(999)).json(), [])
        client.close()

    def test_disabled_plan_is_backwards_compatible_and_doesnt_start_trial(self):
        self.s.save_plan(self.s.plan() | {'enabled': False})
        client = TestClient(create_app(self.db, WebSettings('test-token')))
        self.assertEqual(client.get('/api/products').status_code, 200)
        self.assertEqual(client.post('/api/subscription/trial', headers=auth()).status_code, 409)
        self.assertTrue(self.s.status(123)['trial_available'])
        client.close()

    def test_webhook_fetches_provider_and_duplicate_delivery(self):
        order = self.order()
        remote = self.remote(order)
        self.s.settle(order['id'], remote | {'status': 'pending', 'paid': False})
        client = TestClient(create_app(self.db, WebSettings('test-token')))
        with patch.object(YooKassa, 'request', AsyncMock(return_value=remote)) as fetch:
            for _ in range(2):
                response = client.post('/api/webhooks/yookassa', json={'event': 'payment.succeeded', 'object': {'id': remote['id'], 'amount': {'value': '9999'}}})
                self.assertEqual(response.status_code, 200)
            self.assertEqual(fetch.await_count, 2)
        self.assertLessEqual(self.s.status(123, test=True)['access_until'], int(time.time()) + 30 * DAY)
        client.close()

    def test_checkout_uses_server_price_and_consent(self):
        client = TestClient(create_app(self.db, WebSettings('test-token')))
        with patch.dict('os.environ', {'BOT_USERNAME': 'patternhub_bot'}), patch.object(YooKassa, 'ready', return_value=True):
            payload = {'accepted_terms': True, 'price_kopecks': 1, 'terms_url': 'https://example.com/terms'}
            self.assertEqual(client.post('/api/subscription/payments', headers=auth(), json=payload).status_code, 409)
            payload['price_kopecks'] = 29900
            order = self.order()
            remote = self.remote(order) | {'status': 'pending', 'paid': False, 'confirmation': {'confirmation_url': 'https://yoomoney.ru/checkout'}}
            with patch.object(YooKassa, 'request', AsyncMock(return_value=remote)) as fetch:
                response = client.post('/api/subscription/payments', headers=auth(), json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(fetch.call_args.kwargs['body']['amount']['value'], '299.00')
                self.assertEqual(fetch.call_args.kwargs['key'], order['id'])
        client.close()

    def test_live_launch_requires_explicit_approval(self):
        with patch.dict('os.environ', {'PAYMENTS_ENABLED': 'true', 'YOOKASSA_MODE': 'live', 'YOOKASSA_SHOP_ID': '123', 'YOOKASSA_SECRET_KEY': 'live_testfixture', 'YOOKASSA_LIVE_APPROVED': 'false'}):
            self.assertFalse(YooKassa().ready())

    def test_concurrent_notifications_credit_once(self):
        from concurrent.futures import ThreadPoolExecutor
        order = self.order()
        remote = self.remote(order)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.s.settle(order['id'], remote), range(8)))
        paid = self.s.order(order['id'])
        self.assertEqual(self.s.status(123, test=True)['access_until'], paid['paid_at'] + 30 * DAY)
        self.s.start_trial(123)
        self.assertFalse(self.s.status(123, test=True)['trial_available'])
        self.assertEqual(self.s.status(123, test=True)['access_until'], paid['paid_at'] + 30 * DAY)

    def test_admin_plan_validation(self):
        client = TestClient(create_app(self.db, WebSettings('test-token', frozenset({42}))))
        plan = self.s.plan()
        for changed in ({'price_kopecks': -1}, {'price_kopecks': 1.5}, {'terms_url': 'javascript:alert(1)'}, {'support_url': ''}):
            self.assertEqual(client.put('/api/admin/subscription', headers=auth(42), json=plan | changed).status_code, 422)
        with patch.object(YooKassa, 'ready', return_value=False):
            self.assertEqual(client.put('/api/admin/subscription', headers=auth(42), json=plan).status_code, 409)
        with patch.object(YooKassa, 'ready', return_value=True):
            self.assertEqual(client.put('/api/admin/subscription', headers=auth(42), json=plan | {'price_kopecks': 99000}).status_code, 200)
        self.assertEqual(self.s.plan()['price_kopecks'], 99000)
        client.close()

    def test_public_merchant_pages_and_protected_edits(self):
        client = TestClient(create_app(self.db, WebSettings('test-token', frozenset({42}))))
        body = {'full_name': '<script>alert(1)</script>', 'inn': '123456789012', 'email': 'support@example.com'}
        self.assertEqual(client.put('/api/admin/merchant', json=body).status_code, 401)
        self.assertEqual(client.put('/api/admin/merchant', headers=auth(), json=body).status_code, 403)
        self.assertEqual(client.put('/api/admin/merchant', headers=auth(42), json=body).status_code, 200)
        html = client.get('/seller')
        self.assertEqual(html.status_code, 200)
        self.assertIn('&lt;script&gt;', html.text)
        self.assertNotIn('<script>alert', html.text)
        self.assertIn('123456789012', html.text)
        self.assertIn('support@example.com', html.text)
        self.assertEqual(html.headers['cache-control'], 'no-store')
        self.assertIn('299 ₽ за 30 дней', client.get('/subscription').text)
        self.s.save_plan(self.s.plan() | {'price_kopecks': 49900})
        self.assertIn('499 ₽ за 30 дней', client.get('/subscription').text)
        for changed in ({'inn': '123'}, {'email': 'fake email'}):
            self.assertEqual(client.put('/api/admin/merchant', headers=auth(42), json=body | changed).status_code, 422)
        client.close()

    def test_old_ambiguous_order_cannot_create_second_payment(self):
        import asyncio
        order = self.order()
        order['created'] = int(time.time()) - DAY
        with self.assertRaises(ValueError), patch.object(YooKassa, 'request', AsyncMock()) as fetch:
            asyncio.run(YooKassa().sync(self.s, order))
        fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
