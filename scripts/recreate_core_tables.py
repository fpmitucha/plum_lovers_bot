"""
Пересоздание основных таблиц под текущие модели.
- roster: с бэкапом slug'ов
- applications, invites, blacklist: пересоздаём «как есть»

Запуск:
  export PYTHONPATH=$PWD/src
  source .venv/bin/activate
  python scripts/recreate_core_tables.py
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from bot.config import settings
from bot.models.models import Roster, Application, Invite, Blacklist

async def recreate_roster(conn):
    slugs: list[str] = []
    try:
        res = await conn.execute(text("SELECT slug FROM roster;"))
        slugs = [row[0] for row in res.fetchall() if row[0]]
        print(f"[roster] Бэкап slug: {len(slugs)}")
    except Exception:
        print("[roster] Нет читаемой старой таблицы — бэкап пропущен.")

    await conn.execute(text("DROP TABLE IF EXISTS roster;"))
    await conn.run_sync(Roster.__table__.create)
    print("[roster] ✅ создана заново")

    if slugs:
        seen = set()
        unique = []
        for s in slugs:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        for s in unique:
            await conn.execute(text("INSERT INTO roster (slug) VALUES (:slug)"), {"slug": s})
        print(f"[roster] 🔁 восстановлено slug: {len(unique)}")

async def recreate_plain(conn, model, name: str):
    await conn.execute(text(f"DROP TABLE IF EXISTS {name};"))
    await conn.run_sync(model.__table__.create)
    print(f"[{name}] ✅ создана заново")

async def main():
    engine = create_async_engine(settings.DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await recreate_roster(conn)
        await recreate_plain(conn, Application, "applications")
        await recreate_plain(conn, Invite, "invites")
        await recreate_plain(conn, Blacklist, "blacklist")
    await engine.dispose()
    print("Готово: все ключевые таблицы приведены к актуальной схеме.")

if __name__ == "__main__":
    asyncio.run(main())
