from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class WebSettings:
    bot_token: str = ""
    admin_ids: frozenset[int] = frozenset()
    environment: str = "production"
    dev_key: str = ""
    admin_usernames: frozenset[str] = frozenset()

    def __post_init__(self):
        if self.environment not in {"local", "production"}:
            raise ValueError("APP_ENV must be local or production")
        if self.dev_key and (self.environment != "local" or len(self.dev_key) < 32):
            raise ValueError("Dev access requires APP_ENV=local and a key of at least 32 characters")

    @classmethod
    def from_env(cls):
        return cls(os.getenv("BOT_TOKEN", ""),
                   frozenset(int(x.strip()) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()),
                   os.getenv("APP_ENV", "production"), os.getenv("MINIAPP_DEV_KEY", ""),
                   frozenset(x.strip().lstrip("@").casefold() for x in os.getenv("ADMIN_USERNAMES", "").split(",") if x.strip().lstrip("@")))


def telegram_user(raw: str, token: str, now: float | None = None) -> int:
    try:
        if not token or not raw or len(raw) > 16384:
            raise ValueError()
        pairs = parse_qsl(raw, strict_parsing=True)
        data = dict(pairs)
        if len(data) != len(pairs):
            raise ValueError()
        supplied = data.pop("hash")
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        check = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied):
            raise ValueError()
        age = (time.time() if now is None else now) - int(data["auth_date"])
        if not -30 <= age <= 3600:
            raise ValueError()
        user_id = json.loads(data["user"])["id"]
        if type(user_id) is not int or user_id <= 0:
            raise ValueError()
        return user_id
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, "Invalid or expired Telegram authorization") from None


def require_admin(request: Request):
    settings = request.app.state.web_settings
    # No cookies, no CORS, no forwarded-header trust. Dev key never enters the bundle.
    dev_key = request.headers.get("x-dev-key", "")
    if (settings.environment == "local" and settings.dev_key and dev_key
        and request.client and request.client.host in {"127.0.0.1", "::1"}
        and request.url.hostname in {"localhost", "127.0.0.1", "::1"}
        and hmac.compare_digest(dev_key, settings.dev_key)):
        return 0
    raw = request.headers.get("x-telegram-init-data", "")
    user_id = telegram_user(raw, settings.bot_token)
    if user_id in settings.admin_ids:
        return user_id
    # Only signed Telegram usernames may claim an unbound account. Pin the ID
    # once so a later username transfer cannot transfer administrative access.
    user = json.loads(dict(parse_qsl(raw))["user"])
    username = str(user.get("username", "")).casefold()
    with request.app.state.database.connect() as db:
        for allowed in settings.admin_usernames:
            key = "miniapp.admin." + allowed
            if username == allowed:
                db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, str(user_id)))
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if row and row[0] == str(user_id):
                return user_id
    raise HTTPException(403, "Administrator access required")
