"""
Модуль конфигурации логирования.

Предназначен для единообразной настройки логирования во всём приложении.
"""

import logging
from logging import Logger


def setup_logging(level: int = logging.INFO) -> Logger:
    """
    Настроить формат и уровень логирования.

    :param level: Уровень логирования (по умолчанию INFO).
    :return: Корневой логгер.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    return logging.getLogger("innopls-bot")
