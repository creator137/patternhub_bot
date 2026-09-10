from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.handlers.start import handle_start


class StartHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_selects_chat_and_answers_test(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123456789),
            answer=AsyncMock(),
        )
        service = SimpleNamespace(select_if_missing=AsyncMock(return_value=True))

        await handle_start(message, service)

        service.select_if_missing.assert_awaited_once_with(123456789)
        message.answer.assert_awaited_once_with("Test")


if __name__ == "__main__":
    unittest.main()
