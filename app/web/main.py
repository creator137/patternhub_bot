from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from app.config import load_settings
from app.database import Database
from app.models.categories import CATEGORIES
from app.web.auth import WebSettings, require_admin
from app.web.catalog import FILTERS, MENUS, WebCatalogRepository, WebCatalogService, safe_url


class CatalogQuery(BaseModel):
    limit: int = Field(24, ge=1, le=60)
    offset: int = Field(0, ge=0, le=1000000)
    search: str = Field("", max_length=150)
    category: str | None = Field(None, max_length=150)
    source: str | None = Field(None, max_length=80)
    audience: Literal["women", "men", "kids", "unisex"] | None = None
    is_new: bool | None = None
    is_sale: bool | None = None
    is_free: bool | None = None
    is_beginner: bool | None = None
    is_knit: bool | None = None
    sort: Literal["name", "price_asc", "price_desc"] = "name"


class Toggle(BaseModel):
    enabled: bool


class SourceInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    base_url: HttpUrl


class UIItem(BaseModel):
    key: str
    enabled: bool


class UISettings(BaseModel):
    filters: list[UIItem]
    menu: list[UIItem]


class ProductOverride(BaseModel):
    hidden: bool
    category: str | None = None


def create_app(database: Database | None = None, web_settings: WebSettings | None = None):
    config = load_settings(require_token=False)
    database = database or Database(config.database_path)
    database.initialize()
    repo = WebCatalogRepository(database)
    app = FastAPI(title="PatternHub Mini App", version="0.1.0")
    app.state.web_settings = web_settings or WebSettings.from_env()
    app.state.catalog = WebCatalogService(repo)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/products")
    async def products(query: CatalogQuery = Depends()):
        return await app.state.catalog.browse(query.model_dump())

    @app.get("/api/products/{product_id}")
    async def product(product_id: int):
        result = (await app.state.catalog.browse({"id": product_id}))["items"]
        if not result:
            raise HTTPException(404, "Product not found")
        return result[0]

    @app.get("/api/meta")
    def meta():
        facets = repo.page({"limit": 1})
        return {"ui": repo.settings(), "coverage": repo.coverage(), "categories": facets["categories"], "brands": facets["brands"],
                "category_options": [c.name for c in CATEGORIES],
                "local_login": app.state.web_settings.environment == "local" and bool(app.state.web_settings.dev_key)}

    @app.get("/api/admin/session", dependencies=[Depends(require_admin)])
    def session():
        return {"admin": True}

    @app.get("/api/admin/sources", dependencies=[Depends(require_admin)])
    def sources():
        return repo.sources()

    @app.post("/api/admin/sources", dependencies=[Depends(require_admin)], status_code=201)
    def add_source(value: SourceInput):
        url = safe_url(str(value.base_url))
        if not url:
            raise HTTPException(422, "HTTP(S) URL without credentials required")
        with database.connect() as db:
            db.execute("INSERT INTO sources(name,display_name,base_url,enabled) VALUES(?,?,?,0)",
                       ("site_" + uuid4().hex[:16], value.display_name.strip(), url))
        return {"ok": True}

    @app.patch("/api/admin/sources/{source}", dependencies=[Depends(require_admin)])
    def toggle(source: str, value: Toggle):
        with database.connect() as db:
            cursor = db.execute("UPDATE sources SET enabled=?,updated_at=CURRENT_TIMESTAMP WHERE name=?", (value.enabled, source))
            if not cursor.rowcount:
                raise HTTPException(404, "Source not found")
        return {"ok": True}

    @app.put("/api/admin/settings", dependencies=[Depends(require_admin)])
    def settings(value: UISettings):
        for entries, keys in ((value.filters, FILTERS), (value.menu, MENUS)):
            if len(entries) != len(keys) or {x.key for x in entries} != set(keys):
                raise HTTPException(422, "Include each supported key exactly once")
        repo.save_settings(value.model_dump())
        return value

    @app.get("/api/admin/products", dependencies=[Depends(require_admin)])
    async def admin_products(query: CatalogQuery = Depends()):
        return await app.state.catalog.browse(query.model_dump(), admin=True)

    @app.patch("/api/admin/products/{product_id}", dependencies=[Depends(require_admin)])
    def override(product_id: int, value: ProductOverride):
        if value.category is not None and value.category not in {c.name for c in CATEGORIES}:
            raise HTTPException(422, "Choose an internal category")
        if repo.get_product(product_id) is None:
            raise HTTPException(404, "Product not found")
        with database.connect() as db:
            db.execute("INSERT INTO product_overrides(product_id,hidden,category) VALUES(?,?,?) ON CONFLICT(product_id) DO UPDATE SET hidden=excluded.hidden, category=excluded.category, updated_at=CURRENT_TIMESTAMP", (product_id, value.hidden, value.category))
        return {"ok": True}

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app
