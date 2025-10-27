#!/usr/bin/env python3
"""
Тест команды /whoami через Telegram Bot API.
"""

import json
import urllib.request
import urllib.parse
import sys
import os
from pathlib import Path

def get_bot_token():
    """Получить токен бота из переменных окружения или .env файла."""
    # Сначала пробуем переменную окружения
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if token:
        return token
    
    # Пробуем найти .env файл
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

def test_whoami_command(token):
    """Тестируем команду /whoami, отправив сообщение боту."""
    # Получаем информацию о боте
    url = f"https://api.telegram.org/bot{token}/getMe"
    
    try:
        with urllib.request.urlopen(url) as response:
            result = json.loads(response.read().decode('utf-8'))
            
        if result.get('ok'):
            bot_info = result['result']
            print(f"Бот: @{bot_info['username']} ({bot_info['first_name']})")
            
            # Получаем последние обновления
            updates_url = f"https://api.telegram.org/bot{token}/getUpdates"
            with urllib.request.urlopen(updates_url) as response:
                updates = json.loads(response.read().decode('utf-8'))
                
            if updates.get('ok'):
                print(f"Получено {len(updates['result'])} обновлений")
                
                # Ищем сообщения с командой /whoami
                whoami_messages = []
                for update in updates['result']:
                    if 'message' in update and 'text' in update['message']:
                        text = update['message']['text']
                        if '/whoami' in text:
                            whoami_messages.append({
                                'user_id': update['message']['from']['id'],
                                'username': update['message']['from'].get('username', 'N/A'),
                                'text': text,
                                'date': update['message']['date']
                            })
                
                if whoami_messages:
                    print(f"\nНайдено {len(whoami_messages)} сообщений с /whoami:")
                    for msg in whoami_messages[-3:]:  # Показываем последние 3
                        print(f"  Пользователь: {msg['username']} (ID: {msg['user_id']})")
                        print(f"  Сообщение: {msg['text']}")
                        print(f"  Дата: {msg['date']}")
                else:
                    print("Сообщений с /whoami не найдено")
                    
            return True
        else:
            print(f"ОШИБКА: {result.get('description', 'Неизвестная ошибка')}")
            return False
            
    except Exception as e:
        print(f"ОШИБКА: {e}")
        return False

def main():
    print("Тестирование команды /whoami...")
    
    token = get_bot_token()
    if not token:
        return False
    
    return test_whoami_command(token)

if __name__ == "__main__":
    success = main()
    if success:
        print("\nТест завершен.")
    else:
        print("\nТест не удался.")
        sys.exit(1)
