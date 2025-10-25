"""
Пересоздать таблицу blacklist без трогания остальных таблиц.
Запуск:
  export PYTHONPATH=$PWD/src
  source .venv/bin/activate
  python scripts/recreate_blacklist.py
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from bot.config import settings
from bot.models.models import Blacklist

async def main():
    engine = create_async_engine(settings.DATABASE_URL, future=True)
    async with engine.begin() as conn:
        # Посмотреть текущую структуру (в лог)
        try:
            res = await conn.execute(text("PRAGMA table_info(blacklist);"))
            cols = res.fetchall()
            print("Текущие колонки blacklist:", cols)
        except Exception:
            pass

        # Удаляем только таблицу blacklist
        await conn.execute(text("DROP TABLE IF EXISTS blacklist;"))
        # Создаём таблицу заново по текущей модели
        await conn.run_sync(Blacklist.__table__.create)

    await engine.dispose()
    print("✅ Таблица 'blacklist' пересоздана.")

if __name__ == "__main__":
    asyncio.run(main())
