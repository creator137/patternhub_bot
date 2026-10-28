"""Apply a validated recent public crawl through the normal catalog pipeline.

Used for deployment after a staged crawl, so sites are not crawled twice merely
to copy already verified data to the VPS. Never reads a user's Telegram DB.
"""
import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from pathlib import Path
from urllib.parse import urlsplit

from app.config import load_settings
from app.database import Database
from app.models.catalog_policy import publication_datetime
from app.models.product import ParsedProduct
from app.providers.base import BaseProvider, ProviderResult
from app.providers.registry import available_providers
from app.repositories.products import ProductRepository
from app.services.catalog import CatalogService
from app.suppliers import supplier_definition


class SnapshotProvider(BaseProvider):
    def __init__(self, source, products, skipped=0):
        self.source, self.products, self.skipped = source, products, skipped

    async def fetch_products(self):
        return ProviderResult(self.products, skipped=self.skipped, complete=True)


def validate_document(document):
    if document.get('version') != 1 or not isinstance(document.get('sources'), list):
        raise ValueError('Unsupported snapshot format')
    now = datetime.now(timezone.utc)
    sources, seen = [], set()
    for entry in document['sources']:
        source = entry['source']
        observed = publication_datetime(entry.get('observed_at'))
        if (source not in available_providers() or source in seen or entry.get('complete') is not True
                or observed is None or not now-timedelta(days=1) <= observed <= now):
            raise ValueError('Unknown, stale, duplicate or incomplete source snapshot')
        seen.add(source)
        definition = supplier_definition(source)
        host = urlsplit(definition['base_url']).hostname.removeprefix('www.')
        products, keys, urls = [], set(), {}
        for raw in entry['products']:
            values = dict(raw)
            for field in ['price','old_price']:
                if values.get(field) is not None:
                    values[field] = Decimal(str(values[field]))
            for field in ['source_published_at','source_updated_at']:
                if values.get(field) is not None:
                    values[field] = publication_datetime(values[field])
                    if values[field] is None:
                        raise ValueError('Invalid date in snapshot')
            for field in ['sizes','heights','image_urls']:
                if values.get(field) is not None:
                    if not isinstance(values[field], list):
                        raise ValueError('Invalid list field in snapshot')
                    values[field] = tuple(values[field])
            product = ParsedProduct(**values).normalized()
            key = product.source_product_id or product.product_url
            if (product.source != source or key in keys or
                    (product.product_url in urls and (not product.source_product_id or not urls[product.product_url]))
                    or urlsplit(product.product_url).hostname.removeprefix('www.') != host):
                raise ValueError('Product identity/origin mismatch in snapshot')
            keys.add(key); urls[product.product_url]=product.source_product_id; products.append(product)
        if not products:
            raise ValueError('Empty complete snapshot')
        sources.append(SnapshotProvider(source, products, int(entry.get('skipped',0))))
    if not sources:
        raise ValueError('No source snapshots')
    return sources


async def apply_document(document, service):
    providers = validate_document(document)  # Validate every source before writing anything.
    return [await service.synchronize(provider) for provider in providers]


async def main(path, dry_run=False):
    document = json.loads(Path(path).read_text())
    providers = validate_document(document)
    if dry_run:
        print(json.dumps({p.source:len(p.products) for p in providers},ensure_ascii=False))
        return
    db = Database(load_settings(require_token=False).database_path)
    db.initialize()
    service = CatalogService(ProductRepository(db))
    for provider in providers:
        print(json.dumps(asdict(await service.synchronize(provider)),ensure_ascii=False),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('file')
    parser.add_argument('--dry-run',action='store_true')
    args = parser.parse_args()
    asyncio.run(main(args.file,args.dry_run))
