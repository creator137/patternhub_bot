"""First-party Mini App counters; no names, IP addresses or purchase claims."""
from datetime import datetime, timedelta, timezone

from app.database import Database


class AnalyticsRepository:
    def __init__(self, database: Database):
        self.database = database

    def record(self, user_id: int, event_id: str, kind: str,
               source: str | None = None, product_id: int | None = None):
        with self.database.connect() as db:
            # Resolve attribution on the server, never trust a client-supplied brand.
            if kind == 'outbound':
                if product_id is not None:
                    row = db.execute('''SELECT p.source FROM products p JOIN sources s ON s.name=p.source
                        LEFT JOIN product_overrides o ON o.product_id=p.id
                        WHERE p.id=? AND p.is_available=1 AND s.enabled=1 AND COALESCE(o.hidden,0)=0''', (product_id,)).fetchone()
                else:
                    row = db.execute('SELECT name FROM sources WHERE name=? AND enabled=1', (source,)).fetchone()
                if not row:
                    raise ValueError('Destination not found')
                source = row[0]
            else:
                source, product_id = None, None
            # Retried requests are idempotent, independent users cannot suppress one another.
            db.execute('''INSERT OR IGNORE INTO analytics_events
                (user_id,event_id,kind,source,product_id) VALUES(?,?,?,?,?)''',
                (user_id, event_id, kind, source, product_id))

    def summary(self, days: int):
        now = datetime.now(timezone.utc)
        start = (now.date() - timedelta(days=days - 1)).isoformat()
        with self.database.connect() as db:
            totals = dict(db.execute('''SELECT COUNT(DISTINCT user_id) AS users,
                COALESCE(SUM(kind='open'),0) AS opens,
                COALESCE(SUM(kind='outbound'),0) AS clicks,
                COUNT(DISTINCT CASE WHEN kind='outbound' THEN user_id END) AS outbound_users
                FROM analytics_events WHERE created_at>=?''', (start,)).fetchone())
            sources = [dict(row) for row in db.execute('''SELECT e.source,s.display_name AS name,
                COUNT(*) AS clicks,COUNT(DISTINCT e.user_id) AS users FROM analytics_events e
                JOIN sources s ON s.name=e.source WHERE e.kind='outbound' AND e.created_at>=?
                GROUP BY e.source ORDER BY clicks DESC,s.display_name''', (start,))]
            daily = {row['day']: dict(row) for row in db.execute('''SELECT date(created_at) AS day,
                COUNT(DISTINCT user_id) AS users, SUM(kind='open') AS opens,
                SUM(kind='outbound') AS clicks FROM analytics_events WHERE created_at>=?
                GROUP BY date(created_at)''', (start,))}
            since = db.execute('SELECT MIN(created_at) FROM analytics_events').fetchone()[0]
        dates = [(now.date() - timedelta(days=offset)).isoformat() for offset in reversed(range(days))]
        return dict(totals, days=days, since=since, timezone='UTC', sources=sources,
                    daily=[daily.get(day, dict(day=day, users=0, opens=0, clicks=0)) for day in dates])
