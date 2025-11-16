import asyncio
import logging
from pathlib import Path
import ast

from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from bot.config import settings
from datetime import datetime, timedelta

from src.bot.utils.repo import Repo

last_events = ["120000"] * len(settings.DONOR_MAILS)


async def parse_deadlines(session_maker: async_sessionmaker[AsyncSession]) -> None:
    logger = logging.getLogger("innopls-bot")
    for i in range(len(settings.DONOR_MAILS)):
        cur_mail = settings.DONOR_MAILS[i]
        cur_pass = settings.DONOR_PASSWORDS[i]

        logger.info(cur_mail + " " + cur_pass)
        cmd = [
            "python",
            "scripts/get_inno_deadlines.py",
            "--user",
            cur_mail,
            "--pass",
            cur_pass,
            "--last_event",
            last_events[i],
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(Path.cwd()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.info("Код который вернул скрипт: " + str(process.returncode))
            logger.info(stderr.decode().strip())
            logger.info(stdout.decode().strip())
            continue

        s = stdout.decode().strip().split("Deadlines:")[1]
        tasks = ast.literal_eval(s)
        async with session_maker() as s:
            repo = Repo(s)

            for task in tasks:
                await repo.add_deadline(
                    task_id=task["task_id"],
                    course_name=task["course_name"],
                    task_name=task["activityname"],
                    start_at=datetime.now(ZoneInfo("Europe/Moscow")) - timedelta(minutes=5),
                    end_at=datetime.fromtimestamp(task["timestart"], tz=ZoneInfo("Europe/Moscow")),
                )
