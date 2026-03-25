"""
FastAPI-приложение для платформы.

Запускается независимо от Telegram-бота, но использует те же
SQLAlchemy-модели и ту же базу данных (bot.db).

Эндпоинты:
  GET  /api/me              — профиль текущего пользователя (по initData)
  GET  /api/deadlines       — список ближайших дедлайнов
  POST /api/avatar/upload   — загрузка аватарки в S3
"""

from datetime import datetime, timezone

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text as sa_text_migrate
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
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# DB migration: добавить avatar_url в profiles, если колонки нет
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def _migrate_avatar_column():
    async with _engine.begin() as conn:
        # Проверяем, есть ли колонка avatar_url
        result = await conn.execute(sa_text_migrate("PRAGMA table_info(profiles)"))
        columns = [row[1] for row in result.fetchall()]
        if "avatar_url" not in columns:
            await conn.execute(sa_text_migrate(
                "ALTER TABLE profiles ADD COLUMN avatar_url TEXT"
            ))


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
        avatar_url=profile.avatar_url,
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


# ---------------------------------------------------------------------------
# Platform linking
# ---------------------------------------------------------------------------

from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from sqlalchemy import text as sql_text_api


class LinkVerifyRequest(BaseModel):
    code: str
    web_username: str


class LinkVerifyResponse(BaseModel):
    tg_user_id: int
    tg_username: str


@app.post("/api/link/verify", response_model=LinkVerifyResponse, summary="Verify platform link code")
async def verify_link_code(
    body: LinkVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> LinkVerifyResponse:
    """
    Verifies a 6-digit code generated by the bot.
    Returns tg_user_id and tg_username on success.
    """
    result = await db.execute(
        sql_text_api(
            "SELECT code, tg_user_id, tg_username, created_at, used "
            "FROM platform_link_tokens WHERE code = :code"
        ),
        {"code": body.code.strip()},
    )
    row = result.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Код не найден")

    if row.used:
        raise HTTPException(status_code=400, detail="Код уже использован")

    created_at = datetime.fromisoformat(row.created_at).replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - created_at > timedelta(minutes=15):
        raise HTTPException(status_code=400, detail="Код истёк. Запроси новый в боте.")

    # Mark as used
    await db.execute(
        sql_text_api("UPDATE platform_link_tokens SET used = 1 WHERE code = :code"),
        {"code": body.code.strip()},
    )
    await db.commit()

    return LinkVerifyResponse(
        tg_user_id=row.tg_user_id,
        tg_username=row.tg_username or "",
    )


# ---------------------------------------------------------------------------
# Public profile by TG ID (after linking, no initData needed)
# ---------------------------------------------------------------------------

class TgProfileOut(BaseModel):
    tg_user_id: int
    tg_username: str
    karma: int
    rank: int
    avatar_url: str | None = None


@app.get("/api/user-by-tg-id", response_model=TgProfileOut, summary="Get TG profile by ID")
async def get_user_by_tg_id(
    tg_id: int,
    db: AsyncSession = Depends(get_db),
) -> TgProfileOut:
    """
    Returns karma and rank for a given Telegram user ID.
    Used by the web platform after account linking.
    """
    result = await db.execute(
        sql_text_api("SELECT user_id, username, avatar_url FROM profiles WHERE user_id = :uid"),
        {"uid": tg_id},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден в боте")

    # Get karma
    karma_row = await db.execute(
        sql_text_api("SELECT COALESCE(SUM(value), 0) as total FROM karma_log WHERE target_id = :uid"),
        {"uid": tg_id},
    )
    karma_data = karma_row.fetchone()
    karma = int(karma_data.total) if karma_data else 0

    # Get rank
    rank_row = await db.execute(
        sql_text_api("""
            SELECT COUNT(*) + 1 as rank FROM profiles
            WHERE (SELECT COALESCE(SUM(value), 0) FROM karma_log WHERE target_id = user_id)
            > (SELECT COALESCE(SUM(value), 0) FROM karma_log WHERE target_id = :uid)
        """),
        {"uid": tg_id},
    )
    rank_data = rank_row.fetchone()
    rank = int(rank_data.rank) if rank_data else 0

    return TgProfileOut(
        tg_user_id=tg_id,
        tg_username=row.username or "",
        karma=karma,
        rank=rank,
        avatar_url=row.avatar_url,
    )


# ---------------------------------------------------------------------------
# Avatar upload
# ---------------------------------------------------------------------------

from api.s3 import upload_avatar, validate_avatar


class AvatarUploadResponse(BaseModel):
    avatar_url: str


@app.post("/api/avatar/upload", response_model=AvatarUploadResponse, summary="Загрузить аватарку")
async def upload_avatar_endpoint(
    file: UploadFile = File(...),
    tg_user: dict = Depends(get_telegram_user),
    db: AsyncSession = Depends(get_db),
) -> AvatarUploadResponse:
    """
    Принимает изображение (JPEG/PNG/WebP/GIF, до 2 MB),
    ресайзит до 256×256, загружает в S3 как WebP.
    Обновляет avatar_url в профиле пользователя.
    """
    raw_bytes = await file.read()

    err = validate_avatar(file.content_type, len(raw_bytes))
    if err:
        raise HTTPException(status_code=400, detail=err)

    telegram_id: int = tg_user["id"]
    avatar_url = upload_avatar(raw_bytes, telegram_id)

    # Обновить avatar_url в БД
    await db.execute(
        sql_text_api("UPDATE profiles SET avatar_url = :url WHERE user_id = :uid"),
        {"url": avatar_url, "uid": telegram_id},
    )
    await db.commit()

    return AvatarUploadResponse(avatar_url=avatar_url)
