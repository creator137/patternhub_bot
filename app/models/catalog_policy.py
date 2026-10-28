"""Shared user-facing selection rules, independent of any provider."""
from datetime import datetime, timezone

NEW_WINDOW_DAYS = 60


def publication_datetime(value):
    if not value:
        return None
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def is_recent_publication(value, *, now=None):
    published = publication_datetime(value)
    if published is None:
        return False
    age = ((now or datetime.now(timezone.utc)) - published).total_seconds()
    return 0 <= age <= NEW_WINDOW_DAYS * 86400


def new_section_sql(prefix: str = '') -> str:
    return f"COALESCE((julianday({prefix}source_published_at) BETWEEN julianday('now','-{NEW_WINDOW_DAYS} days') AND julianday('now')),0)"


def free_section_sql(prefix: str = '') -> str:
    # is_free keeps its strict zero-price meaning on product cards.
    return f"({prefix}is_free=1 OR COALESCE(({prefix}currency='RUB' AND CAST({prefix}price AS NUMERIC)=1),0))"
