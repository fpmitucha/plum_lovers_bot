# Деплой API на VPS (213.176.113.161)

## 1. Обновить код на сервере

```bash
cd /root/plum_lovers_bot   # или твой путь к боту
git pull
```

## 2. Установить новые зависимости

```bash
# Активируй тот же venv, что использует бот
source venv/bin/activate
pip install -r requirements.txt
```

## 3. Проверить путь к БД

Убедись, что переменная `DATABASE_URL` в `.env` указывает на правильный файл:
```
DATABASE_URL=sqlite+aiosqlite:///./bot.db
```

## 4. Настроить systemd-сервис

```bash
# Проверь и при необходимости поправь пути в файле:
nano plum_api.service
# Убедись, что User= и WorkingDirectory= и ExecStart= указывают корректно

# Скопируй unit в systemd
sudo cp plum_api.service /etc/systemd/system/

# Перезагрузи systemd и запусти сервис
sudo systemctl daemon-reload
sudo systemctl enable plum_api
sudo systemctl start plum_api

# Проверь статус
sudo systemctl status plum_api
```

## 5. Проверить, что API работает

```bash
curl http://localhost:8080/healthz
# Ожидаемый ответ: {"status":"ok"}
```

## 6. Открыть порт в фаерволле (если не открыт)

```bash
sudo ufw allow 8080/tcp
sudo ufw reload
```

Проверить снаружи:
```
http://213.176.113.161:8080/docs
```

Должна открыться Swagger UI со всеми эндпоинтами.

## 7. (Опционально) Настроить nginx-прокси

Если хочешь использовать HTTPS (рекомендуется для продакшна):

```nginx
# /etc/nginx/sites-available/plum_api
server {
    listen 80;
    server_name 213.176.113.161;

    location /api/ {
        proxy_pass http://127.0.0.1:8080/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /docs {
        proxy_pass http://127.0.0.1:8080/docs;
    }

    location /openapi.json {
        proxy_pass http://127.0.0.1:8080/openapi.json;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/plum_api /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

После этого можно поменять `_base` в `api_service.dart` на `http://213.176.113.161/api`.

## 8. Деплой Flutter

```bash
cd flutter_app
flutter pub get
flutter build web --release
# Скопировать build/web/ на сервер или GitHub Pages
```
