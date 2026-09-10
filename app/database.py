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
                    category TEXT,
                    subcategory TEXT,
                    price TEXT,
                    old_price TEXT,
                    currency TEXT,
                    is_sale INTEGER NOT NULL DEFAULT 0,
                    is_free INTEGER NOT NULL DEFAULT 0,
                    sizes TEXT,
                    heights TEXT,
                    difficulty TEXT,
                    description TEXT,
                    product_url TEXT NOT NULL,
                    image_url TEXT,
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
            connection.executemany(
                """
                INSERT OR IGNORE INTO sources
                    (name, display_name, base_url, enabled)
                VALUES (?, ?, ?, ?)
                """,
                (
                    ("vikisews", "VikiSews", "https://vikisews.com", 1),
                    ("grasser", "Grasser", "https://grasser.ru", 0),
                    ("helpersew", "HelperSew", "https://helpersew.com", 0),
                    (
                        "studio_yusupova",
                        "Studio Yusupova",
                        "https://studio-yusupova.ru",
                        0,
                    ),
                    ("sewitnow", "Sew It Now", "https://sewitnow.ru", 0),
                ),
            )

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
