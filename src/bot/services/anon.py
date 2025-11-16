from __future__ import annotations

"""
Helper primitives for anonymous messaging flows:
- rate limiting;
- dialog code generation + snapshots;
- text validation and user resolution.
"""

import asyncio
import random
import string
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

from bot.services.user_info import UserInfoSource

MIN_MESSAGE_LENGTH = 5
MAX_MESSAGE_LENGTH = 1500


class RateLimitExceeded(Exception):
    def __init__(self, seconds: int) -> None:
        self.seconds = seconds
        super().__init__(f"blocked for {seconds} seconds")


class FloodControl:
    def __init__(self, *, window_seconds: int = 10, max_hits: int = 10, block_seconds: int = 300) -> None:
        self.window_seconds = window_seconds
        self.max_hits = max_hits
        self.block_seconds = block_seconds
        self._hits: Dict[int, Deque[float]] = {}
        self._blocked: Dict[int, float] = {}

    def check(self, user_id: int) -> None:
        now = time.monotonic()
        until = self._blocked.get(user_id)
        if until and until > now:
            raise RateLimitExceeded(int(until - now))

        bucket = self._hits.setdefault(user_id, deque())
        while bucket and now - bucket[0] > self.window_seconds:
            bucket.popleft()
        bucket.append(now)

        if len(bucket) > self.max_hits:
            self._blocked[user_id] = now + self.block_seconds
            bucket.clear()
            raise RateLimitExceeded(self.block_seconds)


@dataclass(frozen=True)
class DialogSnapshot:
    id: int
    dialog_code: str
    initiator_id: int
    target_id: int
    kind: str
    status: str
    initiator_header_sent: int
    target_header_sent: int
    initiator_consent: str
    target_consent: str


def snapshot(dialog) -> DialogSnapshot:
    if isinstance(dialog, DialogSnapshot):
        return dialog
    return DialogSnapshot(
        id=dialog.id,
        dialog_code=dialog.dialog_code,
        initiator_id=dialog.initiator_id,
        target_id=dialog.target_id,
        kind=getattr(dialog, "kind", "user"),
        status=getattr(dialog, "status", "active"),
        initiator_header_sent=int(getattr(dialog, "initiator_header_sent", 0) or 0),
        target_header_sent=int(getattr(dialog, "target_header_sent", 0) or 0),
        initiator_consent=getattr(dialog, "initiator_consent", "approved"),
        target_consent=getattr(dialog, "target_consent", "approved"),
    )


async def generate_dialog_code(repo, *, length: int = 6) -> str:
    alphabet = string.digits
    for _ in range(10):
        code = "".join(random.choices(alphabet, k=length))
        if not await repo.get_anon_dialog_by_code(code):
            return code
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length + 2))


async def resolve_user_identifier(raw: str) -> Optional[int]:
    if not raw:
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    if candidate.startswith("@"):
        raise ValueError("username_lookup_disabled")
    return int(candidate)


def validate_text(text: str, lang: str) -> str | None:
    payload = (text or "").strip()
    if len(payload) < MIN_MESSAGE_LENGTH:
        return "Сообщение слишком короткое." if lang != "en" else "Message is too short."
    if len(payload) > MAX_MESSAGE_LENGTH:
        return "Сообщение слишком длинное." if lang != "en" else "Message is too long."
    return None
