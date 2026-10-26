"""Sequential catalog refresh with a local SQLite backup before importing."""
import asyncio
from datetime import datetime, timezone
import logging
import sqlite3

from app.config import load_settings
from app.database import Database
from app.providers.registry import available_providers, create_provider
from app.repositories.products import ProductRepository
from app.services.catalog import CatalogService


async def refresh() -> int:
    config = load_settings(require_token=False)
    database = Database(config.database_path)
    database.initialize()
    backup_dir = config.database_path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    with sqlite3.connect(backup_dir / f"catalog-{stamp}.sqlite3") as target:
        with database.connect() as source:
            source.backup(target)
    for old in sorted(backup_dir.glob("catalog-*.sqlite3"))[:-7]:
        old.unlink()
    service = CatalogService(ProductRepository(database))
    with database.connect() as db:
        enabled = {row[0] for row in db.execute("SELECT name FROM sources WHERE enabled=1")}
    failures = 0
    for source in available_providers():
        if source not in enabled:
            continue
        try:
            result = await service.synchronize(create_provider(source))
            logging.info("Refresh result: %s", result)
            failures += bool(result.errors or not result.complete)
        except Exception as exc:
            failures += 1
            logging.error("Refresh failed for %s: %s", source, type(exc).__name__)
    return int(bool(failures))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(asyncio.run(refresh()))
