from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.types import MenuButtonWebApp, WebAppInfo

from app.config import Settings
from app.miniapp import miniapp_entry_url
from app.database import Database
from app.handlers.catalog import create_catalog_router
from app.handlers.start import create_start_router
from app.repositories.products import ProductRepository
from app.repositories.settings import SettingsRepository
from app.services.catalog import CatalogService
from app.services.test_chat import TestChatService
from app.services.subscriptions import SubscriptionService
from app.handlers.subscription import create_subscription_router, SubscriptionGuard


logger = logging.getLogger(__name__)


async def run_bot(settings: Settings) -> None:
    if settings.bot_token is None:
        raise ValueError("BOT_TOKEN is required to start the Telegram bot")

    database = Database(settings.database_path)
    database.initialize()
    test_chat_service = TestChatService(SettingsRepository(database))
    catalog_service = CatalogService(ProductRepository(database))

    dispatcher = Dispatcher()
    subscriptions = SubscriptionService(database)
    subscriptions.initialize()
    dispatcher.include_router(create_subscription_router(subscriptions, settings.miniapp_url))
    dispatcher.include_router(create_start_router(test_chat_service, catalog_service))
    catalog_router = create_catalog_router(catalog_service)
    guard = SubscriptionGuard(subscriptions, settings.miniapp_url)
    catalog_router.message.middleware(guard)
    catalog_router.callback_query.middleware(guard)
    dispatcher.include_router(catalog_router)
    bot = Bot(token=settings.bot_token)
    try:
        if settings.miniapp_url:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="Каталог", web_app=WebAppInfo(url=miniapp_entry_url(settings.miniapp_url, "catalog")),
                )
            )
        logger.info("Starting Telegram bot in long polling mode")
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
