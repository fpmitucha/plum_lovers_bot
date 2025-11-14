from __future__ import annotations

"""
Shared helpers for working with administrator configuration.
"""

from typing import Iterable, Optional

from bot.config import settings


def _candidate_ids() -> Iterable[int]:
    """
    Yield possible main admin ids in priority order:
    explicit MAIN_ADMIN_ID -> legacy MAIN_ADMIN_USER_ID -> ADMIN_USER_IDS list.
    """
    for attr in ("MAIN_ADMIN_ID", "MAIN_ADMIN_USER_ID"):
        raw = getattr(settings, attr, None)
        if raw is not None:
            yield raw
    for item in getattr(settings, "ADMIN_USER_IDS", []) or []:
        yield item


def main_admin_id_from_settings() -> Optional[int]:
    """
    Try to resolve the main admin id from configuration/static lists.
    Returns None if nothing valid is configured.
    """
    for candidate in _candidate_ids():
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if value:
            return value
    return None


def admin_notify_chat_id() -> Optional[int]:
    """
    Return admin notification chat id if configured and valid.
    """
    raw = getattr(settings, "ADMIN_NOTIFY_CHAT_ID", None)
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value or None
