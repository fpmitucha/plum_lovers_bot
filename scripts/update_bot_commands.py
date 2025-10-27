#!/usr/bin/env python3
"""
Скрипт для обновления команд бота в Telegram без перезапуска.

Этот скрипт:
1. Подключается к боту через токен
2. Обновляет список команд в интерфейсе Telegram
3. Выводит результат операции
"""

import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from aiogram import Bot
from aiogram.types import BotCommand
from src.bot.config import settings


async def update_bot_commands():
    """Обновить команды бота в Telegram."""
    print("🤖 Обновление команд бота...")
    
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    
    try:
        # Получаем информацию о боте
        me = await bot.get_me()
        print(f"✅ Подключен к боту: @{me.username} ({me.first_name})")
        
        # Устанавливаем новые команды
        commands = [
            BotCommand(command="stats", description="Статистика моей кармы"),
            BotCommand(command="top", description="Топ пользователей по карме"),
            BotCommand(command="help", description="Помощь и информация"),
            BotCommand(command="whoami", description="Показать мой Telegram ID"),
        ]
        
        await bot.set_my_commands(commands)
        print("✅ Команды бота успешно обновлены!")
        
        # Проверяем, что команды установились
        current_commands = await bot.get_my_commands()
        print(f"\n📋 Текущие команды бота:")
        for cmd in current_commands:
            print(f"   /{cmd.command} — {cmd.description}")
            
    except Exception as e:
        print(f"❌ Ошибка при обновлении команд: {e}")
        return False
    finally:
        await bot.session.close()
    
    return True


if __name__ == "__main__":
    success = asyncio.run(update_bot_commands())
    if success:
        print("\n🎉 Готово! Команды бота обновлены.")
        print("Теперь в интерфейсе Telegram должны отображаться только:")
        print("   /stats, /top, /help, /whoami")
    else:
        print("\n💥 Не удалось обновить команды бота.")
        sys.exit(1)
