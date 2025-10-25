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
from bot.handlers import start as start_handlers
from bot.handlers import join as join_handlers
from bot.handlers import admin as admin_handlers
from bot.handlers import chat_member as chat_member_handlers
from bot.handlers import cleanup as cleanup_handlers

from bot.utils.db import create_engine, create_session_factory
from bot.models.models import Base


async def set_bot_commands(bot: Bot) -> None:
    """Зарегистрировать команды бота в интерфейсе Telegram."""
    await bot.set_my_commands(
        commands=[
            BotCommand(command="start", description="Начать"),
            # BotCommand(command="admin", description="Админ-панель"),  # при желании
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

    # ✅ Правильный способ передать зависимости во все хендлеры (aiogram v3):
    dp.workflow_data.update({"session_maker": session_maker})

    await set_bot_commands(bot)
    await seed_roster_if_needed(session_maker)


async def main():
    """Основной цикл запуска бота."""
    logger = setup_logging()

    # aiogram ≥ 3.7: parse_mode задаётся через DefaultBotProperties
    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Регистрируем роутеры
    dp.include_router(start_handlers.router)
    dp.include_router(join_handlers.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(chat_member_handlers.router)
    dp.include_router(cleanup_handlers.router)

    # Инициализируем БД и стартовые хуки
    engine = create_engine(settings.DATABASE_URL)
    await on_startup(dp, bot, engine)

    # Запускаем поллинг
    logger.info("Bot is up. Starting polling...")
    allowed_updates = ["message", "callback_query", "chat_member", "my_chat_member"]
    await dp.start_polling(bot, allowed_updates=allowed_updates)


if __name__ == "__main__":
    asyncio.run(main())
