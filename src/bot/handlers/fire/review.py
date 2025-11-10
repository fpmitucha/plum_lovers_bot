from __future__ import annotations

import contextlib

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.utils.repo import Repo
from bot.handlers.admin import _get_all_admin_ids

from .callbacks import FireReviewCB
from bot.config import settings

from .common import incident_broadcast_text, incident_user_result_text

router = Router(name="fire-review")


@router.callback_query(FireReviewCB.filter())
async def on_review(
    callback: CallbackQuery,
    callback_data: FireReviewCB,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        repo = Repo(session)
        incident = await repo.get_fire_incident(callback_data.incident_id)
        admins = await _get_all_admin_ids(repo)
        if callback.from_user.id not in admins:
            await callback.answer("Недостаточно прав.", show_alert=True)
            return
        if not incident:
            await callback.answer("Запись не найдена.", show_alert=True)
            return
        if incident.status != "pending":
            await callback.answer("Заявка уже обработана.", show_alert=True)
            return

        if callback_data.action == "approve":
            await repo.update_fire_incident_status(
                incident_id=incident.id,
                status="approved",
                processed_by=callback.from_user.id,
            )
            total = await repo.increment_fire_counter(incident.dorm_number)
            counters = await repo.get_fire_leaderboard()
        else:
            await repo.update_fire_incident_status(
                incident_id=incident.id,
                status="rejected",
                processed_by=callback.from_user.id,
            )
            total = None
            counters = []

    approved = callback_data.action == "approve"
    await _notify_user(callback, incident.user_id, incident.dorm_number, approved, total)
    if approved and total is not None:
        await _notify_chats(callback, incident.dorm_number, total, counters)
    await callback.message.edit_text(
        "🔥 Пожарка подтверждена." if approved else "Заявка отклонена.",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


async def _notify_user(callback: CallbackQuery, user_id: int, dorm_number: int, approved: bool, total: int | None) -> None:
    text = incident_user_result_text(dorm_number, approved, total)
    with contextlib.suppress(Exception):
        await callback.bot.send_message(user_id, text, parse_mode=ParseMode.HTML)


async def _notify_chats(callback: CallbackQuery, dorm_number: int, total: int, counters) -> None:
    text = incident_broadcast_text(dorm_number, total, counters, dorm_number)
    target_chat = getattr(settings, "TARGET_CHAT_ID", None)
    if not target_chat:
        return
    with contextlib.suppress(Exception):
        await callback.bot.send_message(int(target_chat), text, parse_mode=ParseMode.HTML)
