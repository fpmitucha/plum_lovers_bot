from __future__ import annotations

import html
from typing import Iterable, List

from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.config import settings

from .callbacks import FireReviewCB

VALID_DORMS: tuple[int, ...] = tuple(range(1, 8))
MIN_DESCRIPTION_LEN = 5
MAX_DESCRIPTION_LEN = 500


def sanitize_description(text: str | None) -> str:
    payload = (text or "").strip()
    return payload[:MAX_DESCRIPTION_LEN]


def validate_description(text: str | None) -> str | None:
    payload = (text or "").strip()
    if len(payload) < MIN_DESCRIPTION_LEN:
        return "Нужно описать ситуацию (минимум 5 символов)."
    return None


def dorm_label(dorm_number: int) -> str:
    return f"🏢 Дорм #{dorm_number}"


def incident_admin_text(incident, description: str) -> str:
    body = html.escape(description or "—")
    dorm = dorm_label(incident.dorm_number)
    return (
        f"🚨 <b>Новый сигнал о пожарке #{incident.id}</b>\n\n"
        f"{dorm}\n"
        f"<b>Описание:</b> {body}\n"
        f"<b>Отправитель:</b> <code>{incident.user_id}</code>\n\n"
        "Подтвердите, если сигнализация действительно сработала."
    )


def incident_user_text(dorm_number: int) -> str:
    return (
        f"{dorm_label(dorm_number)} зафиксирована, заявка "
        "отправлена на проверку админам. Сообщим, когда обновим счётчик."
    )


def incident_broadcast_text(dorm_number: int, total: int, counters, highlight: int) -> str:
    return render_leaderboard(counters, highlight=highlight)


def incident_user_result_text(dorm_number: int, approved: bool, total: int | None = None) -> str:
    if approved:
        return (
            f"✅ {dorm_label(dorm_number)} подтверждена."
            f" Новый счётчик: <b>{total or 0}</b>."
        )
    return f"⛔️ {dorm_label(dorm_number)} не подтверждена администрацией."


def review_keyboard(incident_id: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(
        text="✅ Подтвердить",
        callback_data=FireReviewCB(action="approve", incident_id=incident_id).pack(),
    )
    kb.button(
        text="⛔️ Отклонить",
        callback_data=FireReviewCB(action="reject", incident_id=incident_id).pack(),
    )
    kb.adjust(2)
    return kb


def render_leaderboard(counters, *, highlight: int | None = None) -> str:
    totals = {c.dorm_number: c.total for c in (counters or [])}
    full = [(dorm, totals.get(dorm, 0)) for dorm in VALID_DORMS]
    full.sort(key=lambda item: (-item[1], item[0]))
    leader_dorm, leader_total = full[0]
    lines = ["🔥 <b>Рейтинг пожарок</b>", f"Лидирует: {dorm_label(leader_dorm)} — <b>{leader_total}</b>", ""]
    for idx, (dorm, total) in enumerate(full, start=1):
        marker = "🔥 " if highlight == dorm else ""
        lines.append(f"{idx}. {marker}{dorm_label(dorm)} — <b>{total}</b>")
    return "\n".join(lines)
