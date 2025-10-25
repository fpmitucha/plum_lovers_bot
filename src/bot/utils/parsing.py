"""
Парсинг и валидация «slug» студента.

Формат (англ., 7 частей, разделённые дефисом):
first-last-university-program-group-course-startyear

Пример:
artem-tuchkov-Innopolis-AI360-01-1-25
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class StudentSlug:
    """
    Структурированное представление slug.

    Хранит каждую часть, чтобы при необходимости вести аналитику/валидацию на уровне полей.
    """
    first: str
    last: str
    university: str
    program: str
    group: str
    course: str
    start_year: str

    @property
    def raw(self) -> str:
        """Вернуть исходную строку slug в канонической форме."""
        return "-".join(
            [
                self.first,
                self.last,
                self.university,
                self.program,
                self.group,
                self.course,
                self.start_year,
            ]
        )


def parse_slug(slug: str) -> StudentSlug:
    """
    Провалидировать и распарсить slug.

    Требования:
    - строго 7 частей, разделённых дефисом;
    - части не пусты, допускаются латиница и цифры (минимальная валидация).

    :param slug: исходная строка от пользователя.
    :return: объект StudentSlug.
    :raises ValueError: при несоответствии формату.
    """
    parts = slug.strip().split("-")
    if len(parts) != 7:
        raise ValueError("Ожидается 7 частей через дефис: first-last-university-program-group-course-startyear")

    for p in parts:
        if not p or any(ch.isspace() for ch in p):
            raise ValueError("Части не должны быть пустыми и содержать пробелы")

    return StudentSlug(*parts)  # type: ignore[arg-type]


def normalize_slug(slug: str) -> str:
    """
    Привести slug к канонической форме.

    - Триминг;
    - Удаление повторных дефисов вокруг;
    - Без изменения регистра (пример допускает смешанный регистр).

    :param slug: исходная строка.
    :return: нормализованный slug.
    """
    return "-".join(part.strip() for part in slug.strip().split("-"))
