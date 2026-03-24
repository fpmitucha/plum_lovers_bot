"""
FastAPI-приложение для платформы.

Запускается независимо от Telegram-бота, но использует те же
SQLAlchemy-модели и ту же базу данных (bot.db).

Эндпоинты:
  GET /api/me         — профиль текущего пользователя (по initData)
  GET /api/deadlines  — список ближайших дедлайнов
"""

from datetime import datetime, timezone

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import settings
from bot.models.models import Profile, Deadline
from api.auth import get_telegram_user
from api.schemas import ProfileOut, DeadlineOut

# ---------------------------------------------------------------------------
# Движок БД — тот же файл, что использует бот
# ---------------------------------------------------------------------------
_engine = create_async_engine(settings.DATABASE_URL, future=True, echo=False)
_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=_engine, expire_on_commit=False
)


async def get_db() -> AsyncSession:
    async with _session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Plum Lovers Platform API",
    version="1.0.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    # Разрешаем запросы с любого origin (Telegram WebApp открывается с telegram.org)
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Роуты
# ---------------------------------------------------------------------------

@app.get("/api/me", response_model=ProfileOut, summary="Профиль текущего пользователя")
async def get_me(
    tg_user: dict = Depends(get_telegram_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileOut:
    """
    Возвращает профиль пользователя из таблицы profiles по Telegram user_id.
    Создаёт минимальную запись, если пользователь ещё не зарегистрирован в боте.
    """
    telegram_id: int = tg_user["id"]

    result = await db.execute(
        select(Profile).where(Profile.user_id == telegram_id)
    )
    profile = result.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Профиль не найден. Напишите боту /start для регистрации.",
        )

    return ProfileOut(
        telegram_id=profile.user_id,
        username=profile.username,
        eng_group=profile.eng_group,
    )


@app.get(
    "/api/deadlines",
    response_model=list[DeadlineOut],
    summary="Ближайшие дедлайны",
)
async def get_deadlines(
    tg_user: dict = Depends(get_telegram_user),
    db: AsyncSession = Depends(get_db),
) -> list[DeadlineOut]:
    """
    Возвращает все дедлайны у которых end_at > сейчас, отсортированные по end_at.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # SQLite хранит naive
    result = await db.execute(
        select(Deadline)
        .where(Deadline.end_at >= now)
        .order_by(Deadline.end_at)
        .limit(50)
    )
    rows = result.scalars().all()
    return [
        DeadlineOut(
            id=d.id,
            course_name=d.course_name,
            task_name=d.task_name,
            start_at=d.start_at,
            end_at=d.end_at,
        )
        for d in rows
    ]


@app.get("/healthz", include_in_schema=False)
async def healthcheck():
    return {"status": "ok"}
