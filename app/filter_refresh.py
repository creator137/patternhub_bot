"""Refresh source-owned filter sections without reimporting product records."""
import argparse
import asyncio
import logging
from app.config import load_settings
from app.database import Database
from app.repositories.products import ProductRepository
from app.providers.registry import create_provider, available_providers


async def refresh(source):
    db = Database(load_settings(require_token=False).database_path)
    db.initialize()
    repo = ProductRepository(db)
    provider = create_provider(source, request_delay=0, timeout=120)
    incomplete = False
    for field, snapshot in (await provider.fetch_filter_snapshots()).items():
        changed = await asyncio.to_thread(repo.apply_filter_snapshot, source, field, snapshot)
        logging.info('Source=%s field=%s found=%s complete=%s updated=%s', source,field,len(snapshot.products),snapshot.complete,changed)
        incomplete = incomplete or not snapshot.complete
    return int(incomplete)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', choices=available_providers())
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(refresh(parser.parse_args().source)))
