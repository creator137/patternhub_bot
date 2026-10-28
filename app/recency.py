"""Refresh manufacturer newest-first ordering without importing or hiding products."""
import argparse
import asyncio
import logging

from app.config import load_settings
from app.database import Database
from app.providers.registry import available_providers, create_provider
from app.repositories.products import ProductRepository
from app.services.catalog import CatalogService


async def refresh(sources):
    db = Database(load_settings(require_token=False).database_path)
    db.initialize()
    service = CatalogService(ProductRepository(db))
    failures = 0
    for source in sources:
        try:
            # Follow the site's own pagination sequentially; no parallel burst.
            result = await service.refresh_recency(create_provider(source, request_delay=1.0, max_pages=1000))
            print(result, flush=True)
            failures += not result['ranked']
        except Exception as error:
            failures += 1
            logging.error('Recency refresh failed source=%s error=%s', source, type(error).__name__)
    return int(bool(failures))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('sources', nargs='*', choices=available_providers())
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(refresh(args.sources or available_providers())))
