"""
Пересоздать таблицу roster по текущей модели, сохранив данные (slug).
Запуск из корня проекта (bot_pls):
  export PYTHONPATH=$PWD/src
  source .venv/bin/activate
  python scripts/recreate_roster.py
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from bot.config import settings
from bot.models.models import Roster

async def main():
    engine = create_async_engine(settings.DATABASE_URL, future=True)

    async with engine.begin() as conn:
        # Пробуем прочитать текущие слоги (если таблица есть)
        slugs: list[str] = []
        try:
            res = await conn.execute(text("SELECT slug FROM roster;"))
            slugs = [row[0] for row in res.fetchall() if row[0]]
            print(f"Найдено slug в старой таблице: {len(slugs)}")
        except Exception:
            print("Старая таблица roster не читается (возможно, не существует или с другой схемой). Продолжаем.")

        # Дропаем старую таблицу
        await conn.execute(text("DROP TABLE IF EXISTS roster;"))
        # Создаём заново по текущей модели
        await conn.run_sync(Roster.__table__.create)
        print("✅ Таблица 'roster' создана заново.")

        # Возвращаем слоги (уникальные)
        if slugs:
            # Удалим дубликаты, сохранив порядок
            seen = set()
            unique = []
            for s in slugs:
                if s not in seen:
                    seen.add(s)
                    unique.append(s)

            # Вставка
            for s in unique:
                await conn.execute(text("INSERT INTO roster (slug) VALUES (:slug)"), {"slug": s})
            print(f"🔁 Восстановлено slug: {len(unique)}")

    await engine.dispose()
    print("Готово.")

if __name__ == "__main__":
    asyncio.run(main())
