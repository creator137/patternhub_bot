from __future__ import annotations

import asyncio
import logging
from time import monotonic

from app.models.product import SyncStats
from app.providers.base import BaseProvider
from app.repositories.products import ProductRepository


logger = logging.getLogger(__name__)


class CatalogService:
    def __init__(self, repository: ProductRepository) -> None:
        self.repository = repository

    async def synchronize(self, provider: BaseProvider) -> SyncStats:
        started = monotonic()
        logger.info("Starting parser: %s", provider.source)
        result = await provider.fetch_products()
        logger.info("Parser %s found %d products", provider.source, len(result.products))
        added, updated = await asyncio.to_thread(
            self.repository.upsert_many, result.products
        )
        stats = SyncStats(
            source=provider.source,
            found=len(result.products),
            added=added,
            updated=updated,
            errors=result.errors,
            duration_seconds=monotonic() - started,
        )
        logger.info(
            "Parser %s complete: found=%d added=%d updated=%d errors=%d duration=%.2fs",
            stats.source,
            stats.found,
            stats.added,
            stats.updated,
            stats.errors,
            stats.duration_seconds,
        )
        return stats
