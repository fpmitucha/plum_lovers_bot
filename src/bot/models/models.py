"""
ORM-модели SQLAlchemy для бота.

Таблицы:
- roster       — список «участников» (используется на чтение).
- applications — заявки пользователей на вступление.
- invites      — выданные персональные инвайты.
- blacklist    — заблокированные пользователи.
- admins       — динамические администраторы (кроме главного и тех, что заданы в settings).

Примечание (SQLite):
created_at/updated_at хранятся как TEXT в UTC-формате 'YYYY-MM-DD HH:MM:SS'.
"""

from sqlalchemy import BigInteger, Integer, String, Text, text, UniqueConstraint, Column
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Roster(Base):
    """
    Строка в «реестре участников».

    Атрибуты:
        id         — PK.
        slug       — нормализованный slug (уникален).
        created_at — дата/время создания (UTC, TEXT).
        updated_at — дата/время последнего изменения (UTC, TEXT).
    """
    __tablename__ = "roster"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String, unique=True, index=True, nullable=False)

    created_at = Column(String, nullable=False, server_default=text("(CURRENT_TIMESTAMP)"))
    updated_at = Column(String, nullable=False, server_default=text("(CURRENT_TIMESTAMP)"))


class Application(Base):
    """
    Заявка на вступление.

    Атрибуты:
        id, user_id, username, slug,
        status: 'pending' | 'approved' | 'rejected' | 'done',
        reason  — опциональная причина,
        created_at, updated_at.
    """
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(BigInteger, index=True, nullable=False)
    username = Column(String, nullable=True)
    slug = Column(String, nullable=False)

    status = Column(String, nullable=False, server_default=text("'pending'"))
    reason = Column(Text, nullable=True)

    created_at = Column(String, nullable=False, server_default=text("(CURRENT_TIMESTAMP)"))
    updated_at = Column(String, nullable=False, server_default=text("(CURRENT_TIMESTAMP)"))


class Invite(Base):
    """
    Выданный персональный инвайт в целевой чат.

    Атрибуты:
        id, user_id, chat_id, invite_link (уникален),
        expires_at, created_at, updated_at.
    """
    __tablename__ = "invites"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(BigInteger, index=True, nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    invite_link = Column(String, nullable=False, unique=True)
    expires_at = Column(String, nullable=False)

    created_at = Column(String, nullable=False, server_default=text("(CURRENT_TIMESTAMP)"))
    updated_at = Column(String, nullable=False, server_default=text("(CURRENT_TIMESTAMP)"))


class Blacklist(Base):
    """
    Чёрный список пользователей.

    Атрибуты:
        id, user_id (уникален), reason, created_at.
    """
    __tablename__ = "blacklist"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(BigInteger, index=True, nullable=False, unique=True)
    reason = Column(Text, nullable=True)

    created_at = Column(String, nullable=False, server_default=text("(CURRENT_TIMESTAMP)"))

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_blacklist_user"),
    )


class Admin(Base):
    """
    Динамические администраторы (настраиваются в рантайме).
    Главный админ и админы из settings.ADMIN_USER_IDS сюда не обязаны входить.

    Атрибуты:
        id, user_id (уникален), created_at.
    """
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, index=True, nullable=False)

    created_at = Column(String, nullable=False, server_default=text("(CURRENT_TIMESTAMP)"))
