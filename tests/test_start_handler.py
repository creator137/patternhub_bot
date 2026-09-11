from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.handlers.start import handle_start
from app.services.catalog import CatalogSection


class StartHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_selects_chat_and_answers_main_menu(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123456789),
            answer=AsyncMock(),
        )
        service = SimpleNamespace(select_if_missing=AsyncMock(return_value=True))
        catalog = SimpleNamespace(
            get_sections=AsyncMock(
                return_value=[
                    CatalogSection("women", "👗 Женские", 2, True),
                    CatalogSection("men", "👔 Мужские", 0, False),
                    CatalogSection("kids", "🧒 Детские", 0, False),
                ]
            )
        )

        await handle_start(message, service, catalog)

        service.select_if_missing.assert_awaited_once_with(123456789)
        message.answer.assert_awaited_once()
        self.assertIn("Каталог выкроек", message.answer.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
