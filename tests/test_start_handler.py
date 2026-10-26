from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.handlers.start import handle_start
from app.handlers.catalog import create_main_keyboard
from app.services.catalog import CatalogSection


class StartHandlerTests(unittest.IsolatedAsyncioTestCase):
    def test_miniapp_button_is_optional(self):
        keyboard = create_main_keyboard(miniapp_url="https://catalog.example.com/")
        self.assertEqual(keyboard.keyboard[0][0].web_app.url, "https://catalog.example.com/")
        self.assertFalse(any(button.web_app for row in create_main_keyboard().keyboard for button in row))

    async def test_start_opens_miniapp_only_in_private_chats(self):
        from app.handlers.catalog import show_main_menu
        catalog = SimpleNamespace(get_sections=AsyncMock(return_value=[]))
        with patch.dict("os.environ", {"MINIAPP_URL": "https://catalog.example.com/"}):
            for chat_type in ("private", "group"):
                message = SimpleNamespace(chat=SimpleNamespace(type=chat_type), answer=AsyncMock())
                await show_main_menu(message, catalog)
                keyboard = message.answer.await_args.kwargs["reply_markup"]
                buttons = [button for row in keyboard.keyboard for button in row if button.web_app]
                self.assertEqual(bool(buttons), chat_type == "private")

    async def test_start_selects_chat_and_answers_main_menu(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123456789, type="private"),
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
