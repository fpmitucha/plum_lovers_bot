"""
Pydantic-схемы для ответов API.
Не зависят от SQLAlchemy-моделей напрямую — конвертация вручную.
"""

from datetime import datetime
from pydantic import BaseModel


class ProfileOut(BaseModel):
    telegram_id: int
    username: str | None = None
    eng_group: str | None = None
    avatar_url: str | None = None

    model_config = {"from_attributes": True}


class DeadlineOut(BaseModel):
    id: int
    course_name: str
    task_name: str
    start_at: datetime
    end_at: datetime

    model_config = {"from_attributes": True}
