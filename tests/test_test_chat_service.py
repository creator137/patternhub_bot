from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.database import Database
from app.repositories.settings import SettingsRepository


class SettingsRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp_directory.name) / "test.sqlite3")
        database.initialize()
        self.repository = SettingsRepository(database)

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_first_chat_id_is_persisted_and_not_replaced(self) -> None:
        self.assertTrue(self.repository.select_test_chat_id(111))
        self.assertFalse(self.repository.select_test_chat_id(222))
        self.assertEqual(self.repository.get_test_chat_id(), 111)

    def test_chat_id_can_be_reset_and_selected_again(self) -> None:
        self.repository.select_test_chat_id(111)

        self.assertTrue(self.repository.reset_test_chat_id())
        self.assertIsNone(self.repository.get_test_chat_id())
        self.assertTrue(self.repository.select_test_chat_id(222))
        self.assertEqual(self.repository.get_test_chat_id(), 222)

    def test_chat_id_can_be_changed_manually(self) -> None:
        self.repository.select_test_chat_id(111)
        self.repository.set_test_chat_id(-1001234567890)

        self.assertEqual(self.repository.get_test_chat_id(), -1001234567890)


if __name__ == "__main__":
    unittest.main()
