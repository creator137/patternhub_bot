from pathlib import Path
from typing import Literal
from uuid import uuid4
from urllib.parse import urlsplit
from contextlib import asynccontextmanager
import asyncio

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response
from fastapi import Request
from hashlib import sha256
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from app.config import load_settings
from app.database import Database
from app.models.categories import CATEGORIES
from app.web.auth import WebSettings, require_admin, require_user
from app.web.catalog import FILTERS, MENUS, COMMON_FILTERS, WebCatalogRepository, WebCatalogService, safe_url
from app.services.images import ImageCache, ImageUnavailable, image_key
from app.repositories.media import MediaRepository


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
    sort: Literal["name", "new_first", "price_asc", "price_desc"] = "name"
    ids: str | None = Field(None, max_length=6000, pattern=r"^[0-9]{1,12}(,[0-9]{1,12}){0,499}$")


class Toggle(BaseModel):
    enabled: bool


class FavoriteInput(BaseModel):
    saved: bool


class SourceInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    base_url: HttpUrl
    specialization: Literal['general','lingerie','kids','bags','pets'] = 'general'


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
    media_repo = MediaRepository(database)
    images = ImageCache(database.path.parent / "media", repository=media_repo)
    image_tasks: dict[tuple, asyncio.Task] = {}
    @asynccontextmanager
    async def lifespan(app):
        yield
        for task in list(image_tasks.values()):
            task.cancel()
        await asyncio.gather(*list(image_tasks.values()), return_exceptions=True)
        await images.aclose()
    app = FastAPI(title="allsewpattern Mini App", version="0.1.0", lifespan=lifespan)
    app.state.web_settings = web_settings or WebSettings.from_env()
    app.state.database = database
    app.state.catalog = WebCatalogService(repo)
    app.state.images = images

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/") and "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path.startswith('/assets/'):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        elif request.url.path in {'/', '/index.html'}:
            response.headers['Cache-Control'] = 'no-cache'
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

    @app.get("/api/products/{product_id}/image/{index}")
    async def image(request: Request, product_id: int, index: int, size: Literal['thumb', 'detail'] = 'thumb'):
        media = await asyncio.to_thread(repo.public_media, product_id)
        urls = media['urls']
        if index < 0 or index >= len(urls):
            raise HTTPException(404, 'Image not found')
        async def prepare_image():
            selected = urls[index]
            try:
                path = await images.get(selected, size, referer=media['referer'])
            except ImageUnavailable:
                if index != 0:
                    raise
                # A deleted cover must not hide the product's other real
                # photos. Bounded fallback shares the same persistent cache,
                # SSRF checks, cooldowns and in-flight request coalescing.
                for candidate in urls[1:4]:
                    try:
                        path = await images.get(candidate, size, referer=media['referer'])
                        selected = candidate
                        break
                    except ImageUnavailable:
                        continue
                else:
                    raise
            if index == 0:
                await asyncio.to_thread(media_repo.set_cover, product_id, image_key(selected))
            return path
        key = (product_id, urls[index], size)
        task = image_tasks.get(key)
        if task is None:
            task = asyncio.create_task(prepare_image())
            image_tasks[key] = task
            def finished(done):
                image_tasks.pop(key, None)
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(finished)
        try:
            path = await asyncio.wait_for(asyncio.shield(task), timeout=2)
        except (ImageUnavailable, TimeoutError, OSError):
            old = await asyncio.to_thread(media_repo.last_cover, product_id) if index == 0 else None
            choices = [images.cached_path(old['url'], kind) for kind in (size, 'thumb')] if old else []
            path = next((candidate for candidate in choices if candidate.is_file()), None)
            if path is None:
                raise HTTPException(503, 'Image is being prepared', headers={'Retry-After': '2'}) from None
        try:
            content = await asyncio.to_thread(path.read_bytes)
        except OSError:
            raise HTTPException(503, 'Image is being prepared', headers={'Retry-After': '2'}) from None
        etag = '"' + sha256(content).hexdigest() + '"'
        headers = {'Cache-Control': 'public, max-age=86400, stale-while-revalidate=604800, stale-if-error=604800', 'ETag': etag}
        if request.headers.get('if-none-match') == etag:
            return Response(status_code=304, headers=headers)
        return Response(content, media_type='image/webp', headers=headers)

    @app.get("/api/meta")
    def meta():
        facets = repo.page({"limit": 1})
        return {"ui": repo.public_settings(), "common_filters": COMMON_FILTERS,
                "supplier_count": len(repo.public_suppliers()),
                "coverage": repo.coverage(), "categories": facets["categories"], "brands": facets["brands"],
                "category_options": [c.name for c in CATEGORIES],
                "local_login": app.state.web_settings.environment == "local" and bool(app.state.web_settings.dev_key)}

    @app.get('/api/suppliers')
    async def public_suppliers():
        return await asyncio.to_thread(repo.public_suppliers)

    @app.get("/api/admin/session", dependencies=[Depends(require_admin)])
    def session():
        return {"admin": True}

    @app.get('/api/favorites')
    def favorites(user_id: int = Depends(require_user)):
        with database.connect() as db:
            rows = db.execute("""SELECT f.product_id FROM favorites f JOIN products p ON p.id=f.product_id
                JOIN sources s ON s.name=p.source LEFT JOIN product_overrides o ON o.product_id=p.id
                WHERE f.user_id=? AND p.is_available=1 AND s.enabled=1 AND COALESCE(o.hidden,0)=0
                ORDER BY f.created_at DESC, f.product_id DESC LIMIT 500""", (user_id,)).fetchall()
        return {'ids': [row[0] for row in rows]}

    @app.put('/api/favorites/{product_id}')
    def favorite(product_id: int, value: FavoriteInput, user_id: int = Depends(require_user)):
        if value.saved and not repo.page({'id': product_id, 'limit': 1})['total']:
            raise HTTPException(404, 'Product not found')
        with database.connect() as db:
            if value.saved:
                count = db.execute('SELECT COUNT(*) FROM favorites WHERE user_id=?', (user_id,)).fetchone()[0]
                if count >= 500:
                    exists = db.execute('SELECT 1 FROM favorites WHERE user_id=? AND product_id=?', (user_id, product_id)).fetchone()
                    if not exists:
                        raise HTTPException(409, 'Favorites limit reached')
                db.execute('INSERT OR IGNORE INTO favorites(user_id,product_id) VALUES(?,?)', (user_id, product_id))
            else:
                db.execute('DELETE FROM favorites WHERE user_id=? AND product_id=?', (user_id, product_id))
        return {'saved': value.saved}

    @app.get("/api/admin/sources", dependencies=[Depends(require_admin)])
    def sources():
        return repo.sources()

    @app.get('/api/admin/media', dependencies=[Depends(require_admin)])
    async def media_stats():
        return await asyncio.to_thread(media_repo.dashboard)

    @app.post("/api/admin/sources", dependencies=[Depends(require_admin)], status_code=201)
    def add_source(value: SourceInput):
        url = safe_url(str(value.base_url))
        if not url:
            raise HTTPException(422, "HTTP(S) URL without credentials required")
        with database.connect() as db:
            host = urlsplit(url).hostname.removeprefix('www.')
            if any(urlsplit(row[0]).hostname.removeprefix('www.') == host for row in db.execute('SELECT base_url FROM sources')):
                raise HTTPException(409,'Этот сайт уже добавлен')
            db.execute("INSERT INTO sources(name,display_name,base_url,enabled,catalog_url,specialization) VALUES(?,?,?,0,?,?)",
                       ("site_" + uuid4().hex[:16], value.display_name.strip(), url, url, value.specialization))
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
