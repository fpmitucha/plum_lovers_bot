"""
FastAPI-приложение для платформы.

Запускается независимо от Telegram-бота, но использует те же
SQLAlchemy-модели и ту же базу данных (bot.db).

Эндпоинты:
  GET  /api/me              — профиль текущего пользователя (по initData)
  GET  /api/deadlines       — список ближайших дедлайнов
  POST /api/avatar/upload   — загрузка аватарки в S3
  POST /api/auth/magic-login — автовход по токену из бота
  POST /api/auth/login       — вход по логину/паролю
  POST /api/auth/change-password — смена пароля
"""

import hashlib
import secrets
import string
from datetime import datetime, timezone

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Header, status
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


@app.on_event("startup")
async def _migrate_web_credentials():
    async with _engine.begin() as conn:
        await conn.execute(sa_text_migrate("""
            CREATE TABLE IF NOT EXISTS web_credentials (
                tg_user_id INTEGER PRIMARY KEY,
                login TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """))


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
# Auth: magic-link + login/password
# ---------------------------------------------------------------------------

from datetime import timedelta
from pydantic import BaseModel
from sqlalchemy import text as sql_text_api


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _generate_password(length: int = 8) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


class MagicLoginRequest(BaseModel):
    token: str


class AuthResponse(BaseModel):
    tg_user_id: int
    login: str
    password: str | None = None  # только при первом входе
    username: str
    karma: int
    rank: int
    avatar_url: str | None = None
    eng_group: str | None = None
    is_new: bool = False


async def _get_karma_rank(db: AsyncSession, tg_id: int) -> tuple[int, int]:
    try:
        karma_row = await db.execute(
            sql_text_api("SELECT COALESCE(karma, 0) as total FROM profiles WHERE user_id = :uid"),
            {"uid": tg_id},
        )
        karma_data = karma_row.fetchone()
        karma = int(karma_data.total) if karma_data else 0

        rank_row = await db.execute(
            sql_text_api("""
                SELECT COUNT(*) + 1 as rank FROM profiles
                WHERE COALESCE(karma, 0) > (SELECT COALESCE(karma, 0) FROM profiles WHERE user_id = :uid)
            """),
            {"uid": tg_id},
        )
        rank_data = rank_row.fetchone()
        rank = int(rank_data.rank) if rank_data else 0
        return karma, rank
    except Exception:
        return 0, 0


@app.post("/api/auth/magic-login", response_model=AuthResponse, summary="Автовход по токену из бота")
async def magic_login(
    body: MagicLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    # Валидируем токен
    result = await db.execute(
        sql_text_api(
            "SELECT code, tg_user_id, tg_username, created_at, used "
            "FROM platform_link_tokens WHERE code = :code"
        ),
        {"code": body.token.strip()},
    )
    row = result.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Токен не найден")
    if row.used:
        raise HTTPException(status_code=400, detail="Токен уже использован")

    created_at = datetime.fromisoformat(row.created_at).replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - created_at > timedelta(minutes=15):
        raise HTTPException(status_code=400, detail="Токен истёк. Запроси новый в боте.")

    tg_id = row.tg_user_id
    tg_username = row.tg_username or ""

    # Отметить использованным
    await db.execute(
        sql_text_api("UPDATE platform_link_tokens SET used = 1 WHERE code = :code"),
        {"code": body.token.strip()},
    )

    # Получить профиль
    prof = await db.execute(
        sql_text_api("SELECT user_id, username, eng_group, avatar_url FROM profiles WHERE user_id = :uid"),
        {"uid": tg_id},
    )
    profile = prof.fetchone()
    if profile is None:
        raise HTTPException(status_code=404, detail="Профиль не найден в боте. Напиши /start боту.")

    # Проверяем, есть ли уже web_credentials
    cred = await db.execute(
        sql_text_api("SELECT login, password_hash FROM web_credentials WHERE tg_user_id = :uid"),
        {"uid": tg_id},
    )
    cred_row = cred.fetchone()

    is_new = False
    raw_password = None

    if cred_row is None:
        # Первый вход — создаём логин/пароль
        login = tg_username if tg_username else f"user_{tg_id}"
        raw_password = _generate_password()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        await db.execute(
            sql_text_api(
                "INSERT INTO web_credentials (tg_user_id, login, password_hash, created_at) "
                "VALUES (:uid, :login, :phash, :ts)"
            ),
            {"uid": tg_id, "login": login, "phash": _hash_password(raw_password), "ts": now},
        )
        is_new = True
    else:
        login = cred_row.login

    await db.commit()

    karma, rank = await _get_karma_rank(db, tg_id)

    return AuthResponse(
        tg_user_id=tg_id,
        login=login,
        password=raw_password,
        username=profile.username or tg_username,
        karma=karma,
        rank=rank,
        avatar_url=profile.avatar_url,
        eng_group=profile.eng_group,
        is_new=is_new,
    )


class LoginRequest(BaseModel):
    login: str
    password: str


@app.post("/api/auth/login", response_model=AuthResponse, summary="Вход по логину/паролю")
async def auth_login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    cred = await db.execute(
        sql_text_api("SELECT tg_user_id, login, password_hash FROM web_credentials WHERE login = :login"),
        {"login": body.login.strip()},
    )
    cred_row = cred.fetchone()
    if cred_row is None:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    computed_hash = _hash_password(body.password)
    stored_hash = cred_row.password_hash
    import logging
    logging.warning(f"AUTH DEBUG: login={body.login}, computed={computed_hash[:16]}..., stored={stored_hash[:16]}..., match={computed_hash == stored_hash}")

    if computed_hash != stored_hash:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    tg_id = cred_row.tg_user_id

    prof = await db.execute(
        sql_text_api("SELECT user_id, username, eng_group, avatar_url FROM profiles WHERE user_id = :uid"),
        {"uid": tg_id},
    )
    profile = prof.fetchone()
    if profile is None:
        raise HTTPException(status_code=404, detail="Профиль не найден")

    karma, rank = await _get_karma_rank(db, tg_id)

    return AuthResponse(
        tg_user_id=tg_id,
        login=cred_row.login,
        username=profile.username or "",
        karma=karma,
        rank=rank,
        avatar_url=profile.avatar_url,
        eng_group=profile.eng_group,
    )


class ChangePasswordRequest(BaseModel):
    login: str
    old_password: str
    new_password: str


@app.post("/api/auth/change-password", summary="Смена пароля")
async def change_password(
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    cred = await db.execute(
        sql_text_api("SELECT tg_user_id, password_hash FROM web_credentials WHERE login = :login"),
        {"login": body.login.strip()},
    )
    cred_row = cred.fetchone()
    if cred_row is None or _hash_password(body.old_password) != cred_row.password_hash:
        raise HTTPException(status_code=401, detail="Неверный старый пароль")

    if len(body.new_password) < 4:
        raise HTTPException(status_code=400, detail="Пароль слишком короткий (минимум 4 символа)")

    await db.execute(
        sql_text_api("UPDATE web_credentials SET password_hash = :phash WHERE login = :login"),
        {"phash": _hash_password(body.new_password), "login": body.login.strip()},
    )
    await db.commit()
    return {"ok": True}


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
    result = await db.execute(
        sql_text_api("SELECT user_id, username, avatar_url FROM profiles WHERE user_id = :uid"),
        {"uid": tg_id},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден в боте")

    karma, rank = await _get_karma_rank(db, tg_id)

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
    x_login: str | None = Header(None, alias="X-Login"),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    db: AsyncSession = Depends(get_db),
) -> AvatarUploadResponse:
    """
    Принимает изображение (JPEG/PNG/WebP/GIF, до 2 MB),
    ресайзит до 256×256, загружает в S3 как WebP.
    Обновляет avatar_url в профиле пользователя.
    Авторизация: X-Login header (логин из web_credentials) или X-Telegram-Init-Data.
    """
    telegram_id: int | None = None

    # Авторизация по логину
    if x_login:
        cred = await db.execute(
            sql_text_api("SELECT tg_user_id FROM web_credentials WHERE login = :login"),
            {"login": x_login.strip()},
        )
        cred_row = cred.fetchone()
        if cred_row is None:
            raise HTTPException(status_code=401, detail="Неизвестный логин")
        telegram_id = cred_row.tg_user_id
    elif x_telegram_init_data:
        from api.auth import verify_telegram_init_data
        tg_user = verify_telegram_init_data(x_telegram_init_data)
        telegram_id = tg_user["id"]
    else:
        raise HTTPException(status_code=401, detail="Требуется авторизация")

    raw_bytes = await file.read()

    err = validate_avatar(file.content_type, len(raw_bytes))
    if err:
        raise HTTPException(status_code=400, detail=err)

    avatar_url = upload_avatar(raw_bytes, telegram_id)

    # Обновить avatar_url в БД
    await db.execute(
        sql_text_api("UPDATE profiles SET avatar_url = :url WHERE user_id = :uid"),
        {"url": avatar_url, "uid": telegram_id},
    )
    await db.commit()

    return AvatarUploadResponse(avatar_url=avatar_url)


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

class LeaderboardEntry(BaseModel):
    username: str
    karma: int
    rank: int
    avatar_url: str | None = None
    tg_user_id: int


@app.get("/api/leaderboard", response_model=list[LeaderboardEntry], summary="Топ по карме")
async def get_leaderboard(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[LeaderboardEntry]:
    result = await db.execute(
        sql_text_api("""
            SELECT user_id, username, COALESCE(karma, 0) as karma, avatar_url
            FROM profiles
            ORDER BY karma DESC
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = result.fetchall()
    return [
        LeaderboardEntry(
            tg_user_id=row.user_id,
            username=row.username or "",
            karma=row.karma,
            rank=i + 1,
            avatar_url=row.avatar_url,
        )
        for i, row in enumerate(rows)
    ]
