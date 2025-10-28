# Быстрая инструкция по перезапуску бота

## Вы выполнили только daemon-reload, но не перезапустили сам бот!

### Выполните следующие команды:

```bash
# 1. Узнаем название сервиса бота
systemctl list-units --type=service | grep -i bot

# ИЛИ попробуйте эти варианты:
sudo systemctl restart plum_lovers_bot
# или
sudo systemctl restart bot_pls
# или
sudo systemctl restart telegram-bot
# или
sudo systemctl restart plsbot
```

### Если не знаете название сервиса:

```bash
# Найдите процесс Python с ботом
ps aux | grep python | grep -i bot

# Или найдите все Python процессы
ps aux | grep python

# Если нашли процесс - убейте его
kill <PID>

# Затем запустите бота вручную
cd ~/plum_lovers_bot
source .venv/bin/activate
python run.py
```

### Проверка логов после перезапуска:

```bash
# Если это systemd сервис:
sudo journalctl -u <название_сервиса> -f

# Или смотрите логи в файле (если настроены)
tail -f /var/log/plum_lovers_bot.log
```

### Как проверить, что бот работает:

```bash
# Проверьте статус сервиса
sudo systemctl status plum_lovers_bot

# Или найдите процесс
ps aux | grep "run.py"
```

После перезапуска отправьте боту команду `/whoami` в Telegram!
