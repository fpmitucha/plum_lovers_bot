#!/usr/bin/env python3
"""
Простой скрипт для обновления команд бота через Telegram Bot API.
Использует только стандартные библиотеки Python.
"""

import json
import urllib.request
import urllib.parse
import sys
from pathlib import Path

def get_bot_token():
    """Получить токен бота из файла конфигурации."""
    config_file = Path("src/bot/config.py")
    if not config_file.exists():
        print("ОШИБКА: Файл конфигурации не найден")
        return None
    
    with open(config_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Ищем токен в файле
    for line in content.split('\n'):
        if 'TELEGRAM_BOT_TOKEN' in line and '=' in line:
            # Извлекаем токен из строки
            token = line.split('=')[1].strip().strip('"').strip("'")
            if token and token != 'None':
                return token
    
    print("ОШИБКА: Токен бота не найден в конфигурации")
    return None

def update_bot_commands(token):
    """Обновить команды бота через Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    
    commands = [
        {"command": "stats", "description": "Статистика моей кармы"},
        {"command": "top", "description": "Топ пользователей по карме"},
        {"command": "help", "description": "Помощь и информация"},
        {"command": "whoami", "description": "Показать мой Telegram ID"},
    ]
    
    data = {
        "commands": commands
    }
    
    try:
        # Отправляем запрос
        req_data = json.dumps(data).encode('utf-8')
        request = urllib.request.Request(url, data=req_data, headers={'Content-Type': 'application/json'})
        
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode('utf-8'))
            
        if result.get('ok'):
            print("УСПЕХ: Команды бота успешно обновлены!")
            print("\nНовые команды:")
            for cmd in commands:
                print(f"   /{cmd['command']} — {cmd['description']}")
            return True
        else:
            print(f"ОШИБКА API: {result.get('description', 'Неизвестная ошибка')}")
            return False
            
    except Exception as e:
        print(f"ОШИБКА при обновлении команд: {e}")
        return False

def get_bot_info(token):
    """Получить информацию о боте."""
    url = f"https://api.telegram.org/bot{token}/getMe"
    
    try:
        with urllib.request.urlopen(url) as response:
            result = json.loads(response.read().decode('utf-8'))
            
        if result.get('ok'):
            bot_info = result['result']
            print(f"Подключен к боту: @{bot_info['username']} ({bot_info['first_name']})")
            return True
        else:
            print(f"ОШИБКА получения информации о боте: {result.get('description', 'Неизвестная ошибка')}")
            return False
            
    except Exception as e:
        print(f"ОШИБКА подключения к боту: {e}")
        return False

def main():
    print("Обновление команд бота...")
    
    # Получаем токен
    token = get_bot_token()
    if not token:
        return False
    
    # Проверяем подключение к боту
    if not get_bot_info(token):
        return False
    
    # Обновляем команды
    return update_bot_commands(token)

if __name__ == "__main__":
    success = main()
    if success:
        print("\nГотово! Команды бота обновлены.")
        print("Теперь в интерфейсе Telegram должны отображаться только:")
        print("   /stats, /top, /help, /whoami")
    else:
        print("\nНе удалось обновить команды бота.")
        sys.exit(1)
