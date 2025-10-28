#!/usr/bin/env python3
"""
Точка входа для запуска бота.
- Фиксирует рабочую директорию на папку проекта (важно для относительных путей: ./bot.db и т.п.)
- Подключает src в sys.path
- (Опционально) грузит переменные из .env, если установлен python-dotenv
- Запускает main() через asyncio.run() с корректной обработкой сигналов
"""
import os
import sys
import asyncio
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

sys.path.insert(0, str(BASE_DIR / "src"))

try:
    from dotenv import load_dotenv  # pip install python-dotenv
    load_dotenv(dotenv_path=BASE_DIR / ".env")
except Exception:
    pass

from bot.main import main  # noqa: E402


async def _run():
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    for sig in ("SIGINT", "SIGTERM"):
        try:
            import signal
            loop.add_signal_handler(getattr(signal, sig), stop.set)
        except Exception:
            pass


    task = asyncio.create_task(main())
    done, pending = await asyncio.wait(
        {task, asyncio.create_task(stop.wait())},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if stop.is_set():
        for t in pending:
            t.cancel()
        try:
            await asyncio.wait_for(task, timeout=10)
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(_run())
