#!/usr/bin/env python3
"""
Скрипт для исправления профилей с NULL значением в поле karma.

Этот скрипт:
1. Проверяет наличие колонки karma в таблице profiles
2. Если колонки нет - добавляет её
3. Устанавливает значение 10 для всех записей, где karma IS NULL
4. Выводит статистику исправлений
"""

import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.bot.config import settings
from src.bot.utils.db import create_engine, create_session_factory
from sqlalchemy import text


async def fix_karma_null():
    """Исправляет NULL значения в поле karma."""
    print("🔧 Исправление NULL значений в поле karma...")
    
    engine = create_engine(settings.DATABASE_URL)
    session_maker = create_session_factory(engine)
    
    async with session_maker() as session:
        # Проверяем наличие колонки karma
        res = await session.execute(text("PRAGMA table_info(profiles)"))
        cols = [row[1] for row in res.fetchall()]
        
        if "karma" not in cols:
            print("📝 Колонка karma не найдена, добавляем...")
            await session.execute(text("ALTER TABLE profiles ADD COLUMN karma INTEGER"))
            await session.commit()
            print("✅ Колонка karma добавлена")
        else:
            print("✅ Колонка karma уже существует")
        
        # Подсчитываем записи с NULL karma
        res = await session.execute(text("SELECT COUNT(*) FROM profiles WHERE karma IS NULL"))
        null_count = res.scalar() or 0
        
        if null_count > 0:
            print(f"🔍 Найдено {null_count} записей с NULL karma")
            
            # Исправляем NULL значения
            await session.execute(text("UPDATE profiles SET karma = 10 WHERE karma IS NULL"))
            await session.commit()
            
            print(f"✅ Исправлено {null_count} записей")
        else:
            print("✅ Все записи уже имеют корректное значение karma")
        
        # Выводим статистику
        res = await session.execute(text("SELECT COUNT(*) FROM profiles"))
        total_count = res.scalar() or 0
        
        res = await session.execute(text("SELECT COUNT(*) FROM profiles WHERE karma = 10"))
        default_karma_count = res.scalar() or 0
        
        res = await session.execute(text("SELECT COUNT(*) FROM profiles WHERE karma != 10"))
        custom_karma_count = res.scalar() or 0
        
        print("\n📊 Статистика:")
        print(f"   Всего профилей: {total_count}")
        print(f"   С кармой по умолчанию (10): {default_karma_count}")
        print(f"   С пользовательской кармой: {custom_karma_count}")
        print(f"   С NULL кармой: 0")


if __name__ == "__main__":
    asyncio.run(fix_karma_null())
