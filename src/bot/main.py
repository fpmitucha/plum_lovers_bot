"""
Точка входа: сборка приложения, регистрация роутеров, запуск long polling.

Также:
 - создаёт таблицы БД при старте;
 - загружает начальный «ростер» из файла при первом запуске (опционально);
 - регистрирует команды бота.
"""

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from bot.config import settings
from bot.logging_config import setup_logging
from bot.handlers import help as help_member
from bot.handlers import start as start_handlers
from bot.handlers import join as join_handlers
from bot.handlers import anon as anon_handlers
from bot.handlers import fire as fire_handlers
from bot.handlers import admin as admin_handlers
from bot.handlers import chat_member as chat_member_handlers
from bot.handlers import cleanup as cleanup_handlers
from bot.handlers import cabinet as cabinet_handlers
from bot.handlers import settings as settings_handlers
from bot.handlers import deadlines as deadlines_handlers
from bot.handlers import admin_karma
from bot.handlers.top import router as top_router
from bot.handlers.karma_auto import router as karma_auto_router

from bot.utils.db import create_engine, create_session_factory
from bot.utils.parse_deadlines import parse_deadlines
from bot.models.models import Base

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo


async def set_bot_commands(bot: Bot) -> None:
    """Зарегистрировать команды бота в интерфейсе Telegram."""
    await bot.set_my_commands(
        commands=[
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="stats", description="Статистика моей кармы"),
            BotCommand(command="top", description="Топ пользователей по карме"),
            BotCommand(command="help", description="Помощь и информация"),
            BotCommand(command="whoami", description="Показать мой Telegram ID"),
            BotCommand(command="fire", description="Сообщить о пожарке"),
            BotCommand(command="deadlines", description="Показать текущие дедлайны"),
            BotCommand(command="firetop", description="Рейтинг пожарок"),
            # BotCommand(command="admin", description="Админ-панель"),
        ]
    )


async def seed_roster_if_needed(session_maker) -> None:
    """
    Первичная загрузка «базы» (roster) из файла, если он указан и не пуст.
    """
    if not settings.ROSTER_SEED_FILE:
        return

    f = Path(settings.ROSTER_SEED_FILE)
    if not f.exists():
        return

    from bot.utils.repo import Repo

    async with session_maker() as session:
        repo = Repo(session)
        with f.open("r", encoding="utf-8") as fh:
            slugs = [line.strip() for line in fh if line.strip()]
        if slugs:
            added = await repo.roster_bulk_insert(slugs)
            logging.getLogger("innopls-bot").info("Roster seed added: %s", added)


async def on_startup(dp: Dispatcher, bot: Bot, engine):
    """Хуки старта: создание таблиц, DI session_maker, команды и seed."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = create_session_factory(engine)
    dp.workflow_data.update({"session_maker": session_maker})

    await set_bot_commands(bot)
    await seed_roster_if_needed(session_maker)

    # Настройка планировщика
    scheduler = AsyncIOScheduler(timezone=ZoneInfo("Europe/Moscow"))

    # Первый запуск: каждый день в 00:20
    scheduler.add_job(
        parse_deadlines,
        trigger=CronTrigger(hour=0, minute=20),
        args=[session_maker],
        id="daily_deadlines_parse_0020",
        replace_existing=True,
    )

    # Второй запуск: каждый день в 12:50
    scheduler.add_job(
        parse_deadlines,
        trigger=CronTrigger(hour=12, minute=50),
        args=[session_maker],
        id="daily_deadlines_parse_1250",
        replace_existing=True,
    )

    # scheduler.add_job(
    #     parse_deadlines,
    #     trigger=CronTrigger(hour=4, minute=55),
    #     args=[session_maker],
    #     id="daily_deadlines_parse_0455",
    #     replace_existing=True,
    # )

    scheduler.start()
    dp.workflow_data["scheduler"] = scheduler

    asyncio.create_task(parse_deadlines(session_maker))


async def main():
    """Основной цикл запуска бота."""
    logger = setup_logging()

    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # ПОРЯДОК ВАЖЕН: команды до universal handlers
    dp.include_router(help_member.router)
    dp.include_router(start_handlers.router)
    dp.include_router(join_handlers.router)
    dp.include_router(anon_handlers.router)
    dp.include_router(fire_handlers.router)
    dp.include_router(top_router)
    dp.include_router(admin_handlers.router)
    dp.include_router(admin_karma.router)
    dp.include_router(cabinet_handlers.router)
    dp.include_router(settings_handlers.router)
    dp.include_router(deadlines_handlers.router)

    dp.include_router(karma_auto_router)  # ← после всех команд (есть @router.message())

    dp.include_router(chat_member_handlers.router)
    dp.include_router(cleanup_handlers.router)

    engine = create_engine(settings.DATABASE_URL)
    await on_startup(dp, bot, engine)

    logger.info("Bot is up. Starting polling...")
    allowed_updates = [
        "message",
        "callback_query",
        "chat_member",
        "my_chat_member",
        "message_reaction",
        "message_reaction_count",
    ]

    try:
        await dp.start_polling(bot, allowed_updates=allowed_updates)
    finally:
        scheduler = dp.get("scheduler")
        if scheduler:
            scheduler.shutdown()
        await bot.session.close()

    # await dp.start_polling(bot, allowed_updates=allowed_updates)


if __name__ == "__main__":
    asyncio.run(main())
