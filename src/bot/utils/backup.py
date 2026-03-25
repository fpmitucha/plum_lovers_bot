"""
Утилита для создания резервной копии базы данных и отправки её главному админу.
"""

import io
import logging
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot

ADMIN_ID = 8421106062
DB_PATH = Path("bot.db")
TZ_MSK = ZoneInfo("Europe/Moscow")

logger = logging.getLogger("innopls-bot")


async def send_db_backup(bot: Bot) -> None:
    """
    Создаёт zip-архив базы данных в памяти и отправляет его главному админу.
    """
    if not DB_PATH.exists():
        logger.warning("backup: bot.db not found at %s", DB_PATH.resolve())
        return

    now = datetime.now(TZ_MSK)
    archive_name = f"bot_backup_{now.strftime('%Y-%m-%d')}.zip"

    # Создаём zip в памяти (без записи на диск)
    buffer = io.BytesIO()
    try:
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Копируем db через shutil чтобы избежать проблем с блокировкой файла
            db_copy = io.BytesIO()
            with open(DB_PATH, "rb") as f:
                shutil.copyfileobj(f, db_copy)
            db_copy.seek(0)
            zf.writestr("bot.db", db_copy.read())
    except Exception as e:
        logger.error("backup: failed to create zip: %s", e)
        return

    buffer.seek(0)
    size_kb = len(buffer.getvalue()) // 1024

    try:
        from aiogram.types import BufferedInputFile
        file = BufferedInputFile(buffer.read(), filename=archive_name)
        await bot.send_document(
            chat_id=ADMIN_ID,
            document=file,
            caption=(
                f"🗄 <b>Ежедневный бэкап БД</b>\n"
                f"📅 {now.strftime('%d.%m.%Y %H:%M')} МСК\n"
                f"📦 Размер: {size_kb} КБ"
            ),
            parse_mode="HTML",
        )
        logger.info("backup: sent %s (%d KB) to admin %d", archive_name, size_kb, ADMIN_ID)
    except Exception as e:
        logger.error("backup: failed to send to admin: %s", e)
