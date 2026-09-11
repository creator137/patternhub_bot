from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from app.database import Database
from app.models.audience import AUDIENCES
from app.models.categories import category_code, category_name_by_code
from app.models.product import CatalogCategory, CatalogStats, ParsedProduct, Product, ProductFilter


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

    def list_categories(self, filters: ProductFilter | None = None) -> list[CatalogCategory]:
        where, parameters = self._where(filters)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT category, COUNT(*) AS count
                FROM products
                {where}
                GROUP BY category
                HAVING category IS NOT NULL AND TRIM(category) != ''
                ORDER BY category
                """,
                parameters,
            ).fetchall()
        return [
            CatalogCategory(
                code=self.category_code(row["category"]),
                name=row["category"],
                products=row["count"],
            )
            for row in rows
        ]

    def list_products(
        self,
        limit: int = 10,
        *,
        offset: int = 0,
        filters: ProductFilter | None = None,
    ) -> list[Product]:
        where, parameters = self._where(filters)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM products {where} ORDER BY name, id LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ).fetchall()
        return [self._to_product(row) for row in rows]

    def get_product(self, product_id: int) -> Product | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM products WHERE id = ?", (product_id,)
            ).fetchone()
        return self._to_product(row) if row else None

    def count_products(self, filters: ProductFilter | None = None) -> int:
        where, parameters = self._where(filters)
        with self.database.connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM products {where}", parameters
            ).fetchone()
        return int(row["count"])

    def stats(self) -> CatalogStats:
        with self.database.connect() as connection:
            availability = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       COALESCE(SUM(is_available = 1), 0) AS available,
                       COALESCE(SUM(is_available = 0), 0) AS unavailable
                FROM products
                """
            ).fetchone()
            totals = connection.execute(
                """
                SELECT COUNT(*) AS products,
                       COALESCE(SUM(is_sale), 0) AS on_sale,
                       COALESCE(SUM(is_new), 0) AS new,
                       COALESCE(SUM(is_free), 0) AS free,
                       COUNT(DISTINCT category) AS categories,
                       COALESCE(SUM(price IS NULL), 0) AS no_price,
                       COALESCE(SUM(image_url IS NULL), 0) AS no_image
                FROM products
                WHERE is_available = 1
                """
            ).fetchone()
            source_rows = connection.execute(
                """
                SELECT source, COUNT(*) AS count
                FROM products
                WHERE is_available = 1
                GROUP BY source
                ORDER BY source
                """
            ).fetchall()
            unavailable_source_rows = connection.execute(
                """
                SELECT source, COUNT(*) AS count
                FROM products
                WHERE is_available = 0
                GROUP BY source
                ORDER BY source
                """
            ).fetchall()
            audience_rows = connection.execute(
                """
                SELECT COALESCE(audience, 'unknown') AS audience, COUNT(*) AS count
                FROM products
                WHERE is_available = 1
                GROUP BY COALESCE(audience, 'unknown')
                ORDER BY audience
                """
            ).fetchall()
        by_audience = {audience: 0 for audience in (*AUDIENCES, "unknown")}
        by_audience.update({row["audience"]: row["count"] for row in audience_rows})
        return CatalogStats(
            products=totals["products"],
            total=availability["total"],
            available=availability["available"],
            unavailable=availability["unavailable"],
            by_source={row["source"]: row["count"] for row in source_rows},
            unavailable_by_source={
                row["source"]: row["count"] for row in unavailable_source_rows
            },
            on_sale=totals["on_sale"],
            new=totals["new"],
            free=totals["free"],
            categories=totals["categories"],
            no_price=totals["no_price"],
            no_image=totals["no_image"],
            by_audience=by_audience,
        )

    def mark_unavailable_missing(
        self, source: str, products: Iterable[ParsedProduct]
    ) -> int:
        normalized_products = [product.normalized() for product in products]
        if not normalized_products:
            return 0
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TEMP TABLE current_import_keys (
                    source_product_id TEXT,
                    product_url TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO current_import_keys (source_product_id, product_url)
                VALUES (?, ?)
                """,
                (
                    (product.source_product_id, product.product_url)
                    for product in normalized_products
                ),
            )
            cursor = connection.execute(
                """
                UPDATE products
                SET is_available = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE source = ?
                  AND is_available = 1
                  AND NOT EXISTS (
                      SELECT 1
                      FROM current_import_keys current
                      WHERE (
                          products.source_product_id IS NOT NULL
                          AND current.source_product_id = products.source_product_id
                      )
                      OR current.product_url = products.product_url
                  )
                """,
                (source,),
            )
            connection.execute("DROP TABLE current_import_keys")
        return cursor.rowcount

    def delete_source_products(
        self,
        source: str,
        *,
        source_product_ids: Iterable[str] = (),
        product_urls: Iterable[str] = (),
    ) -> int:
        deleted = 0
        with self.database.connect() as connection:
            for source_product_id in source_product_ids:
                cursor = connection.execute(
                    "DELETE FROM products WHERE source = ? AND source_product_id = ?",
                    (source, source_product_id),
                )
                deleted += cursor.rowcount
            for product_url in product_urls:
                cursor = connection.execute(
                    "DELETE FROM products WHERE source = ? AND product_url = ?",
                    (source, product_url),
                )
                deleted += cursor.rowcount
        return deleted

    @staticmethod
    def category_code(category: str) -> str:
        return category_code(category)

    @staticmethod
    def category_name_by_code(code: str) -> str | None:
        return category_name_by_code(code)

    @staticmethod
    def _where(filters: ProductFilter | None) -> tuple[str, tuple[object, ...]]:
        clauses = ["is_available = 1"]
        parameters: list[object] = []
        if filters is not None:
            if filters.source:
                clauses.append("source = ?")
                parameters.append(filters.source)
            if filters.audience:
                audiences = (
                    (filters.audience,)
                    if isinstance(filters.audience, str)
                    else filters.audience
                )
                placeholders = ", ".join("?" for _ in audiences)
                clauses.append(f"audience IN ({placeholders})")
                parameters.extend(audiences)
            if filters.category:
                clauses.append("category = ?")
                parameters.append(filters.category)
            if filters.is_sale is not None:
                clauses.append("is_sale = ?")
                parameters.append(int(filters.is_sale))
            if filters.is_free is not None:
                clauses.append("is_free = ?")
                parameters.append(int(filters.is_free))
            if filters.is_new is not None:
                clauses.append("is_new = ?")
                parameters.append(int(filters.is_new))
        return f"WHERE {' AND '.join(clauses)}", tuple(parameters)

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
            "audience": product.audience,
            "category": product.category,
            "subcategory": product.subcategory,
            "price": str(product.price) if product.price is not None else None,
            "old_price": str(product.old_price) if product.old_price is not None else None,
            "currency": product.currency,
            "is_sale": int(product.is_sale),
            "is_free": int(product.is_free),
            "is_new": int(product.is_new),
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
            audience=row["audience"],
            category=row["category"],
            subcategory=row["subcategory"],
            price=Decimal(row["price"]) if row["price"] is not None else None,
            old_price=(
                Decimal(row["old_price"]) if row["old_price"] is not None else None
            ),
            currency=row["currency"],
            is_sale=bool(row["is_sale"]),
            is_free=bool(row["is_free"]),
            is_new=bool(row["is_new"]),
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
