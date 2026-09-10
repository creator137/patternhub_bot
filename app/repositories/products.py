from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from app.database import Database
from app.models.product import CatalogStats, ParsedProduct, Product


class ProductRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_many(self, products: Iterable[ParsedProduct]) -> tuple[int, int]:
        added = 0
        updated = 0
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for raw_product in products:
                product = raw_product.normalized()
                existing_id = self._find_existing_id(connection, product)
                values = self._values(product)
                if existing_id is None:
                    connection.execute(
                        f"INSERT INTO products ({', '.join(values)}) "
                        f"VALUES ({', '.join('?' for _ in values)})",
                        tuple(values.values()),
                    )
                    added += 1
                else:
                    assignments = ", ".join(f"{column} = ?" for column in values)
                    connection.execute(
                        f"UPDATE products SET {assignments}, updated_at = CURRENT_TIMESTAMP "
                        "WHERE id = ?",
                        (*values.values(), existing_id),
                    )
                    updated += 1
        return added, updated

    def list_products(self, limit: int = 10) -> list[Product]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM products ORDER BY id LIMIT ?", (limit,)
            ).fetchall()
        return [self._to_product(row) for row in rows]

    def stats(self) -> CatalogStats:
        with self.database.connect() as connection:
            totals = connection.execute(
                """
                SELECT COUNT(*) AS products,
                       COALESCE(SUM(is_sale), 0) AS on_sale,
                       COALESCE(SUM(is_free), 0) AS free
                FROM products
                """
            ).fetchone()
            source_rows = connection.execute(
                "SELECT source, COUNT(*) AS count FROM products GROUP BY source ORDER BY source"
            ).fetchall()
        return CatalogStats(
            products=totals["products"],
            by_source={row["source"]: row["count"] for row in source_rows},
            on_sale=totals["on_sale"],
            free=totals["free"],
        )

    @staticmethod
    def _find_existing_id(
        connection: sqlite3.Connection, product: ParsedProduct
    ) -> int | None:
        if product.source_product_id:
            row = connection.execute(
                "SELECT id FROM products WHERE source = ? AND source_product_id = ?",
                (product.source, product.source_product_id),
            ).fetchone()
            if row:
                return row["id"]
        row = connection.execute(
            "SELECT id FROM products WHERE source = ? AND product_url = ?",
            (product.source, product.product_url),
        ).fetchone()
        return row["id"] if row else None

    @staticmethod
    def _values(product: ParsedProduct) -> dict[str, object]:
        return {
            "source": product.source,
            "source_product_id": product.source_product_id,
            "name": product.name,
            "brand": product.brand,
            "category": product.category,
            "subcategory": product.subcategory,
            "price": str(product.price) if product.price is not None else None,
            "old_price": str(product.old_price) if product.old_price is not None else None,
            "currency": product.currency,
            "is_sale": int(product.is_sale),
            "is_free": int(product.is_free),
            "sizes": json.dumps(product.sizes, ensure_ascii=False) if product.sizes else None,
            "heights": json.dumps(product.heights, ensure_ascii=False) if product.heights else None,
            "difficulty": product.difficulty,
            "description": product.description,
            "product_url": product.product_url,
            "image_url": product.image_url,
            "is_available": int(product.is_available),
            "source_updated_at": (
                product.source_updated_at.isoformat()
                if product.source_updated_at is not None
                else None
            ),
        }

    @staticmethod
    def _to_product(row: sqlite3.Row) -> Product:
        return Product(
            id=row["id"],
            source=row["source"],
            source_product_id=row["source_product_id"],
            name=row["name"],
            brand=row["brand"],
            category=row["category"],
            subcategory=row["subcategory"],
            price=Decimal(row["price"]) if row["price"] is not None else None,
            old_price=(
                Decimal(row["old_price"]) if row["old_price"] is not None else None
            ),
            currency=row["currency"],
            is_sale=bool(row["is_sale"]),
            is_free=bool(row["is_free"]),
            sizes=tuple(json.loads(row["sizes"])) if row["sizes"] else None,
            heights=tuple(json.loads(row["heights"])) if row["heights"] else None,
            difficulty=row["difficulty"],
            description=row["description"],
            product_url=row["product_url"],
            image_url=row["image_url"],
            is_available=bool(row["is_available"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            source_updated_at=(
                datetime.fromisoformat(row["source_updated_at"])
                if row["source_updated_at"]
                else None
            ),
        )
