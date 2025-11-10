"""
Загрузка и валидация конфигурации приложения.

Используется pydantic для работы с переменными окружения (.env).
"""

from pydantic import BaseModel, Field, AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional


class Settings(BaseSettings):
    """
    Настройки бота, загружаемые из окружения.

    - TELEGRAM_BOT_TOKEN: токен бота;
    - MAIN_ADMIN_ID: основной админ (используется в анонимных обращениях);
    - ADMIN_USER_IDS: список числовых ID администраторов;
    - ADMIN_NOTIFY_CHAT_ID: чат, куда слать уведомления для админов (опц.);
    - TARGET_CHAT_ID: ID целевого чата для приглашения;
    - START_PHOTO_URL: URL или file_id изображения для /start;
    - START_CAPTION: текст описания для экрана /start;
    - DATABASE_URL: строка подключения SQLAlchemy;
    - ROSTER_SEED_FILE: файл с исходной «базой» (необязательно);
    - RULES_URL: ссылка на свод правил (Telegra.ph).
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    TELEGRAM_BOT_TOKEN: str = Field(..., min_length=10)
    MAIN_ADMIN_ID: Optional[int] = None
    ADMIN_USER_IDS: List[int] = Field(default_factory=list)
    ADMIN_NOTIFY_CHAT_ID: Optional[int] = None
    TARGET_CHAT_ID: int
    START_PHOTO_URL: str
    START_CAPTION: str = "Добро пожаловать!"
    DATABASE_URL: str = "sqlite+aiosqlite:///./bot.db"
    ROSTER_SEED_FILE: Optional[str] = None
    RULES_URL: str


settings = Settings()
