# src/bot/services/karma_digest.py
from __future__ import annotations

"""
Ежедневная рассылка краткого дайджеста по карме.

Что делает:
- раз в сутки в заданное время (по локальному времени сервера) проходит по всем профилям
- считает + и - карму за текущие сутки, а также общую статистику
- отправляет пользователю личное сообщение-отчёт (если есть изменения за сегодня)

Запуск из bot.main:  start_karma_digest(bot, session_maker, hour=21, minute=0)
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Iterable, List

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from bot.utils.repo import Repo
from bot.models import Profile  # модель уже используется в проекте


async def _all_user_ids(session_maker: async_sessionmaker[AsyncSession]) -> List[int]:
    """Собрать все user_id из таблицы профилей."""
    async with session_maker() as s:
        rows = await s.execute(select(Profile.user_id))
        return [int(x) for x in rows.scalars().all() if x]


def _seconds_until(hour: int, minute: int) -> float:
    """Сколько секунд спать до ближайшего времени (локальное время сервера)."""
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


async def _send_digest_once(bot: Bot, session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Один проход по всем пользователям и рассылка отчётов."""
    user_ids = await _all_user_ids(session_maker)

    # интервал "сегодня": с полуночи по UTC до текущего момента по UTC (как и вся карма в Repo)
    now_utc = datetime.now(timezone.utc)
    start_today_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    async with session_maker() as s:
        repo = Repo(s)
        for uid in user_ids:
            try:
                plus_today, minus_today = await repo.karma_stats(uid, since=start_today_utc, until=now_utc)
                # Чтобы не спамить: если за сегодня ничего не изменилось — пропускаем
                if (plus_today or minus_today):
                    plus_total, minus_total = await repo.karma_stats(uid)
                    karma = await repo.get_karma(uid)

                    text = (
                        "📬 <b>Дневной отчёт по карме</b>\n"
                        f"За сегодня:  +{plus_today} / -{minus_today}\n"
                        f"Всего:       +{plus_total} / -{minus_total}\n"
                        f"Текущая карма: <b>{karma}</b>\n\n"
                        "Спасибо за участие в КЛС!"
                    )
                    await bot.send_message(uid, text, parse_mode="HTML")
            except Exception:
                # Любые ошибки доставки (пользователь закрыл ЛС, заблокировал бота и т.п.) — игнорируем
                continue


def start_karma_digest(
    bot: Bot,
    session_maker: async_sessionmaker[AsyncSession],
    *,
    hour: int = 21,
    minute: int = 0,
) -> None:
    """
    Запускает фоновую задачу с бесконечным циклом:
    - ждёт до ближайшего целевого времени;
    - делает рассылку;
    - снова ждёт сутки.
    """
    async def _runner():
        # Первый запуск: ждём до ближайшего «час:минута», чтобы не валить отчёты сразу при старте бота
        await asyncio.sleep(max(0.0, _seconds_until(hour, minute)))
        while True:
            try:
                await _send_digest_once(bot, session_maker)
            except Exception:
                # Никогда не падаем навсегда из-за исключения — просто ждём следующие сутки
                pass
            # Ждём до следующего дня в то же время
            await asyncio.sleep(24 * 60 * 60)

    asyncio.create_task(_runner(), name="karma_daily_digest")
