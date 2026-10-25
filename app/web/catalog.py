"""Web presentation queries over the existing repository, never a second import path."""
from dataclasses import asdict
import asyncio
import json
from urllib.parse import urlsplit

from app.repositories.products import ProductRepository
from app.providers.registry import available_providers
from app.services.catalog import CatalogService

FILTERS = ("search", "category", "source", "audience", "is_new", "is_sale", "is_free", "is_beginner", "is_knit", "sort")
MENUS = ("women", "men", "kids", "unisex")
SORTS = {"name": "p.name, p.id", "price_asc": "p.price IS NULL, CAST(p.price AS REAL), p.id",
         "price_desc": "p.price IS NULL, CAST(p.price AS REAL) DESC, p.id"}


class WebCatalogService(CatalogService):
    """Adds presentation queries; inherits the single existing synchronization path."""
    async def browse(self, query, *, admin=False):
        return await asyncio.to_thread(self.repository.page, query, admin=admin)


def safe_url(value):
    try:
        url = urlsplit(value or "")
        return value if url.scheme in {"http", "https"} and url.hostname and not url.username and not url.password else None
    except ValueError:
        return None


class WebCatalogRepository(ProductRepository):
    def settings(self):
        with self.database.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='miniapp.ui'").fetchone()
        return json.loads(row[0]) if row else {
            "filters": [{"key": key, "enabled": True} for key in FILTERS],
            "menu": [{"key": key, "enabled": True} for key in MENUS],
        }

    def save_settings(self, value):
        with self.database.connect() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('miniapp.ui',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP", (json.dumps(value),))

    def page(self, query, *, admin=False):
        clauses, values = [], []
        if not admin:
            clauses.extend(["p.is_available=1", "s.enabled=1", "COALESCE(o.hidden,0)=0"])
        active = set(FILTERS) if admin else {x["key"] for x in self.settings()["filters"] if x["enabled"]}
        for key in ("source", "audience", "category", "is_new", "is_sale", "is_free", "is_beginner", "is_knit"):
            value = query.get(key)
            if key in active and value is not None and value != "":
                column = "COALESCE(o.category,p.category)" if key == "category" else f"p.{key}"
                clauses.append(f"{column}=?")
                values.append(value)
        if query.get("search") and "search" in active:
            clauses.append("instr(casefold(p.name),?)>0")
            values.append(query["search"].casefold())
        if query.get("id") is not None:
            clauses.append("p.id=?")
            values.append(query["id"])
        where = " AND ".join(clauses) or "1=1"
        base = "FROM products p JOIN sources s ON s.name=p.source LEFT JOIN product_overrides o ON o.product_id=p.id"
        order = SORTS.get(query.get("sort"), SORTS["name"]) if "sort" in active else SORTS["name"]
        with self.database.connect() as db:
            total = db.execute(f"SELECT COUNT(*) {base} WHERE {where}", values).fetchone()[0]
            rows = db.execute(f"SELECT p.*, COALESCE(o.category,p.category) AS effective_category, COALESCE(o.hidden,0) AS hidden, s.enabled AS source_enabled {base} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?", (*values, query.get("limit", 24), query.get("offset", 0))).fetchall()
            categories = [dict(r) for r in db.execute(f"SELECT COALESCE(o.category,p.category) AS name, COUNT(*) AS count {base} WHERE {where} GROUP BY 1 HAVING COALESCE(o.category,p.category) IS NOT NULL ORDER BY 1", values)]
            brands = [dict(r) for r in db.execute(f"SELECT s.name AS source, s.display_name AS name, COUNT(*) AS count {base} WHERE {where} GROUP BY s.name ORDER BY s.display_name", values)]
        items = []
        for row in rows:
            item = asdict(self._to_product(row))
            item.pop("telegram_file_id", None)
            item["category"] = row["effective_category"]
            item["product_url"] = safe_url(item["product_url"])
            item["image_url"] = safe_url(item["image_url"])
            item["new_basis"] = "source_label" if item["is_new"] else None
            if admin:
                item.update(hidden=bool(row["hidden"]), source_enabled=bool(row["source_enabled"]), imported_category=row["category"])
            items.append(item)
        return {"items": items, "total": total, "categories": categories, "brands": brands}

    def sources(self):
        with self.database.connect() as db:
            rows = db.execute("SELECT s.*, COUNT(p.id) AS products FROM sources s LEFT JOIN products p ON p.source=s.name GROUP BY s.name ORDER BY s.display_name").fetchall()
        return [dict(row) | {"parser_status": "connected" if row["name"] in available_providers() else "pending"} for row in rows]

    def coverage(self):
        with self.database.connect() as db:
            rows = db.execute("""SELECT p.* FROM products p JOIN sources s ON s.name=p.source
                LEFT JOIN product_overrides o ON o.product_id=p.id
                WHERE p.is_available=1 AND s.enabled=1 AND COALESCE(o.hidden,0)=0""").fetchall()
        counts = {key: sum(row["audience"] == key for row in rows) for key in MENUS}
        counts.update({key: sum(bool(row[key]) for row in rows) for key in FILTERS if key.startswith("is_")})
        return {"counts": counts, "unknown_audience": sum(not row["audience"] for row in rows), "total": len(rows)}
