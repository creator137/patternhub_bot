"""Refresh publisher dates only; never reconcile product availability."""

import argparse
import asyncio
import logging

from app.config import load_settings
from app.database import Database
from app.providers.registry import available_providers, create_provider
from app.repositories.products import ProductRepository
from app.services.catalog import CatalogService


async def refresh(source: str) -> int:
    db = Database(load_settings(require_token=False).database_path)
    db.initialize()
    result = await CatalogService(ProductRepository(db)).enrich_publications(
        create_provider(source)
    )
    print(result)
    return int(bool(result["products"]) and not result["dated"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", choices=available_providers())
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    raise SystemExit(asyncio.run(refresh(parser.parse_args().source)))
