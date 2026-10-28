from __future__ import annotations

import json
import sqlite3
import time
import random
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

from app.database import Database
from app.models.audience import AUDIENCES
from app.models.categories import category_code, category_name_by_code
from app.models.product import (
    CatalogBrand,
    CatalogCategory,
    CatalogStats,
    ParsedProduct,
    Product,
    ProductFilter,
)
from app.models.catalog_policy import free_section_sql, new_section_sql, is_recent_publication, publication_datetime


class ProductRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_many(self, products: Iterable[ParsedProduct]) -> tuple[int, int]:
        added = 0
        updated = 0
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            authoritative = {(r['source'], r['field']) for r in connection.execute(
                "SELECT source,field FROM source_filter_snapshots WHERE checked_at>=datetime('now','-1 day')")}
            for raw_product in products:
                product = raw_product.normalized()
                existing_id = self._find_existing_id(connection, product)
                values = self._values(product)
                if existing_id is not None:
                    for field in ('is_beginner', 'is_knit', 'sizes', 'heights', 'difficulty', 'description', 'source_published_at'):
                        if getattr(product, field) is None:
                            values.pop(field, None)
                    for field in ('is_beginner', 'is_knit', 'is_new'):
                        if values.get(field) == 0 and (product.source, field) in authoritative:
                            values.pop(field, None)
                if product.image_urls:
                    values["image_urls"] = json.dumps(product.image_urls, ensure_ascii=False)
                    values['gallery_checked_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
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
            connection.execute(f'UPDATE products SET is_new={new_section_sql()} WHERE is_new!={new_section_sql()}')
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

    def list_brands(self, filters: ProductFilter | None = None) -> list[CatalogBrand]:
        where, parameters = self._where(filters)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT source,
                       COALESCE(NULLIF(TRIM(brand), ''), source) AS brand_name,
                       COUNT(*) AS count
                FROM products
                {where}
                GROUP BY source, brand_name
                ORDER BY brand_name
                """,
                parameters,
            ).fetchall()
        return [
            CatalogBrand(
                source=row["source"],
                name=row["brand_name"],
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

    def set_photo_file_id(
        self,
        product_id: int,
        file_id: str,
        *,
        status: str = "telegram_file_id",
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE products
                SET telegram_file_id = ?,
                    image_status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (file_id, status, product_id),
            )

    def set_image_status(self, product_id: int, status: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE products
                SET image_status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, product_id),
            )

    def set_gallery(self, product_id: int, urls: Iterable[str], *, expected_url: str) -> None:
        images = tuple(dict.fromkeys(urls))
        if not images:
            return
        with self.database.connect() as db:
            db.execute("""UPDATE products SET image_urls=?, image_url=?,
                telegram_file_id=CASE WHEN image_url=? THEN telegram_file_id ELSE NULL END,
                image_status=CASE WHEN image_url=? THEN image_status ELSE NULL END,
                gallery_checked_at=CURRENT_TIMESTAMP
                WHERE id=? AND product_url=?""",
                (json.dumps(images, ensure_ascii=False), images[0], images[0], images[0], product_id, expected_url))
            db.execute('DELETE FROM media_gallery_jobs WHERE product_id=?', (product_id,))

    def gallery_failed(self, product_id: int, error: str):
        with self.database.connect() as db:
            row = db.execute('SELECT attempts FROM media_gallery_jobs WHERE product_id=?', (product_id,)).fetchone()
            attempts = (row[0] if row else 0) + 1
            deadline = time.time() + min(21600, 60 * 2 ** min(attempts, 9) * random.uniform(.8, 1.2))
            db.execute('INSERT INTO media_gallery_jobs(product_id,attempts,next_attempt,last_error) VALUES(?,?,?,?) '
                'ON CONFLICT(product_id) DO UPDATE SET attempts=excluded.attempts,next_attempt=excluded.next_attempt,last_error=excluded.last_error',
                (product_id, attempts, deadline, error[:100]))

    def set_filter_metadata(self, product_id: int, facts: dict, *, expected_url: str):
        allowed = {'is_beginner', 'is_knit', 'difficulty', 'description', 'source_published_at'}
        if set(facts) - allowed:
            raise ValueError('Unsupported detail fact')
        values = {key: int(value) if key.startswith('is_') else value
                  for key, value in facts.items() if value is not None}
        if 'source_published_at' in values:
            published = publication_datetime(values['source_published_at'])
            if published is None:
                raise ValueError('Invalid source publication date')
            values['source_published_at'] = published.isoformat()
        with self.database.connect() as db:
            # A current, complete source section outranks absence of a tag on a
            # detail page. Positive detail evidence can still extend coverage.
            authoritative = {r[0] for r in db.execute('''SELECT f.field FROM source_filter_snapshots f
                JOIN products p ON p.source=f.source WHERE p.id=?
                AND f.checked_at>=datetime('now','-1 day')''', (product_id,))}
            values = {key:value for key,value in values.items() if key not in authoritative or value != 0}
            assignments = [f'{key}=?' for key in values]
            # A bulk date lookup is not a detail-page filter audit.
            if set(facts) != {'source_published_at'}:
                assignments.append('filters_checked_at=CURRENT_TIMESTAMP')
            if not assignments:
                return
            db.execute(f"UPDATE products SET {','.join(assignments)} WHERE id=? AND product_url=?",
                       (*values.values(), product_id, expected_url))
            if 'source_published_at' in values:
                db.execute(f'UPDATE products SET is_new={new_section_sql()} WHERE id=?', (product_id,))

    def apply_filter_snapshot(self, source: str, field: str, snapshot) -> int:
        if field not in {'is_beginner','is_knit'}:
            raise ValueError('Unsupported membership filter')
        if not snapshot.products:
            return 0  # Empty/blocked pages must never clear existing facts.
        if any(p.source.casefold() != source.casefold() for p in snapshot.products):
            raise ValueError('Filter snapshot contains another source')
        with self.database.connect() as db:
            db.execute('CREATE TEMP TABLE filter_keys (source_id TEXT, url TEXT)')
            db.executemany('INSERT INTO filter_keys VALUES (?,?)',
                [(p.source_product_id,p.product_url) for p in snapshot.products])
            previous = db.execute(f'SELECT COUNT(*) FROM products WHERE source=? AND {field}=1', (source,)).fetchone()[0]
            matched = db.execute('''SELECT COUNT(*) FROM products WHERE source=? AND EXISTS (
                SELECT 1 FROM filter_keys k WHERE k.source_id=products.source_product_id OR k.url=products.product_url)''', (source,)).fetchone()[0]
            safe_complete = snapshot.complete and not (previous > 20 and matched < previous / 2)
            logging.info('Filter membership source=%s field=%s found=%s matched=%s complete=%s',
                source,field,len(snapshot.products),matched,safe_complete)
            if snapshot.complete and not safe_complete:
                logging.warning('Refusing to clear filter source=%s field=%s previous=%s matched=%s', source,field,previous,matched)
            fallback = '0' if safe_complete else field
            changed = db.execute(f'''UPDATE products SET {field}=CASE WHEN EXISTS (
                SELECT 1 FROM filter_keys k WHERE k.source_id=products.source_product_id OR k.url=products.product_url)
                THEN 1 ELSE {fallback} END WHERE source=?''', (source,)).rowcount
            if safe_complete:
                db.execute('''INSERT INTO source_filter_snapshots(source,field) VALUES(?,?)
                    ON CONFLICT(source,field) DO UPDATE SET checked_at=CURRENT_TIMESTAMP''', (source,field))
            db.execute('DROP TABLE filter_keys')
        return changed

    def media_products(self, *, product_id: int | None = None, source: str | None = None,
                       galleries: bool = False, filters_only: bool = False, limit: int = 10000) -> list[Product]:
        clauses = ["p.is_available=1", "s.enabled=1"]
        values: list[object] = []
        for key, value in (("id", product_id), ("source", source)):
            if value is not None:
                clauses.append(f"p.{key}=?")
                values.append(value)
        if (galleries or filters_only) and product_id is None:
            clauses.append("(p.filters_checked_at IS NULL OR p.filters_checked_at < datetime('now','-7 day'))" if filters_only else
                "(p.filters_checked_at IS NULL OR p.filters_checked_at < datetime('now','-7 day') OR p.gallery_checked_at IS NULL OR p.gallery_checked_at < datetime('now','-1 day'))")
            clauses.append("NOT EXISTS (SELECT 1 FROM media_gallery_jobs j WHERE j.product_id=p.id AND j.next_attempt>?)")
            values.append(time.time())
        order = ('ROW_NUMBER() OVER (PARTITION BY p.source ORDER BY p.filters_checked_at IS NOT NULL,p.gallery_checked_at IS NOT NULL,p.name,p.id),p.source'
                 if galleries else 'p.name,p.id')
        with self.database.connect() as db:
            rows = db.execute(f"""SELECT p.* FROM products p JOIN sources s ON s.name=p.source
                WHERE {' AND '.join(clauses)} ORDER BY {order} LIMIT ?""",
                (*values, limit)).fetchall()
        return [self._to_product(row) for row in rows]

    def cover_product_ids(self, image_url: str) -> list[int]:
        with self.database.connect() as db:
            return [row[0] for row in db.execute('SELECT id FROM products WHERE image_url=? AND is_available=1', (image_url,))]

    def request_gallery_repair(self, image_url: str):
        with self.database.connect() as db:
            db.execute("""UPDATE products SET gallery_checked_at=NULL WHERE image_url=? OR EXISTS (
                SELECT 1 FROM json_each(COALESCE(products.image_urls,'[]')) WHERE value=?)""", (image_url, image_url))

    def products_with_image(self, image_url: str) -> list[Product]:
        with self.database.connect() as db:
            rows = db.execute("""SELECT p.* FROM products p JOIN sources s ON s.name=p.source
                WHERE p.is_available=1 AND s.enabled=1 AND (p.image_url=? OR EXISTS (
                SELECT 1 FROM json_each(COALESCE(p.image_urls,'[]')) WHERE value=?))""", (image_url, image_url)).fetchall()
        return [self._to_product(row) for row in rows]

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
                f"""
                SELECT COUNT(*) AS products,
                       COALESCE(SUM(is_sale), 0) AS on_sale,
                       COALESCE(SUM({new_section_sql()}), 0) AS new,
                       COALESCE(SUM(is_free), 0) AS free,
                       COALESCE(SUM(is_beginner), 0) AS beginner,
                       COALESCE(SUM(is_knit), 0) AS knit,
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
            beginner=totals["beginner"],
            knit=totals["knit"],
            categories=totals["categories"],
            no_price=totals["no_price"],
            no_image=totals["no_image"],
            by_audience=by_audience,
        )

    def publication_stats(self):
        with self.database.connect() as db:
            return [dict(r) for r in db.execute(f'''SELECT source,COUNT(*) AS products,
                SUM(source_published_at IS NOT NULL) AS dated,
                SUM({new_section_sql()}) AS recent FROM products
                WHERE is_available=1 GROUP BY source ORDER BY source''')]

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
                clauses.append(f"{free_section_sql()} = ?")
                parameters.append(int(filters.is_free))
            if filters.is_new is not None:
                clauses.append(f"{new_section_sql()} = ?")
                parameters.append(int(filters.is_new))
            if filters.is_beginner is not None:
                clauses.append("is_beginner = ?")
                parameters.append(int(filters.is_beginner))
            if filters.is_knit is not None:
                clauses.append("is_knit = ?")
                parameters.append(int(filters.is_knit))
        return f"WHERE {' AND '.join(clauses)}", tuple(parameters)

    @staticmethod
    def _text_filter_clause(
        columns: tuple[str, ...], markers: tuple[str, ...]
    ) -> tuple[str, tuple[str, ...]]:
        parts: list[str] = []
        parameters: list[str] = []
        for column in columns:
            for marker in markers:
                parts.append(f"COALESCE({column}, '') LIKE ?")
                parameters.append(f"%{marker}%")
        return f"({' OR '.join(parts)})", tuple(parameters)

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
            "source_new_badge": int(bool(product.source_new_badge)),
            "is_beginner": int(bool(product.is_beginner)),
            "is_knit": int(bool(product.is_knit)),
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
            "source_published_at": product.source_published_at.isoformat() if product.source_published_at else None,
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
            is_new=is_recent_publication(row['source_published_at']),
            source_new_badge=bool(row['source_new_badge']),
            source_published_at=publication_datetime(row['source_published_at']),
            is_beginner=bool(row["is_beginner"]),
            is_knit=bool(row["is_knit"]),
            sizes=tuple(json.loads(row["sizes"])) if row["sizes"] else None,
            heights=tuple(json.loads(row["heights"])) if row["heights"] else None,
            difficulty=row["difficulty"],
            description=row["description"],
            product_url=row["product_url"],
            image_url=row["image_url"],
            image_urls=tuple(json.loads(row["image_urls"])) if row["image_urls"] else None,
            telegram_file_id=row["telegram_file_id"],
            image_status=row["image_status"],
            is_available=bool(row["is_available"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            source_updated_at=(
                datetime.fromisoformat(row["source_updated_at"])
                if row["source_updated_at"]
                else None
            ),
        )
