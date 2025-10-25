"""
Слой доступа к данным (репозиторий) для работы с SQLite через SQLAlchemy.

Поддерживает:
- Реестр (roster): поиск, пагинация, добавление/удаление/правка.
- Заявки (applications): создание, чтение, смена статуса, пагинация/фильтры.
- Инвайты (invites): создание, поиск, пагинация, удаление.
- Чёрный список (blacklist): проверка, добавление, удаление, пагинация.
- Админы (admins): список/добавление/удаление.

Все временные метки TEXT — в UTC, формат 'YYYY-MM-DD HH:MM:SS'.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Iterable, Tuple

from sqlalchemy import select, update, delete, and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import (
    Roster,
    Application,
    Invite,
    Blacklist,
    Admin,
)


# ---------- helpers ----------

def now_str() -> str:
    """Текущая дата/время в UTC ('YYYY-MM-DD HH:MM:SS')."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _extract_invite_code(invite_url: str) -> Optional[str]:
    """
    Выделить токен инвайта из ссылки Telegram.
    Поддерживаемые варианты:
      - https://t.me/+ABCdef123
      - https://t.me/joinchat/ABCdef123
      - t.me/+ABCdef123
      - t.me/joinchat/ABCdef123
    """
    if not invite_url:
        return None

    url = invite_url.strip()
    if "://" in url:
        url = url.split("://", 1)[1]
    if url.startswith("t.me/"):
        url = url[len("t.me/"):]

    parts = url.split("/")
    tail = parts[-1] if parts else url

    if tail.startswith("+"):
        tail = tail[1:]

    for sep in ("?", "#"):
        if sep in tail:
            tail = tail.split(sep, 1)[0]

    return tail or None


# ---------- repository ----------

class Repo:
    """Репозиторий, инкапсулирующий операции с БД."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # -------- ROSTER --------

    async def roster_contains(self, slug: str) -> bool:
        res = await self.session.execute(select(Roster.id).where(Roster.slug == slug))
        return res.scalar_one_or_none() is not None

    async def add_to_roster(self, slug: str) -> Roster:
        if await self.roster_contains(slug):
            res = await self.session.execute(select(Roster).where(Roster.slug == slug))
            return res.scalar_one()
        rec = Roster(slug=slug)
        self.session.add(rec)
        await self.session.flush()
        await self.session.commit()
        return rec

    # — методы, которые использует админка —
    async def roster_add(self, slug: str) -> Roster:
        """Идемпотентное добавление."""
        return await self.add_to_roster(slug)

    async def roster_get(self, roster_id: int) -> Roster | None:
        res = await self.session.execute(select(Roster).where(Roster.id == roster_id))
        return res.scalar_one_or_none()

    async def roster_update_slug(self, roster_id: int, new_slug: str) -> None:
        await self.session.execute(
            update(Roster).where(Roster.id == roster_id).values(slug=new_slug)
        )
        await self.session.commit()

    async def roster_delete(self, roster_id: int) -> None:
        await self.session.execute(delete(Roster).where(Roster.id == roster_id))
        await self.session.commit()

    async def roster_count(self) -> int:
        res = await self.session.execute(select(func.count()).select_from(Roster))
        return int(res.scalar() or 0)

    async def roster_page(self, *, page: int, page_size: int) -> list[Roster]:
        offset = page * page_size
        res = await self.session.execute(
            select(Roster).order_by(Roster.slug.asc(), Roster.id.asc()).offset(offset).limit(page_size)
        )
        return list(res.scalars().all())

    async def roster_search(
        self, query: str, *, page: int, page_size: int
    ) -> tuple[int, list[Roster]]:
        words = [w for w in query.lower().split() if w]
        cond = True
        for w in words:
            cond = and_(cond, Roster.slug.ilike(f"%{w}%"))

        cnt_res = await self.session.execute(select(func.count()).select_from(Roster).where(cond))
        total = int(cnt_res.scalar() or 0)

        offset = page * page_size
        rows_res = await self.session.execute(
            select(Roster).where(cond).order_by(Roster.slug.asc(), Roster.id.asc()).offset(offset).limit(page_size)
        )
        return total, list(rows_res.scalars().all())

    # -------- APPLICATIONS --------

    async def add_application(
        self, *, user_id: int, username: str | None, slug: str, reason: str | None = None
    ) -> Application:
        app = Application(
            user_id=user_id,
            username=username,
            slug=slug,
            status="pending",
            reason=reason,
            created_at=now_str(),
            updated_at=now_str(),
        )
        self.session.add(app)
        await self.session.flush()
        await self.session.commit()
        return app

    async def get_application(self, app_id: int) -> Application | None:
        res = await self.session.execute(select(Application).where(Application.id == app_id))
        return res.scalar_one_or_none()

    async def get_last_application_for_user(self, user_id: int) -> Application | None:
        res = await self.session.execute(
            select(Application)
            .where(Application.user_id == user_id)
            .order_by(Application.created_at.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def has_active_application(self, user_id: int) -> bool:
        res = await self.session.execute(
            select(Application.id).where(
                and_(
                    Application.user_id == user_id,
                    Application.status.in_(("pending", "approved", "done")),
                )
            )
        )
        return res.scalar_one_or_none() is not None

    async def set_application_status(self, app_id: int, *, status: str, reason: str | None = None) -> None:
        await self.session.execute(
            update(Application)
            .where(Application.id == app_id)
            .values(status=status, reason=reason, updated_at=now_str())
        )
        await self.session.commit()

    # — список/пагинация для админки —
    async def applications_count(self, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(Application)
        if status and status != "all":
            stmt = stmt.where(Application.status == status)
        res = await self.session.execute(stmt)
        return int(res.scalar() or 0)

    async def applications_page(
        self, *, page: int, page_size: int, status: str | None = None
    ) -> list[Application]:
        offset = page * page_size
        stmt = select(Application)
        if status and status != "all":
            stmt = stmt.where(Application.status == status)
        stmt = stmt.order_by(Application.created_at.desc(), Application.id.desc()).offset(offset).limit(page_size)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    # -------- INVITES --------

    async def add_invite(self, *, user_id: int, chat_id: int, invite_link: str, expires_at: str) -> Invite:
        inv = Invite(
            user_id=user_id,
            chat_id=chat_id,
            invite_link=invite_link,
            expires_at=expires_at,
            created_at=now_str(),
            updated_at=now_str(),
        )
        self.session.add(inv)
        await self.session.flush()
        await self.session.commit()
        return inv

    async def find_invite_for_link(self, invite_url: str) -> Invite | None:
        if not invite_url:
            return None

        res = await self.session.execute(select(Invite).where(Invite.invite_link == invite_url))
        inv = res.scalar_one_or_none()
        if inv:
            return inv

        code = _extract_invite_code(invite_url)
        if not code:
            return None

        res = await self.session.execute(
            select(Invite).where(Invite.invite_link.like(f"%{code}"))
        )
        return res.scalar_one_or_none()

    async def get_active_invite(self, user_id: int) -> Invite | None:
        now = now_str()
        res = await self.session.execute(
            select(Invite)
            .where(and_(Invite.user_id == user_id, Invite.expires_at > now))
            .order_by(Invite.created_at.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def has_active_invite(self, user_id: int) -> bool:
        return (await self.get_active_invite(user_id)) is not None

    async def delete_invite(self, invite_id: int) -> None:
        await self.session.execute(delete(Invite).where(Invite.id == invite_id))
        await self.session.commit()

    # — список/пагинация для админки —
    async def invites_count(self, *, active_only: bool = False) -> int:
        stmt = select(func.count()).select_from(Invite)
        if active_only:
            stmt = stmt.where(Invite.expires_at > now_str())
        res = await self.session.execute(stmt)
        return int(res.scalar() or 0)

    async def invites_page(
        self, *, page: int, page_size: int, active_only: bool = False
    ) -> list[Invite]:
        offset = page * page_size
        stmt = select(Invite)
        if active_only:
            stmt = stmt.where(Invite.expires_at > now_str())
        stmt = stmt.order_by(Invite.created_at.desc(), Invite.id.desc()).offset(offset).limit(page_size)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    # -------- BLACKLIST --------

    async def blacklist_contains(self, user_id: int) -> bool:
        res = await self.session.execute(select(Blacklist.id).where(Blacklist.user_id == user_id))
        return res.scalar_one_or_none() is not None

    async def blacklist_add(self, user_id: int, reason: str | None = None) -> None:
        if await self.blacklist_contains(user_id):
            return
        bl = Blacklist(user_id=user_id, reason=reason)
        self.session.add(bl)
        await self.session.commit()

    async def blacklist_remove(self, user_id: int) -> None:
        await self.session.execute(delete(Blacklist).where(Blacklist.user_id == user_id))
        await self.session.commit()

    async def blacklist_update_reason(self, user_id: int, reason: str | None) -> None:
        await self.session.execute(
            update(Blacklist).where(Blacklist.user_id == user_id).values(reason=reason)
        )
        await self.session.commit()

    async def blacklist_count(self) -> int:
        res = await self.session.execute(select(func.count()).select_from(Blacklist))
        return int(res.scalar() or 0)

    async def blacklist_page(self, *, page: int, page_size: int) -> list[Blacklist]:
        offset = page * page_size
        res = await self.session.execute(
            select(Blacklist).order_by(Blacklist.created_at.desc(), Blacklist.id.desc()).offset(offset).limit(page_size)
        )
        return list(res.scalars().all())

    # -------- ADMINS --------

    async def list_admins(self) -> list[Admin]:
        res = await self.session.execute(select(Admin).order_by(Admin.user_id.asc()))
        return list(res.scalars().all())

    async def add_admin(self, user_id: int) -> None:
        if await self.session.execute(select(Admin).where(Admin.user_id == user_id)).then(lambda r: r.scalar_one_or_none()):
            return
        self.session.add(Admin(user_id=user_id, created_at=now_str()))
        await self.session.commit()

    async def remove_admin(self, user_id: int) -> None:
        await self.session.execute(delete(Admin).where(Admin.user_id == user_id))
        await self.session.commit()
