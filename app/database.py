from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
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
                    UNIQUE(source, source_product_id),
                    UNIQUE(source, product_url)
                );

                CREATE INDEX IF NOT EXISTS idx_products_source
                    ON products(source);
                CREATE INDEX IF NOT EXISTS idx_products_category
                    ON products(category);
                """
            )
            self._ensure_column(connection, "products", "is_new", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "products", "audience", "TEXT")
            self._ensure_column(connection, "products", "telegram_file_id", "TEXT")
            self._ensure_column(connection, "products", "image_status", "TEXT")
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
                UPDATE products
                SET is_beginner = CASE
                        WHEN lower(coalesce(difficulty, '') || ' ' ||
                                   coalesce(description, '') || ' ' ||
                                   coalesce(name, '') || ' ' ||
                                   coalesce(subcategory, '')) LIKE '%начинающ%'
                          OR lower(coalesce(difficulty, '') || ' ' ||
                                   coalesce(description, '') || ' ' ||
                                   coalesce(name, '') || ' ' ||
                                   coalesce(subcategory, '')) LIKE '%легк%'
                          OR lower(coalesce(difficulty, '') || ' ' ||
                                   coalesce(description, '') || ' ' ||
                                   coalesce(name, '') || ' ' ||
                                   coalesce(subcategory, '')) LIKE '%простой%'
                          OR lower(coalesce(difficulty, '') || ' ' ||
                                   coalesce(description, '') || ' ' ||
                                   coalesce(name, '') || ' ' ||
                                   coalesce(subcategory, '')) LIKE '%простая%'
                        THEN 1 ELSE is_beginner END,
                    is_knit = CASE
                        WHEN lower(coalesce(category, '') || ' ' ||
                                   coalesce(subcategory, '') || ' ' ||
                                   coalesce(description, '') || ' ' ||
                                   coalesce(name, '')) LIKE '%трикотаж%'
                        THEN 1 ELSE is_knit END
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
                        0,
                    ),
                    ("sewitnow", "SewItNow", "https://sewitnow.ru", 1),
                ),
            )
            connection.execute("UPDATE sources SET enabled = 1 WHERE name = 'grasser'")
            connection.execute("UPDATE sources SET enabled = 1 WHERE name = 'helpersew'")
            connection.execute(
                "UPDATE sources SET enabled = 1 WHERE name = 'studio_yusupova'"
            )
            connection.execute(
                """
                UPDATE sources
                SET display_name = 'SewItNow',
                    base_url = 'https://sewitnow.ru',
                    enabled = 1
                WHERE name = 'sewitnow'
                """
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()
