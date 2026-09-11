from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.handlers.catalog import show_main_menu
from app.services.catalog import CatalogService
from app.services.test_chat import TestChatService


logger = logging.getLogger(__name__)


async def handle_start(
    message: Message,
    test_chat_service: TestChatService,
    catalog_service: CatalogService,
) -> None:
    if await test_chat_service.select_if_missing(message.chat.id):
        logger.info("Selected the first test chat_id: %s", message.chat.id)
    await show_main_menu(message, catalog_service)


def create_start_router(
    test_chat_service: TestChatService, catalog_service: CatalogService
) -> Router:
    router = Router(name=__name__)

    @router.message(CommandStart())
    async def bound_handle_start(message: Message) -> None:
        await handle_start(message, test_chat_service, catalog_service)

    return router
