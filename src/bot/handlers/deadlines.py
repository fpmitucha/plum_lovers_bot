from __future__ import annotations


from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
import logging
from bot.utils.repo import Repo
from datetime import datetime
from zoneinfo import ZoneInfo

router = Router(name="deadlines")

ru_programs = [
    "[F25] Алгоритмы и структуры данных",
    "[F25] Аналитическая геометрия и линейная алгебра",
    "[F25] Введение в комбинаторику и дискретную математику",
    "[F25] Математический анализ",
    "[F25] Основы и методология программирования",
]

en_programs = [
    "[F25] Analytical Geometry and Linear Algebra I",
    "[F25] Computer Architecture",
    "[F25] Introduction to Programming",
    "[F25] Mathematical Analysis I",
    "[F25] Философия",
]
programs_courses = {
    "MFAI": [*ru_programs, "[F25] Общая физика"],
    "AI360": ru_programs,
    "RO": [*ru_programs, "[F25] Общая физика"],
    "CSE": en_programs,
    "DSAI": en_programs,
}

eng_lang_courses = {
    "FL": "[F25] Foreign Language (Tue/Thu)",
    "EAP": "[F25] English for academic purposes on Tue/Thu",
    "AWA1": "[F25] Academic Writing and Argumentation on Mon/Wed",
}
WEEKDAY_MAP = {
    "Monday": "ПН",
    "Tuesday": "ВТ",
    "Wednesday": "СР",
    "Thursday": "ЧТ",
    "Friday": "ПТ",
    "Saturday": "СБ",
    "Sunday": "ВС",
}


@router.message(Command("deadlines"))
async def cmd_deadlines(message: Message, session_maker: async_sessionmaker[AsyncSession]) -> None:
    logger = logging.getLogger("innopls-bot")
    # logger.info(f"Команда /deadlines вызвана пользователем {message.from_user.id}")
    async with session_maker() as s:
        repo = Repo(s)

        app_user = await repo.get_last_application_for_user(user_id=message.from_user.id)
        user = await repo.ensure_profile(user_id=message.from_user.id, username=None, slug=None)
        if app_user.slug.split("-")[2] not in ["Innopolis", "Inno", "innopolis", "inno"]:
            deadline_in_str = "В данный момент команда доступна только для студентов иннополиса ("
        else:
            if user.eng_group:
                user_courses = [
                    *programs_courses[app_user.slug.split("-")[3]],
                    eng_lang_courses[user.eng_group],
                ]
                if len(user_courses) == 0:
                    deadline_in_str = "Проблема с названиями программы"
                else:
                    user_deadlines = await repo.get_deadlines(
                        course_names=user_courses,
                    )
                    # logger.info("User deadlines:" + str(user_deadlines))
                    output_lines = [
                        f"Список дедлайнов ({app_user.slug.split('-')[3]}, {user.eng_group}):"
                    ]
                    current_course = None

                    for dl in user_deadlines:
                        if dl.course_name != current_course:
                            current_course = dl.course_name
                            output_lines.append(f"\n{dl.course_name}:")
                        # Форматируем дату: MM-DD-День_недели (на русском)
                        weekday_en = dl.end_at.strftime("%A")
                        weekday_ru = WEEKDAY_MAP.get(weekday_en, weekday_en)
                        date_str = dl.end_at.strftime("%m-%d") + "-" + weekday_ru
                        output_lines.append(f"   * {date_str}: {dl.task_name}")

                    deadline_in_str = (
                        "\n".join(output_lines) if len(output_lines) >= 1 else "Дедлайны не найдены"
                    )
            else:
                deadline_in_str = "Выберете группу английского в натройках"

    await message.answer(
        deadline_in_str,
        parse_mode="HTML",
    )
