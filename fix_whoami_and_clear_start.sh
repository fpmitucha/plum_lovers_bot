#!/bin/bash
# Скрипт для исправления команды whoami и очистки /start

echo "=== Обновление команд бота ==="

# Активируем виртуальное окружение
cd ~/plum_lovers_bot
source .venv/bin/activate

# Запускаем скрипт обновления команд
python3 scripts/update_commands_env.py

echo ""
echo "=== Очистка команд (удаление всех) ==="

# Создаем временный скрипт для очистки команд
cat > /tmp/clear_commands.py << 'EOF'
import json
import urllib.request
import os
from pathlib import Path

def get_bot_token():
    env_file = Path("~/plum_lovers_bot/.env").expanduser()
    if env_file.exists():
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('TELEGRAM_BOT_TOKEN='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None

token = get_bot_token()
if token:
    # Сначала удаляем все команды
    url = f"https://api.telegram.org/bot{token}/deleteMyCommands"
    try:
        with urllib.request.urlopen(url) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('ok'):
                print("Все команды удалены")
    except Exception as e:
        print(f"Ошибка: {e}")
    
    # Теперь устанавливаем новые команды
    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    commands = [
        {"command": "stats", "description": "Статистика моей кармы"},
        {"command": "top", "description": "Топ пользователей по карме"},
        {"command": "help", "description": "Помощь и информация"},
        {"command": "whoami", "description": "Показать мой Telegram ID"},
    ]
    data = json.dumps({"commands": commands}).encode('utf-8')
    request = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('ok'):
                print("Новые команды установлены:")
                for cmd in commands:
                    print(f"  /{cmd['command']}")
    except Exception as e:
        print(f"Ошибка: {e}")
EOF

python3 /tmp/clear_commands.py

echo ""
echo "=== Перезапуск бота ==="
sudo systemctl restart plum_lovers_bot

sleep 3

echo ""
echo "=== Проверка статуса ==="
sudo systemctl status plum_lovers_bot --no-pager -l

echo ""
echo "Готово! Теперь:"
echo "1. Перезапустите Telegram приложение"
echo "2. Попробуйте команду /whoami снова"
