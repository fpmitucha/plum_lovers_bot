from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from bot.utils.repo import Repo

router = Router(name="stats")

@router.message(Command("stats"))
async def cmd_stats(message: Message, session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as s:
        repo = Repo(s)

        now = datetime.now(timezone.utc)
        start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        plus_today, minus_today = await repo.karma_stats(message.from_user.id, since=start_today, until=now)
        plus_total, minus_total = await repo.karma_stats(message.from_user.id)
        karma = await repo.get_karma(message.from_user.id)

    await message.answer(
        "📊 <b>Статистика кармы</b>\n"
        f"Сегодня:  +{plus_today} / -{minus_today}\n"
        f"Всего:    +{plus_total} / -{minus_total}\n"
        f"Текущая карма: <b>{karma}</b>",
        parse_mode="HTML",
    )
