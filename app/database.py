from __future__ import annotations

import sqlite3
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate_product_identity()
        with self.connect() as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sources (
                    name TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL REFERENCES sources(name),
                    source_product_id TEXT,
                    name TEXT NOT NULL,
                    brand TEXT,
                    audience TEXT,
                    category TEXT,
                    subcategory TEXT,
                    price TEXT,
                    old_price TEXT,
                    currency TEXT,
                    is_sale INTEGER NOT NULL DEFAULT 0,
                    is_free INTEGER NOT NULL DEFAULT 0,
                    is_new INTEGER NOT NULL DEFAULT 0,
                    is_beginner INTEGER NOT NULL DEFAULT 0,
                    is_knit INTEGER NOT NULL DEFAULT 0,
                    sizes TEXT,
                    heights TEXT,
                    difficulty TEXT,
                    description TEXT,
                    product_url TEXT NOT NULL,
                    image_url TEXT,
                    telegram_file_id TEXT,
                    image_status TEXT,
                    is_available INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    source_updated_at TEXT,
                    UNIQUE(source, source_product_id)
                );

                CREATE INDEX IF NOT EXISTS idx_products_source
                    ON products(source);
                CREATE INDEX IF NOT EXISTS idx_products_source_url ON products(source,product_url);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_products_source_url_fallback
                    ON products(source,product_url) WHERE source_product_id IS NULL;
                CREATE INDEX IF NOT EXISTS idx_products_category
                    ON products(category);
                CREATE INDEX IF NOT EXISTS idx_products_image_url
                    ON products(image_url);
                CREATE INDEX IF NOT EXISTS idx_products_product_url
                    ON products(product_url);
                """
            )
            self._ensure_column(connection, "products", "is_new", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "products", "audience", "TEXT")
            self._ensure_column(connection, "products", "telegram_file_id", "TEXT")
            self._ensure_column(connection, "products", "image_status", "TEXT")
            self._ensure_column(connection, "products", "image_urls", "TEXT")
            self._ensure_column(connection, "products", "gallery_checked_at", "TEXT")
            self._ensure_column(connection, "products", "filters_checked_at", "TEXT")
            self._ensure_column(connection, "products", "source_published_at", "TEXT")
            self._ensure_column(connection, "products", "source_recency_rank", "INTEGER")
            self._ensure_column(connection, "products", "source_recency_basis", "TEXT")
            connection.execute('CREATE INDEX IF NOT EXISTS idx_products_recency ON products(source,source_recency_rank)')
            connection.execute('''CREATE TABLE IF NOT EXISTS source_recency_snapshots (
                source TEXT PRIMARY KEY REFERENCES sources(name), basis TEXT NOT NULL,
                products INTEGER NOT NULL, checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            connection.execute('SAVEPOINT publication_badges')
            try:
                if self._ensure_column(connection, 'products', 'source_new_badge', 'INTEGER NOT NULL DEFAULT 0'):
                    connection.execute('UPDATE products SET source_new_badge=is_new')
                    from app.models.catalog_policy import new_section_sql
                    connection.execute(f'UPDATE products SET is_new={new_section_sql()}')
                connection.execute('RELEASE publication_badges')
            except Exception:
                connection.execute('ROLLBACK TO publication_badges')
                connection.execute('RELEASE publication_badges')
                raise
            connection.execute('CREATE INDEX IF NOT EXISTS idx_products_published ON products(source_published_at)')
            connection.execute('''CREATE TABLE IF NOT EXISTS source_filter_snapshots (
                source TEXT NOT NULL REFERENCES sources(name), field TEXT NOT NULL,
                checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(source,field))''')
            connection.executescript("""CREATE TABLE IF NOT EXISTS media_assets (
                key TEXT PRIMARY KEY, url TEXT NOT NULL, referer TEXT,
                state TEXT NOT NULL DEFAULT 'pending', priority INTEGER NOT NULL DEFAULT 100,
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                lease_until REAL NOT NULL DEFAULT 0, lease_owner TEXT, last_success REAL NOT NULL DEFAULT 0,
                last_access REAL NOT NULL DEFAULT 0, last_error TEXT);
                CREATE INDEX IF NOT EXISTS idx_media_due ON media_assets(state,next_attempt,priority);
                CREATE TABLE IF NOT EXISTS product_media_cache (
                    product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
                    asset_key TEXT NOT NULL REFERENCES media_assets(key));
                CREATE TABLE IF NOT EXISTS media_gallery_jobs (
                    product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
                    attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                    last_error TEXT);
            """)
            connection.execute("""CREATE TABLE IF NOT EXISTS favorites (
                user_id INTEGER NOT NULL, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(user_id,product_id))""")
            self._ensure_column(connection, 'media_assets', 'lease_owner', 'TEXT')
            self._ensure_column(
                connection, "products", "is_beginner", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(
                connection, "products", "is_knit", "INTEGER NOT NULL DEFAULT 0"
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_products_flags
                    ON products(is_sale, is_free, is_new, is_beginner, is_knit)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_products_audience_category
                    ON products(audience, category)
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO sources
                    (name, display_name, base_url, enabled)
                VALUES (?, ?, ?, ?)
                """,
                (
                    ("vikisews", "VikiSews", "https://vikisews.com", 1),
                    ("grasser", "Grasser", "https://grasser.ru", 1),
                    ("helpersew", "HelperSew", "https://helpersew.com", 1),
                    (
                        "studio_yusupova",
                        "Studio Yusupova",
                        "https://studio-yusupova.ru",
                        1,
                    ),
                    ("sewitnow", "SewItNow", "https://sewitnow.ru", 1),
                ),
            )
            from app.suppliers import supplier_definitions
            self._ensure_column(connection, 'sources', 'catalog_url', 'TEXT')
            self._ensure_column(connection, 'sources', 'specialization', "TEXT NOT NULL DEFAULT 'general'")
            connection.executemany('''INSERT OR IGNORE INTO sources
                (name,display_name,base_url,enabled,catalog_url,specialization) VALUES(?,?,?,?,?,?)''',
                [(item['source'],item['display_name'],item['base_url'],int(item['enabled']),
                  item['catalog_url'],item['specialization']) for item in supplier_definitions()])
            connection.executemany('''UPDATE sources SET catalog_url=?,specialization=?
                WHERE name=? AND catalog_url IS NULL''',
                [(item['catalog_url'],item['specialization'],item['source']) for item in supplier_definitions()])
            if not connection.execute("SELECT 1 FROM settings WHERE key='taxonomy.bags.v1'").fetchone():
                from app.models.categories import normalize_product_category
                rows = connection.execute("SELECT id,name,category FROM products WHERE category='Аксессуары'").fetchall()
                connection.executemany('UPDATE products SET category=? WHERE id=?',
                    [(normalize_product_category(row['category'],row['name']), row['id']) for row in rows])
                connection.execute("INSERT INTO settings(key,value) VALUES('taxonomy.bags.v1','1')")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS product_overrides (
                    product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
                    hidden INTEGER NOT NULL DEFAULT 0,
                    category TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def _migrate_product_identity(self) -> None:
        """Replace URL-wide uniqueness with a fallback-only constraint.

        Preserve IDs, added columns, indexes and child foreign keys. SQLite
        cannot drop a table UNIQUE constraint without rebuilding the table.
        Foreign keys are disabled only on this migration connection, before
        its transaction, and checked before commit. Concurrent initializers
        recheck the schema after acquiring the write lock.
        """
        pattern = r',\s*UNIQUE\s*\(\s*source\s*,\s*product_url\s*\)'
        with self.connect() as db:
            row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='products'").fetchone()
            if not row or not re.search(pattern, row['sql'], re.I):
                return
            db.execute('PRAGMA foreign_keys=OFF')
            try:
                db.execute('BEGIN IMMEDIATE')
                sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='products'").fetchone()['sql']
                if not re.search(pattern, sql, re.I):
                    db.commit()
                    return
                sequence = db.execute("SELECT seq FROM sqlite_sequence WHERE name='products'").fetchone() if 'AUTOINCREMENT' in sql.upper() else None
                objects = [r['sql'] for r in db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='products' AND type IN ('index','trigger') AND sql IS NOT NULL")]
                sql = re.sub(pattern, '', sql, flags=re.I)
                sql, count = re.subn(r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?["`]?products["`]?',
                                     'CREATE TABLE products_identity_migration', sql, count=1, flags=re.I)
                if count != 1:
                    raise ValueError('Unrecognized products schema')
                columns = ','.join('"'+r['name'].replace('"','""')+'"' for r in db.execute('PRAGMA table_info(products)'))
                db.execute(sql)
                db.execute(f'INSERT INTO products_identity_migration ({columns}) SELECT {columns} FROM products')
                db.execute('DROP TABLE products')
                db.execute('ALTER TABLE products_identity_migration RENAME TO products')
                if sequence:
                    db.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name='products'",(sequence['seq'],))
                    db.execute("INSERT INTO sqlite_sequence(name,seq) SELECT 'products',? WHERE NOT EXISTS(SELECT 1 FROM sqlite_sequence WHERE name='products')",(sequence['seq'],))
                for statement in objects:
                    db.execute(statement)
                db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_products_source_url_fallback ON products(source,product_url) WHERE source_product_id IS NULL')
                db.execute('CREATE INDEX IF NOT EXISTS idx_products_source_url ON products(source,product_url)')
                if db.execute('PRAGMA foreign_key_check').fetchone():
                    raise ValueError('Foreign key validation failed after product migration')
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.execute('PRAGMA foreign_keys=ON')

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> bool:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            return True
        return False

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.create_function("casefold", 1, lambda value: (value or "").casefold())
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()
