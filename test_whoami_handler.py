#!/usr/bin/env python3
"""
Тест обработчика команды /whoami
"""
import sys
import asyncio
from unittest.mock import Mock, AsyncMock

# Добавляем путь к проекту
sys.path.insert(0, 'src')

async def test_whoami():
    """Тестируем обработчик команды /whoami"""
    from bot.handlers.help import cmd_whoami
    
    # Создаем мок объект сообщения
    message = Mock()
    message.from_user = Mock()
    message.from_user.id = 123456789
    message.from_user.username = "testuser"
    message.from_user.first_name = "Test"
    message.from_user.last_name = "User"
    message.answer = AsyncMock()
    
    # Вызываем обработчик
    try:
        await cmd_whoami(message)
        
        # Проверяем, что answer был вызван
        if message.answer.called:
            call_args = message.answer.call_args
            print("УСПЕХ: Обработчик вызван")
            print(f"Текст ответа: {call_args[0][0][:100]}...")
            return True
        else:
            print("ОШИБКА: message.answer не был вызван")
            return False
            
    except Exception as e:
        print(f"ОШИБКА при выполнении обработчика: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Тестирование обработчика /whoami...\n")
    success = asyncio.run(test_whoami())
    
    if success:
        print("\nТест пройден! Обработчик работает корректно.")
    else:
        print("\nТест не пройден! Обработчик не работает.")
        sys.exit(1)
