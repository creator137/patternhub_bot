"""One-time trial and renewable access. Money is stored in integer kopecks."""
from __future__ import annotations

import json
import time
from decimal import Decimal
from uuid import uuid4

from app.database import Database

DAY = 86400
DEFAULT_PLAN = {"enabled": False, "price_kopecks": 0, "terms_url": "", "support_url": ""}


class SubscriptionService:
    def __init__(self, database: Database):
        self.db = database

    def initialize(self):
        with self.db.connect() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS subscription_users (
                    user_id INTEGER PRIMARY KEY, trial_end INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subscription_orders (
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL, days INTEGER NOT NULL DEFAULT 30,
                    test INTEGER NOT NULL, created INTEGER NOT NULL,
                    terms_url TEXT NOT NULL, return_url TEXT NOT NULL,
                    provider_id TEXT UNIQUE, checkout_url TEXT,
                    status TEXT NOT NULL DEFAULT 'pending', paid_at INTEGER,
                    refunded INTEGER NOT NULL DEFAULT 0,
                    checked INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS subscription_orders_user ON subscription_orders(user_id);
            """)
            columns = {row[1] for row in c.execute('PRAGMA table_info(subscription_orders)')}
            if 'checked' not in columns:
                c.execute('ALTER TABLE subscription_orders ADD COLUMN checked INTEGER NOT NULL DEFAULT 0')

    def plan(self):
        with self.db.connect() as c:
            row = c.execute("SELECT value FROM settings WHERE key='subscription.plan'").fetchone()
        plan = DEFAULT_PLAN | (json.loads(row[0]) if row else {})
        plan['terms_url'] = plan.get('terms_url') or '/terms'
        plan['support_url'] = plan.get('support_url') or '/seller'
        return plan

    def save_plan(self, plan):
        with self.db.connect() as c:
            c.execute("INSERT INTO settings(key,value) VALUES('subscription.plan',?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",
                      (json.dumps(plan),))

    def status(self, user_id, *, now=None, test=False):
        now = int(time.time()) if now is None else now
        with self.db.connect() as c:
            row = c.execute("SELECT trial_end FROM subscription_users WHERE user_id=?", (user_id,)).fetchone()
            trial_end = row[0] if row else 0
            payments = c.execute("SELECT paid_at,days FROM subscription_orders WHERE user_id=? "
                                 "AND status='succeeded' AND refunded=0 AND test=? ORDER BY paid_at,id",
                                 (user_id, int(test))).fetchall()
        end = trial_end
        for payment in payments:
            end = max(end, payment['paid_at']) + payment['days'] * DAY
        return {"trial_available": not bool(row), "trial_end": trial_end or None,
                "access_until": end or None, "has_access": end > now,
                "state": "paid" if payments and end > now else "trial" if trial_end > now else "expired" if row or payments else "new"}

    def start_trial(self, user_id, *, now=None):
        now = int(time.time()) if now is None else now
        with self.db.connect() as c:
            c.execute("INSERT OR IGNORE INTO subscription_users(user_id,trial_end) VALUES(?,?)", (user_id, now + 7 * DAY))

    def order(self, order_id, user_id=None):
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM subscription_orders WHERE id=?", (order_id,)).fetchone()
        if not row or (user_id is not None and row['user_id'] != user_id):
            raise ValueError("Платёж не найден")
        return dict(row)

    def new_order(self, user_id, test, return_url):
        now = int(time.time())
        plan = self.plan()
        with self.db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            # Reuse an unfinished checkout, including after a provider timeout.
            row = c.execute("SELECT id FROM subscription_orders WHERE user_id=? AND test=? "
                            "AND status='pending' AND created>? ORDER BY created DESC LIMIT 1",
                            (user_id, int(test), now - 3600)).fetchone()
            if row:
                return row[0]
            order_id = str(uuid4())
            c.execute("INSERT INTO subscription_orders(id,user_id,amount,test,created,terms_url,return_url) "
                      "VALUES(?,?,?,?,?,?,?)", (order_id, user_id, plan['price_kopecks'], int(test), now, plan['terms_url'], return_url))
        return order_id

    def verify(self, order, remote):
        try:
            amount = Decimal(remote['amount']['value']) * 100
            valid = (amount == order['amount'] and remote['amount']['currency'] == 'RUB'
                     and type(remote['test']) is bool and remote['test'] == bool(order['test'])
                     and remote['metadata']['order_id'] == order['id']
                     and remote['metadata']['user_id'] == str(order['user_id'])
                     and isinstance(remote['id'], str)
                     and (not order['provider_id'] or remote['id'] == order['provider_id']))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            valid = False
        if not valid:
            raise ValueError('Данные платежа не совпадают с заказом')

    def settle(self, order_id, remote):
        with self.db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            order = dict(c.execute('SELECT * FROM subscription_orders WHERE id=?', (order_id,)).fetchone())
            self.verify(order, remote)
            status = remote['status']
            checkout = remote.get('confirmation', {}).get('confirmation_url')
            c.execute('UPDATE subscription_orders SET provider_id=?,checkout_url=COALESCE(?,checkout_url) WHERE id=?',
                      (remote['id'], checkout, order_id))
            if status == 'succeeded' and remote.get('paid') is True:
                # A customer who skipped the trial cannot activate it after paid access expires.
                c.execute('INSERT OR IGNORE INTO subscription_users(user_id,trial_end) VALUES(?,0)', (order['user_id'],))
                c.execute("UPDATE subscription_orders SET status='succeeded',paid_at=COALESCE(paid_at,?) WHERE id=?",
                          (int(time.time()), order_id))
                # Any refund revokes this access grant; partial refunds are not supported by this plan.
                refunded = Decimal(remote.get('refunded_amount', {}).get('value', '0')) > 0
                if refunded:
                    c.execute('UPDATE subscription_orders SET refunded=1 WHERE id=?', (order_id,))
            elif status == 'canceled' and order['status'] != 'succeeded':
                c.execute("UPDATE subscription_orders SET status='canceled' WHERE id=?", (order_id,))

    def pending(self):
        with self.db.connect() as c:
            return [dict(row) for row in c.execute("SELECT * FROM subscription_orders WHERE status='pending' "
                                                 "AND (provider_id IS NOT NULL OR created>?) ORDER BY checked,created LIMIT 100", (int(time.time()) - 23 * 3600,))]

    def mark_checked(self, order_id):
        with self.db.connect() as c:
            c.execute('UPDATE subscription_orders SET checked=? WHERE id=?', (int(time.time()), order_id))
