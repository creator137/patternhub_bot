from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str | None
    database_path: Path
    log_level: str
    miniapp_url: str | None = None


def load_settings(*, require_token: bool = True) -> Settings:
    """Load local settings without ever logging secret values."""
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

    token = os.getenv("BOT_TOKEN", "").strip() or None
    if require_token and token is None:
        raise ValueError(
            "BOT_TOKEN is not configured. Copy .env.example to .env and add the token."
        )

    database_path = Path(os.getenv("DATABASE_PATH", "data/patternhub.sqlite3")).expanduser()
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path
    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
    miniapp_url = os.getenv("MINIAPP_URL", "").strip() or None
    if miniapp_url:
        url = urlsplit(miniapp_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("MINIAPP_URL must be an HTTPS URL without credentials")
    return Settings(token, database_path, log_level, miniapp_url)
