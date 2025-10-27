#!/usr/bin/env python3
"""
Проверка работы бота и отправка тестового сообщения.
"""

import json
import urllib.request
import urllib.parse
import sys
import os
from pathlib import Path

def get_bot_token():
    """Получить токен бота из переменных окружения или .env файла."""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if token:
        return token
    
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('TELEGRAM_BOT_TOKEN='):
                    token = line.split('=', 1)[1].strip().strip('"').strip("'")
                    if token:
                        return token
    
    print("ОШИБКА: Токен бота не найден")
    return None

def check_bot_status(token):
    """Проверить статус бота."""
    url = f"https://api.telegram.org/bot{token}/getMe"
    
    try:
        with urllib.request.urlopen(url) as response:
            result = json.loads(response.read().decode('utf-8'))
            
        if result.get('ok'):
            bot_info = result['result']
            print(f"Бот активен: @{bot_info['username']} ({bot_info['first_name']})")
            return True
        else:
            print(f"ОШИБКА: {result.get('description', 'Неизвестная ошибка')}")
            return False
            
    except Exception as e:
        print(f"ОШИБКА подключения: {e}")
        return False

def get_current_commands(token):
    """Получить текущие команды бота."""
    url = f"https://api.telegram.org/bot{token}/getMyCommands"
    
    try:
        with urllib.request.urlopen(url) as response:
            result = json.loads(response.read().decode('utf-8'))
            
        if result.get('ok'):
            commands = result['result']
            print(f"\nТекущие команды бота ({len(commands)}):")
            for cmd in commands:
                print(f"  /{cmd['command']} — {cmd['description']}")
            return True
        else:
            print(f"ОШИБКА получения команд: {result.get('description', 'Неизвестная ошибка')}")
            return False
            
    except Exception as e:
        print(f"ОШИБКА: {e}")
        return False

def main():
    print("Проверка статуса бота...")
    
    token = get_bot_token()
    if not token:
        return False
    
    if not check_bot_status(token):
        return False
    
    get_current_commands(token)
    
    print("\nЕсли команда /whoami не работает, возможно нужно:")
    print("1. Перезапустить бота")
    print("2. Проверить, что роутер help_member.router подключен")
    print("3. Убедиться, что нет конфликтов с другими обработчиками")
    
    return True

if __name__ == "__main__":
    success = main()
    if not success:
        sys.exit(1)
