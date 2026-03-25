"""
Точка запуска API-сервера (отдельный процесс от бота).
Запускать из корня репозитория:
    python run_api.py
"""

import sys
import os

# Добавляем src/ в путь поиска модулей, чтобы работали импорты bot.* и api.*
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api.app:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        log_level="info",
    )
