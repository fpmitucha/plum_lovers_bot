"""
ORM-модели SQLAlchemy для бота.

Таблицы:
- roster       — список «участников» (используется на чтение).
- applications — заявки пользователей на вступление.
- invites      — выданные персональные инвайты.
- blacklist    — заблокированные пользователи.
- admins       — дополнительные администраторы (кроме главного).
- profiles     — карточки участников (кабинет: username, очки/карма и т.д.).

Примечание по SQLite:
- Столбцы created_at/updated_at хранятся как TEXT (UTC, формат YYYY-MM-DD HH:MM:SS).
"""

from sqlalchemy import (
    BigInteger,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Column,
    ForeignKey,
)
from sqlalchemy.sql import text as sa_text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Roster(Base):
    """
    Строка в «реестре участников».

    Атрибуты:
        id         (int)     — PK.
        slug       (str)     — нормализованный slug участника (уникален).
        created_at (str)     — дата/время создания записи (UTC, TEXT).
    """
    __tablename__ = "roster"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))


class Application(Base):
    """
    Заявка на вступление.

    Атрибуты:
        id         (int)      — PK.
        user_id    (int)      — Telegram user id заявителя.
        username   (str|None) — @username заявителя.
        slug       (str)      — нормализованный slug.
        status     (str)      — 'pending'|'approved'|'rejected'|'done'.
        reason     (str|None) — причина отклонения/примечание (опц).
        created_at (str)      — когда создана заявка (UTC, TEXT).
        updated_at (str)      — когда последний раз правили (UTC, TEXT).
    """
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(BigInteger, index=True, nullable=False)
    username = Column(String, nullable=True)
    slug = Column(String, nullable=False)

    status = Column(String, nullable=False, server_default=sa_text("'pending'"))
    reason = Column(Text, nullable=True)

    created_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))
    updated_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))


class Invite(Base):
    """
    Выданный персональный инвайт в целевой чат.

    Атрибуты:
        id          (int)  — PK.
        user_id     (int)  — кому выдали.
        chat_id     (int)  — id целевого чата.
        invite_link (str)  — URL приглашения (уникален).
        expires_at  (str)  — дата/время истечения (UTC, TEXT).
        created_at  (str)  — когда выдали (UTC, TEXT).
        updated_at  (str)  — когда правили (UTC, TEXT).
    """
    __tablename__ = "invites"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(BigInteger, index=True, nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    invite_link = Column(String, nullable=False, unique=True)
    expires_at = Column(String, nullable=False)

    created_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))
    updated_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))


class Blacklist(Base):
    """
    Чёрный список пользователей.

    Атрибуты:
        id         (int)      — PK.
        user_id    (int)      — Telegram user id (уникален).
        reason     (str|None) — причина блокировки/комментарий.
        created_at (str)      — дата/время добавления (UTC, TEXT).
    """
    __tablename__ = "blacklist"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(BigInteger, index=True, nullable=False, unique=True)
    reason = Column(Text, nullable=True)

    created_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_blacklist_user"),
    )


class Admin(Base):
    """
    Дополнительные администраторы (кроме главного).

    Атрибуты:
        id         (int)  — PK.
        user_id    (int)  — Telegram user id (уникален).
        created_at (str)  — когда добавили.
    """
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, index=True, unique=True, nullable=False)
    created_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_admin_user"),
    )


class Profile(Base):
    """
    Профиль участника (для личного кабинета/кармы).

    Атрибуты:
        id         (int)      — PK.
        user_id    (int)      — Telegram user id (уникален).
        username   (str|None) — @username на момент фиксации (опционально).
        points     (int)      — очки/карма (по умолчанию 10).
        created_at (str)      — когда создан профиль.
        updated_at (str)      — когда последний раз обновляли.
    """
    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, index=True, unique=True, nullable=False)
    username = Column(String, nullable=True)
    points = Column(Integer, nullable=False, server_default=sa_text("10"))

    created_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))
    updated_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_profile_user"),
    )


class AnonDialog(Base):
    """
    Анонимный диалог: пользователь ↔ пользователь/админ.
    kind: 'user' | 'admin'
    status: 'active' | 'closed'
    """
    __tablename__ = "anon_dialogs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dialog_code = Column(String, nullable=False, unique=True, index=True)
    kind = Column(String, nullable=False, server_default=sa_text("'user'"))
    initiator_id = Column(BigInteger, nullable=False, index=True)
    target_id = Column(BigInteger, nullable=False, index=True)
    status = Column(String, nullable=False, server_default=sa_text("'active'"))
    created_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))
    closed_at = Column(String, nullable=True)
    initiator_header_sent = Column(Integer, nullable=False, server_default=sa_text("0"))
    target_header_sent = Column(Integer, nullable=False, server_default=sa_text("0"))
    initiator_consent = Column(String, nullable=False, server_default=sa_text("'approved'"))
    target_consent = Column(String, nullable=False, server_default=sa_text("'approved'"))


class AnonMessage(Base):
    """
    Сообщения анонимного диалога, сохраняем для аудита/повторов.
    """
    __tablename__ = "anon_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dialog_id = Column(Integer, ForeignKey("anon_dialogs.id", ondelete="CASCADE"), index=True, nullable=False)
    sender_id = Column(BigInteger, nullable=False)
    recipient_id = Column(BigInteger, nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))
    is_delivered = Column(Integer, nullable=False, server_default=sa_text("1"))


class AnonPublicRequest(Base):
    """
    Очередь анонимных сообщений в общий чат (с модерацией).
    """
    __tablename__ = "anon_public_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    text = Column(Text, nullable=False)
    status = Column(String, nullable=False, server_default=sa_text("'pending'"))  # pending|approved|rejected|failed
    created_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))
    processed_at = Column(String, nullable=True)
    processed_by = Column(BigInteger, nullable=True)
    reason = Column(Text, nullable=True)


class AnonPreference(Base):
    """
    Настройки анонимных чатов для пользователя.
    """
    __tablename__ = "anon_preferences"

    user_id = Column(BigInteger, primary_key=True)
    mode = Column(String, nullable=False, server_default=sa_text("'auto'"))  # auto|confirm|reject
    updated_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))


class AnonConsentRequest(Base):
    """
    Запрос подтверждения для получения анонимного сообщения.
    """
    __tablename__ = "anon_consent_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dialog_id = Column(Integer, ForeignKey("anon_dialogs.id", ondelete="CASCADE"), index=True, nullable=False)
    recipient_id = Column(BigInteger, nullable=False, index=True)
    placeholder_message_id = Column(BigInteger, nullable=False)
    pending_message_id = Column(Integer, ForeignKey("anon_messages.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False, server_default=sa_text("'pending'"))  # pending|approved|rejected
    created_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))
    responded_at = Column(String, nullable=True)


class FireIncident(Base):
    """
    Заявка о сработавшей пожарной сигнализации в дорме.
    """
    __tablename__ = "fire_incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dorm_number = Column(Integer, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, nullable=False, server_default=sa_text("'pending'"))  # pending|approved|rejected
    created_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))
    processed_at = Column(String, nullable=True)
    processed_by = Column(BigInteger, nullable=True)
    comment = Column(Text, nullable=True)


class FireCounter(Base):
    """
    Счётчик подтверждённых пожарок по каждому дорму.
    """
    __tablename__ = "fire_counters"

    dorm_number = Column(Integer, primary_key=True)
    total = Column(Integer, nullable=False, server_default=sa_text("0"))
    updated_at = Column(String, nullable=False, server_default=sa_text("(CURRENT_TIMESTAMP)"))
