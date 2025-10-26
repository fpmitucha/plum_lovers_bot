from __future__ import annotations

from typing import Optional

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from bot.utils.repo import Repo
from bot.services.i18n import get_lang

router = Router(name="top_by_karma")

class StartCB(CallbackData, prefix="start"):
    action: str
    value: Optional[str] = None

def _back_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text={"ru": "⬅️ Назад", "en": "⬅️ Back"}[lang],
            callback_data=StartCB(action="back", value=lang).pack(),
        )]]
    )

@router.message(Command("top"))
async def cmd_top(message: Message, session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Первые 10 пользователей по карме (строго по karma DESC, затем joined_at ASC при наличии, затем user_id ASC)."""
    lang = (get_lang(message.from_user.id) or "ru").lower()
    if lang not in ("ru", "en"):
        lang = "ru"

    async with session_maker() as s:
        repo = Repo(s)
        rows = await repo.get_top_by_karma(limit=10)  # [(uid, username, karma)]

    if not rows:
        text = {"ru": "Пока нет данных для рейтинга по карме.", "en": "No data for karma leaderboard yet."}[lang]
    else:
        header = {
            "ru": "<b>🏆 ТОП по карме</b>\nПервые 10 участников с наибольшей кармой:\n",
            "en": "<b>🏆 Karma leaderboard</b>\nTop 10 members by karma:\n",
        }[lang]
        lines = []
        for pos, (uid, uname, karma) in enumerate(rows, 1):
            tag = f"@{uname}" if uname else f"id:{uid}"
            lines.append(f"{pos}. {tag} — <b>{karma}</b>")
        text = header + "\n".join(lines)

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=_back_kb(lang))
