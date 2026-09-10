from __future__ import annotations

import asyncio

from app.repositories.settings import SettingsRepository


class TestChatService:
    def __init__(self, repository: SettingsRepository) -> None:
        self.repository = repository

    async def select_if_missing(self, chat_id: int) -> bool:
        return await asyncio.to_thread(self.repository.select_test_chat_id, chat_id)
