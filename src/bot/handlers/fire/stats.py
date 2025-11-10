from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.utils.repo import Repo

from .common import render_leaderboard

router = Router(name="fire-stats")


@router.message(Command("firetop"))
async def fire_top(message: Message, session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        repo = Repo(session)
        counters = await repo.get_fire_leaderboard()
    await message.answer(render_leaderboard(counters), disable_web_page_preview=True)
