from __future__ import annotations

from app.database import Database


TEST_CHAT_ID_KEY = "test_chat_id"


class SettingsRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def select_test_chat_id(self, chat_id: int) -> bool:
        """Persist chat_id only if none exists; return whether it was selected."""
        with self.database.connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (TEST_CHAT_ID_KEY, str(chat_id)),
            )
            return cursor.rowcount == 1

    def get_test_chat_id(self) -> int | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (TEST_CHAT_ID_KEY,)
            ).fetchone()
        return int(row[0]) if row else None

    def reset_test_chat_id(self) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM settings WHERE key = ?", (TEST_CHAT_ID_KEY,)
            )
            return cursor.rowcount == 1

    def set_test_chat_id(self, chat_id: int) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (TEST_CHAT_ID_KEY, str(chat_id)),
            )
