from __future__ import annotations

"""
КАРМА:
- +1 автору сообщения, если на него отвечают словами из белого списка
- +1 автору сообщения, если на него ставят позитивную реакцию
- -1 автору сообщения, если на него ставят негативную реакцию
- /stats — показать сегодняшнюю и суммарную статистику (+/-) и текущую карму

Технически:
- кешируем авторов сообщений (chat_id, message_id -> author_id) + дублируем в БД (msg_authors),
  чтобы переживать перезапуск бота и не терять автора.
- события храним в karma_events (создаётся автоматически; при необходимости — авто-миграция колонок)
- начисляем только зарегистрированным пользователям (Repo.has_registered)
"""

import asyncio
import re
import logging
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import F, Router
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command
from aiogram.types import Message, MessageReactionUpdated
from aiogram.types.reaction_type_emoji import ReactionTypeEmoji

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy import text

from bot.utils.repo import Repo

router = Router(name="karma_auto")
log = logging.getLogger("innopls-bot")

# -------- настройки / словари --------

# слова-триггеры в реплае (+1 автору исходного сообщения)
POSITIVE_WORDS = {"+", "класс", "согл", "+реп", "спасибо", "круто", "топ"}

# позитивные реакции (любые сердца считаем «плюсом»)
POSITIVE_EMOJI = {
    "👍", "🔥",
    "❤️", "💙", "💚", "💛", "🧡", "💜", "🤎", "🖤", "🤍",
    "❤️‍🔥", "💖", "💗", "💓", "💕"
}
NEGATIVE_EMOJI = {"👎", "💩", "🤮"}

_DDL_LOCK = asyncio.Lock()

# ограничение на размер кеша авторов
_CACHE_LIMIT = 50_000

# (chat_id, msg_id) -> author_user_id
_msg_author_cache: "OrderedDict[tuple[int, int], int]" = OrderedDict()


# -------- кеш авторов --------
def _cache_put(chat_id: int, msg_id: int, user_id: int) -> None:
    key = (int(chat_id), int(msg_id))
    if key in _msg_author_cache:
        _msg_author_cache.move_to_end(key)
    _msg_author_cache[key] = int(user_id)
    while len(_msg_author_cache) > _CACHE_LIMIT:
        _msg_author_cache.popitem(last=False)


def _cache_get_author(chat_id: int, msg_id: int) -> Optional[int]:
    key = (int(chat_id), int(msg_id))
    v = _msg_author_cache.get(key)
    if v is not None:
        _msg_author_cache.move_to_end(key)
    return v


# -------- SQL utils --------

_CREATE_EVENTS_BASE_SQL = """
CREATE TABLE IF NOT EXISTS karma_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL, -- автор поста, кому изменяем карму
    actor_id   INTEGER,          -- кто поставил реакцию/написал реплай
    chat_id    INTEGER,
    delta      INTEGER NOT NULL, -- +1 / -1
    reason     TEXT,
    created_at TEXT NOT NULL
);
"""

_CREATE_MSG_AUTHORS_SQL = """
CREATE TABLE IF NOT EXISTS msg_authors (
    chat_id  INTEGER NOT NULL,
    msg_id   INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    PRIMARY KEY (chat_id, msg_id)
);
"""

async def _ensure_columns(session, table: str, columns: dict[str, str]) -> None:
    """
    Гарантирует, что в таблице есть указанные колонки.
    Идемпотентно, устойчиво к конкурентным ALTER TABLE.
    """
    async with _DDL_LOCK:
        res = await session.execute(text(f"PRAGMA table_info({table})"))
        existing = {row[1] for row in res.fetchall()}  # имена колонок
        for col, typ in columns.items():
            if col in existing:
                continue
            try:
                await session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))
                await session.commit()
            except OperationalError as e:
                # Если другой поток успел добавить колонку — тихо игнорируем
                if "duplicate column name" in str(e).lower():
                    await session.rollback()
                    continue
                raise
            except Exception:
                # На всякий случай откат и проброс дальше
                await session.rollback()
                raise


async def _ensure_aux_tables(session) -> None:
    """
    Создаём таблицы при первом запуске и догоним схему для старых БД.
    """
    # Базовые таблицы (со всеми актуальными колонками)
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS karma_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER NOT NULL,
            actor_id  INTEGER NOT NULL,
            chat_id   INTEGER NOT NULL,
            msg_id    INTEGER,               -- может быть NULL для старых записей
            delta     INTEGER NOT NULL,
            reason    TEXT,
            created_at TEXT NOT NULL
        )
    """))
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS msg_authors (
            chat_id  INTEGER NOT NULL,
            msg_id   INTEGER NOT NULL,
            user_id  INTEGER NOT NULL,
            PRIMARY KEY (chat_id, msg_id)
        )
    """))
    await session.commit()

    # Миграция старых установок: догоним недостающие колонки у karma_events
    await _ensure_columns(session, "karma_events", {
        "user_id":   "INTEGER",
        "actor_id":  "INTEGER",
        "chat_id":   "INTEGER",
        "msg_id":    "INTEGER",
        "delta":     "INTEGER",
        "reason":    "TEXT",
        "created_at":"TEXT"
    })
async def _store_msg_author(session: AsyncSession, *, chat_id: int, msg_id: int, user_id: int) -> None:
    await _ensure_aux_tables(session)
    await session.execute(
        text(
            "INSERT OR IGNORE INTO msg_authors (chat_id, msg_id, user_id) "
            "VALUES (:c, :m, :u)"
        ),
        {"c": int(chat_id), "m": int(msg_id), "u": int(user_id)},
    )
    await session.commit()


async def _load_msg_author(session: AsyncSession, *, chat_id: int, msg_id: int) -> Optional[int]:
    await _ensure_aux_tables(session)
    res = await session.execute(
        text("SELECT user_id FROM msg_authors WHERE chat_id=:c AND msg_id=:m"),
        {"c": int(chat_id), "m": int(msg_id)},
    )
    val = res.scalar()
    return int(val) if val is not None else None


async def _log_event(session: AsyncSession, *, user_id: int, actor_id: int | None,
                     chat_id: int, msg_id: int, delta: int, reason: str) -> None:
    await _ensure_aux_tables(session)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    await session.execute(
        text(
            "INSERT INTO karma_events (user_id, actor_id, chat_id, msg_id, delta, reason, created_at) "
            "VALUES (:uid, :actor, :chat, :mid, :d, :r, :ts)"
        ),
        {"uid": int(user_id), "actor": (None if actor_id is None else int(actor_id)),
         "chat": int(chat_id), "mid": int(msg_id), "d": int(delta), "r": reason, "ts": ts},
    )
    await session.commit()


async def _stats_for_user(session: AsyncSession, user_id: int) -> tuple[int, int, int, int]:
    """return (today_plus, today_minus, total_plus, total_minus)"""
    await _ensure_aux_tables(session)
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    start_s = start.strftime("%Y-%m-%d %H:%M:%S")
    end_s = end.strftime("%Y-%m-%d %H:%M:%S")

    # total
    total = await session.execute(
        text(
            "SELECT "
            "SUM(CASE WHEN delta>0 THEN 1 ELSE 0 END) AS plus, "
            "SUM(CASE WHEN delta<0 THEN 1 ELSE 0 END) AS minus "
            "FROM karma_events WHERE user_id=:uid"
        ),
        {"uid": int(user_id)},
    )
    t_plus, t_minus = total.fetchone() or (0, 0)
    t_plus = int(t_plus or 0)
    t_minus = int(t_minus or 0)

    # today
    today = await session.execute(
        text(
            "SELECT "
            "SUM(CASE WHEN delta>0 THEN 1 ELSE 0 END) AS plus, "
            "SUM(CASE WHEN delta<0 THEN 1 ELSE 0 END) AS minus "
            "FROM karma_events "
            "WHERE user_id=:uid AND created_at >= :start AND created_at < :end"
        ),
        {"uid": int(user_id), "start": start_s, "end": end_s},
    )
    d_plus, d_minus = today.fetchone() or (0, 0)
    d_plus = int(d_plus or 0)
    d_minus = int(d_minus or 0)

    return d_plus, d_minus, t_plus, t_minus


# -------- бизнес-логика --------

def _normalize_text(s: str | None) -> str:
    if not s:
        return ""
    t = s.lower()
    # убираем «мусор», но не трогаем символ '+'
    t = re.sub(r"[^\w\s+]+", " ", t, flags=re.UNICODE)
    return t


def _text_matches_positive(text: str) -> bool:
    if not text:
        return False
    t = _normalize_text(text)
    if t.strip() == "+":  # отдельный кейс
        return True
    return any(word in t.split() or f" {word} " in f" {t} " for word in POSITIVE_WORDS)


def _extract_emoji_set(reactions: list) -> set[str]:
    out: set[str] = set()
    for r in reactions or []:
        if isinstance(r, ReactionTypeEmoji):
            out.add(r.emoji)
    return out


async def _apply_karma(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    target_user_id: int,
    actor_id: Optional[int],
    chat_id: int,
    msg_id: int,
    delta: int,
    reason: str,
) -> None:
    """Начислить/списать карму зарегистрированному пользователю и залогировать событие."""
    async with session_maker() as session:
        repo = Repo(session)
        if not await repo.has_registered(target_user_id):
            return
        # изменяем карму ровно по 1 за событие
        await repo.add_karma(target_user_id, 1 if delta > 0 else -1)
        await _log_event(
            session,
            user_id=target_user_id,
            actor_id=actor_id,
            chat_id=chat_id,
            msg_id=msg_id,
            delta=1 if delta > 0 else -1,
            reason=reason,
        )


# ===================== ХЭНДЛЕРЫ =====================

# --- /stats — ставим ПЕРВЫМ, чтобы точно срабатывало
@router.message(Command("stats"))
async def cmd_stats(message: Message, session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        repo = Repo(session)
        d_plus, d_minus, t_plus, t_minus = await _stats_for_user(session, message.from_user.id)
        karma = await repo.get_karma(message.from_user.id)

    text_msg = (
        "📊 <b>Статистика кармы</b>\n"
        f"Сегодня:  +{d_plus} / -{d_minus}\n"
        f"Всего:    +{t_plus} / -{t_minus}\n"
        f"Текущая карма: <b>{karma}</b>"
    )
    await message.answer(text_msg, parse_mode=ParseMode.HTML)


# --- кешируем авторов всех сообщений в ГРУППАХ (+ пишем в БД)
@router.message()
async def cache_authors(message: Message, session_maker: async_sessionmaker[AsyncSession]) -> None:
    if message.chat.type not in (ChatType.SUPERGROUP, ChatType.GROUP):
        return
    if not message.from_user or message.from_user.is_bot:
        return
    if not message.message_id:
        return

    _cache_put(message.chat.id, message.message_id, message.from_user.id)
    # в БД
    async with session_maker() as session:
        try:
            await _store_msg_author(
                session, chat_id=message.chat.id, msg_id=message.message_id, user_id=message.from_user.id
            )
        except Exception as e:
            log.warning("msg_authors insert failed: %s", e)


# --- Ответ со словами-триггерами → +1 автору исходного сообщения
@router.message(F.reply_to_message, F.text | F.caption)
async def on_reply_keywords(message: Message, session_maker: async_sessionmaker[AsyncSession]) -> None:
    if message.chat.type not in (ChatType.SUPERGROUP, ChatType.GROUP):
        return
    replied = message.reply_to_message
    if not replied or not replied.from_user:
        return
    if message.from_user and message.from_user.id == replied.from_user.id:  # не начисляем себе
        return

    text_msg = message.text or message.caption or ""
    if not _text_matches_positive(text_msg):
        return

    await _apply_karma(
        session_maker,
        target_user_id=replied.from_user.id,
        actor_id=(message.from_user.id if message.from_user else None),
        chat_id=message.chat.id,
        msg_id=replied.message_id,
        delta=+1,
        reason="reply:keyword",
    )


# --- Реакции
@router.message_reaction()
async def on_reaction(event: MessageReactionUpdated, session_maker: async_sessionmaker[AsyncSession]) -> None:
    chat_id = event.chat.id
    msg_id = event.message_id
    actor_id = event.user.id if event.user else None

    # 1) пытаемся из кеша (в этом запуске)
    author_id = _cache_get_author(chat_id, msg_id)

    # 2) если нет — из БД (переживает перезапуск)
    if author_id is None:
        async with session_maker() as session:
            author_id = await _load_msg_author(session, chat_id=chat_id, msg_id=msg_id)

    # если автора нет — вероятно, у бота включён Privacy Mode, и он не видел исходное сообщение
    if not author_id:
        log.info(
            "reaction ignored: author unknown (chat_id=%s, msg_id=%s). "
            "Включён Privacy Mode или сообщение было до запуска бота.",
            chat_id,
            msg_id,
        )
        return

    # не считаем «сам себе реакцию»
    if actor_id and actor_id == author_id:
        return

    new_emj = _extract_emoji_set(event.new_reaction or [])
    old_emj = _extract_emoji_set(event.old_reaction or [])

    added = new_emj - old_emj
    removed = old_emj - new_emj

    delta = 0
    for e in added:
        if e in POSITIVE_EMOJI:
            delta += 1
        elif e in NEGATIVE_EMOJI:
            delta -= 1
    for e in removed:
        if e in POSITIVE_EMOJI:
            delta -= 1
        elif e in NEGATIVE_EMOJI:
            delta += 1

    if delta == 0:
        return

    # применяем ПО 1 очку, даже если delta > 1 (по ТЗ)
    await _apply_karma(
        session_maker,
        target_user_id=author_id,
        actor_id=actor_id,
        chat_id=chat_id,
        msg_id=msg_id,
        delta=(1 if delta > 0 else -1),
        reason="reaction",
    )
