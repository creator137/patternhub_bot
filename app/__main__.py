from __future__ import annotations

import argparse
import asyncio
import logging

from app.config import load_settings
from app.database import Database
from app.models.categories import category_name_by_code, normalize_category
from app.providers.registry import available_providers
from app.repositories.products import ProductRepository
from app.repositories.settings import SettingsRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("show-chat-id", help="show the selected test chat_id")
    subparsers.add_parser("reset-chat-id", help="clear the selected test chat_id")
    set_parser = subparsers.add_parser(
        "set-chat-id", help="set the test chat_id manually"
    )
    set_parser.add_argument("chat_id", type=int)
    parse_parser = subparsers.add_parser("parse", help="synchronize a catalog source")
    parse_parser.add_argument("source", choices=available_providers())
    parse_parser.add_argument(
        "--enrich-details",
        action="store_true",
        help="fetch product detail pages when the provider supports it",
    )
    parse_parser.add_argument(
        "--detail-limit",
        type=positive_int,
        help="limit detail pages fetched with --enrich-details",
    )
    subparsers.add_parser("catalog-stats", help="show catalog statistics")
    products_parser = subparsers.add_parser("products", help="show saved products")
    products_parser.add_argument("--limit", type=positive_int, default=10)
    products_parser.add_argument("--audience", choices=("women", "men", "kids", "unisex"))
    products_parser.add_argument("--category")
    return parser


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def settings_repository() -> SettingsRepository:
    settings = load_settings(require_token=False)
    database = Database(settings.database_path)
    database.initialize()
    return SettingsRepository(database)


def product_repository() -> ProductRepository:
    settings = load_settings(require_token=False)
    database = Database(settings.database_path)
    database.initialize()
    return ProductRepository(database)


def configure_logging() -> None:
    settings = load_settings(require_token=False)
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "show-chat-id":
        chat_id = settings_repository().get_test_chat_id()
        print(chat_id if chat_id is not None else "Test chat_id is not selected")
        return
    if args.command == "reset-chat-id":
        removed = settings_repository().reset_test_chat_id()
        print("Test chat_id reset" if removed else "Test chat_id was not selected")
        return
    if args.command == "set-chat-id":
        settings_repository().set_test_chat_id(args.chat_id)
        print(f"Test chat_id set to {args.chat_id}")
        return
    if args.command == "catalog-stats":
        stats = product_repository().stats()
        print(f"Products total: {stats.total}")
        print(f"Available: {stats.available}")
        print(f"Unavailable: {stats.unavailable}")
        print("Sources:")
        for source, count in stats.by_source.items():
            print(f"  {source}: {count}")
        if stats.unavailable_by_source:
            print("Unavailable sources:")
            for source, count in stats.unavailable_by_source.items():
                print(f"  {source}: {count}")
        print(f"\nOn sale: {stats.on_sale}")
        print(f"New: {stats.new}")
        print(f"Free: {stats.free}")
        print(f"Beginner: {stats.beginner}")
        print(f"Knit: {stats.knit}")
        print(f"Categories: {stats.categories}")
        print(f"No price: {stats.no_price}")
        print(f"No image: {stats.no_image}")
        print("\nAudience:")
        for audience, count in stats.by_audience.items():
            print(f"  {audience}: {count}")
        return
    if args.command == "products":
        from app.models.product import ProductFilter

        category = category_name_by_code(args.category) or normalize_category(args.category)
        filters = ProductFilter(audience=args.audience, category=category)
        for product in product_repository().list_products(args.limit, filters=filters):
            price = (
                f"{product.price} {product.currency or ''}".strip()
                if product.price is not None
                else "—"
            )
            sizes = ", ".join(product.sizes) if product.sizes else "—"
            print(
                f"[{product.id}] {product.name}\n"
                f"  Price: {price}; Audience: {product.audience or '—'}; "
                f"Category: {product.category or '—'}; Sizes: {sizes}\n"
                f"  {product.product_url}"
            )
        return
    if args.command == "parse":
        from app.providers.registry import create_provider
        from app.services.catalog import CatalogService

        configure_logging()
        stats = asyncio.run(
            CatalogService(product_repository()).synchronize(
                create_provider(
                    args.source,
                    enrich_details=args.enrich_details,
                    detail_limit=args.detail_limit,
                )
            )
        )
        print(
            f"Source: {stats.source}\nFound: {stats.found}\nAdded: {stats.added}\n"
            f"Updated: {stats.updated}\nSkipped: {stats.skipped}\n"
            f"Marked unavailable: {stats.unavailable}\nErrors: {stats.errors}\n"
            f"Complete: {stats.complete}\n"
            f"Duration: {stats.duration_seconds:.2f}s"
        )
        return

    try:
        settings = load_settings(require_token=True)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    from app.bot import run_bot

    configure_logging()
    logging.getLogger(__name__).info("Starting PatternHub Bot application")
    asyncio.run(run_bot(settings))


if __name__ == "__main__":
    main()
