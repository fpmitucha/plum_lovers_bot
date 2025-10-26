from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional, Iterable, Tuple

from sqlalchemy import select, update, delete, and_, func, text, inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import (
    Roster,
    Application,
    Invite,
    Blacklist,
    Admin,
    Profile,
)

# ---------- helpers ----------

def now_dt() -> datetime:
    return datetime.now(timezone.utc)

def now_str() -> str:
    return now_dt().strftime("%Y-%m-%d %H:%M:%S")


def _extract_invite_code(invite_url: str) -> Optional[str]:
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
    def __init__(self, session: AsyncSession):
        self.session = session

    # ===== служебные таблицы (карма события, индекс сообщений) =====

    async def ensure_aux_tables(self) -> None:
        # события кармы (+/-), чтобы считать статистику
        await self.session.execute(text("""
        CREATE TABLE IF NOT EXISTS karma_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER NOT NULL,   -- кому начислили/списали
            actor_id  INTEGER,            -- кто поставил (+/реакцию), если известно
            chat_id   INTEGER,
            message_id INTEGER,
            delta     INTEGER NOT NULL,   -- +N или -N
            reason    TEXT,
            created_at TEXT NOT NULL
        )
        """))
        # индекс собственных сообщений пользователя в чатах — нужен для реакций
        await self.session.execute(text("""
        CREATE TABLE IF NOT EXISTS messages_index (
            chat_id    INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id    INTEGER NOT NULL,
            pos_count  INTEGER NOT NULL DEFAULT 0,  -- суммарные положительные реакции
            neg_count  INTEGER NOT NULL DEFAULT 0,  -- суммарные отрицательные реакции
            PRIMARY KEY (chat_id, message_id)
        )
        """))
        await self.session.commit()

    # ===== колонки (БД vs ORM-мэппинг) =====

    async def _profile_cols_db(self) -> set[str]:
        table = Profile.__tablename__
        res = await self.session.execute(text(f"PRAGMA table_info({table})"))
        return {row[1] for row in res.all()}  # name

    def _profile_cols_mapped(self) -> set[str]:
        mapper = sa_inspect(Profile)
        return {c.key for c in mapper.column_attrs}

    async def _has_profile_col_db(self, name: str) -> bool:
        return name in (await self._profile_cols_db())

    # ---- KARMA + рейтинг -------------------------------------------------

    async def _ensure_karma_column(self) -> None:
        table = Profile.__tablename__
        res = await self.session.execute(text(f"PRAGMA table_info({table})"))
        cols = [row[1] for row in res.all()]
        if "karma" not in cols:
            await self.session.execute(text(f"ALTER TABLE {table} ADD COLUMN karma INTEGER"))
            await self.session.commit()

    async def get_karma(self, user_id: int) -> int:
        await self._ensure_karma_column()
        table = Profile.__tablename__
        res = await self.session.execute(
            text(f"SELECT COALESCE(karma, 10) FROM {table} WHERE user_id = :uid"),
            {"uid": int(user_id)},
        )
        val = res.scalar()
        return int(val) if val is not None else 10

    async def add_karma(self, user_id: int, delta: int) -> int:
        await self._ensure_karma_column()
        if not await self.profile_exists(user_id):
            await self.ensure_profile(user_id=user_id, username=None, slug=None)
        table = Profile.__tablename__
        await self.session.execute(
            text(f"""
                UPDATE {table}
                   SET karma = COALESCE(karma, 10) + :d
                 WHERE user_id = :uid
            """),
            {"d": int(delta), "uid": int(user_id)},
        )
        await self.session.commit()
        return await self.get_karma(user_id)

    async def set_karma(self, user_id: int, value: int) -> int:
        await self._ensure_karma_column()
        if not await self.profile_exists(user_id):
            await self.ensure_profile(user_id=user_id, username=None, slug=None)
        table = Profile.__tablename__
        await self.session.execute(
            text(f"UPDATE {table} SET karma = :v WHERE user_id = :uid"),
            {"v": int(value), "uid": int(user_id)},
        )
        await self.session.commit()
        return await self.get_karma(user_id)

    async def get_top_by_karma(self, *, limit: int = 10) -> list[tuple[int, str | None, int]]:
        await self._ensure_karma_column()
        table = Profile.__tablename__
        has_joined = await self._has_profile_col_db("joined_at")

        order_parts = ["k DESC"]
        if has_joined:
            order_parts += [
                "CASE WHEN joined_at IS NULL THEN 1 ELSE 0 END ASC",
                "joined_at ASC",
            ]
        order_parts += ["user_id ASC"]

        sql = f"""
            SELECT user_id,
                   username,
                   COALESCE(karma, 10) AS k
              FROM {table}
          ORDER BY {", ".join(order_parts)}
             LIMIT :lim
        """
        res = await self.session.execute(text(sql), {"lim": int(limit)})
        rows = res.fetchall()
        return [(int(r[0]), r[1], int(r[2])) for r in rows]

    async def get_rank(self, user_id: int) -> int | None:
        await self._ensure_karma_column()
        if not await self.profile_exists(user_id):
            return None

        table = Profile.__tablename__
        has_joined = await self._has_profile_col_db("joined_at")

        order_parts = ["COALESCE(karma, 10) DESC"]
        if has_joined:
            order_parts += [
                "CASE WHEN joined_at IS NULL THEN 1 ELSE 0 END ASC",
                "joined_at ASC",
            ]
        order_parts += ["user_id ASC"]

        sql = f"""
            SELECT pos FROM (
                SELECT user_id,
                       ROW_NUMBER() OVER (ORDER BY {", ".join(order_parts)}) AS pos
                  FROM {table}
            ) t
            WHERE t.user_id = :uid
        """
        res = await self.session.execute(text(sql), {"uid": int(user_id)})
        pos = res.scalar()
        return int(pos) if pos is not None else None

    # ---- KARMA EVENTS (лог + статистика) -------------------------------

    async def log_karma_event(
        self,
        user_id: int,
        delta: int,
        *,
        chat_id: Optional[int] = None,
        message_id: Optional[int] = None,
        reason: Optional[str] = None,
        actor_id: Optional[int] = None,
    ) -> None:
        await self.session.execute(
            text("""
            INSERT INTO karma_events (user_id, actor_id, chat_id, message_id, delta, reason, created_at)
            VALUES (:uid, :actor, :chat, :mid, :delta, :reason, :ts)
            """),
            {
                "uid": int(user_id),
                "actor": int(actor_id) if actor_id else None,
                "chat": int(chat_id) if chat_id else None,
                "mid": int(message_id) if message_id else None,
                "delta": int(delta),
                "reason": (reason or "")[:200],
                "ts": now_str(),
            },
        )
        await self.session.commit()

    async def karma_stats(self, user_id: int, *, since: Optional[datetime] = None, until: Optional[datetime] = None) -> tuple[int, int]:
        clauses = ["user_id = :uid"]
        params = {"uid": int(user_id)}
        if since is not None:
            clauses.append("created_at >= :since")
            params["since"] = since.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if until is not None:
            clauses.append("created_at < :until")
            params["until"] = until.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        where = " AND ".join(clauses)
        res = await self.session.execute(
            text(f"""
              SELECT
                COALESCE(SUM(CASE WHEN delta > 0 THEN delta ELSE 0 END), 0) AS plus,
                COALESCE(SUM(CASE WHEN delta < 0 THEN -delta ELSE 0 END), 0) AS minus
              FROM karma_events
              WHERE {where}
            """),
            params,
        )
        row = res.first()
        return int(row[0] or 0), int(row[1] or 0)

    async def karma_stats_all_users(self, *, since: datetime, until: datetime) -> dict[int, tuple[int, int]]:
        res = await self.session.execute(
            text("""
                SELECT user_id,
                       COALESCE(SUM(CASE WHEN delta > 0 THEN delta ELSE 0 END), 0) AS plus,
                       COALESCE(SUM(CASE WHEN delta < 0 THEN -delta ELSE 0 END), 0) AS minus
                  FROM karma_events
                 WHERE created_at >= :since AND created_at < :until
              GROUP BY user_id
            """),
            {
                "since": since.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "until": until.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        return {int(r[0]): (int(r[1] or 0), int(r[2] or 0)) for r in res.fetchall()}

    # ---- Индекс сообщений для реакций -----------------------------------

    async def ensure_message_index(self, *, chat_id: int, message_id: int, user_id: int) -> None:
        await self.session.execute(
            text("""
            INSERT OR IGNORE INTO messages_index (chat_id, message_id, user_id)
            VALUES (:chat, :mid, :uid)
            """),
            {"chat": int(chat_id), "mid": int(message_id), "uid": int(user_id)},
        )
        await self.session.commit()

    async def get_message_owner_and_counters(self, *, chat_id: int, message_id: int) -> tuple[int | None, int, int]:
        res = await self.session.execute(
            text("""
            SELECT user_id, pos_count, neg_count
              FROM messages_index
             WHERE chat_id = :chat AND message_id = :mid
            """),
            {"chat": int(chat_id), "mid": int(message_id)},
        )
        row = res.first()
        if not row:
            return None, 0, 0
        return int(row[0]), int(row[1] or 0), int(row[2] or 0)

    async def apply_reaction_tally(
        self, *, chat_id: int, message_id: int, new_pos: int, new_neg: int
    ) -> None:
        owner_id, old_pos, old_neg = await self.get_message_owner_and_counters(chat_id=chat_id, message_id=message_id)
        if owner_id is None:
            return
        dp = max(0, int(new_pos) - int(old_pos))
        dn = max(0, int(new_neg) - int(old_neg))

        if dp == 0 and dn == 0:
            return

        await self.session.execute(
            text("""
            UPDATE messages_index
               SET pos_count = :p, neg_count = :n
             WHERE chat_id = :chat AND message_id = :mid
            """),
            {"p": int(new_pos), "n": int(new_neg), "chat": int(chat_id), "mid": int(message_id)},
        )
        await self.session.commit()

        if dp:
            await self.add_karma(owner_id, dp)
            await self.log_karma_event(owner_id, dp, chat_id=chat_id, message_id=message_id, reason="reactions:+")
        if dn:
            await self.add_karma(owner_id, -dn)
            await self.log_karma_event(owner_id, -dn, chat_id=chat_id, message_id=message_id, reason="reactions:-")

    async def apply_reply_karma(
        self, *,
        target_user_id: int,
        delta: int,
        chat_id: int,
        message_id: int,
        reason: str,
        actor_id: int | None,
    ) -> None:
        await self.add_karma(target_user_id, delta)
        await self.log_karma_event(
            target_user_id, delta, chat_id=chat_id, message_id=message_id, reason=reason, actor_id=actor_id
        )

    # -------- ROSTER --------

    async def get_profile_by_slug(self, slug: str) -> Profile | None:
        if "slug" not in self._profile_cols_mapped():
            return None
        res = await self.session.execute(select(Profile).where(Profile.slug == slug))
        return res.scalar_one_or_none()

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

    async def roster_add(self, slug: str) -> Roster:
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

    async def roster_search(self, query: str, *, page: int, page_size: int) -> tuple[int, list[Roster]]:
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

    async def applications_count(self, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(Application)
        if status and status != "all":
            stmt = stmt.where(Application.status == status)
        res = await self.session.execute(stmt)
        return int(res.scalar() or 0)

    async def applications_page(self, *, page: int, page_size: int, status: str | None = None) -> list[Application]:
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

    async def invites_count(self, *, active_only: bool = False) -> int:
        stmt = select(func.count()).select_from(Invite)
        if active_only:
            stmt = stmt.where(Invite.expires_at > now_str())
        res = await self.session.execute(stmt)
        return int(res.scalar() or 0)

    async def invites_page(self, *, page: int, page_size: int, active_only: bool = False) -> list[Invite]:
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

    # -------- PROFILES --------

    async def ensure_profile(self, *, user_id: int, username: str | None, slug: str | None) -> Profile:
        mapped = self._profile_cols_mapped()

        p = await self.get_profile(user_id)
        if p:
            upd: dict = {}
            if "username" in mapped and username is not None and getattr(p, "username", None) != username:
                upd["username"] = username
            if "slug" in mapped and slug is not None and getattr(p, "slug", None) != slug:
                upd["slug"] = slug
            if upd:
                await self.session.execute(
                    update(Profile).where(Profile.user_id == user_id).values(**upd)
                )
                await self.session.commit()
            return p

        payload: dict = {"user_id": user_id}
        if "username" in mapped:
            payload["username"] = username
        if "slug" in mapped and slug is not None:
            payload["slug"] = slug

        p = Profile(**payload)
        self.session.add(p)
        await self.session.flush()

        if await self._has_profile_col_db("joined_at") and "joined_at" not in mapped:
            table = Profile.__tablename__
            await self.session.execute(
                text(f"UPDATE {table} SET joined_at = :ts WHERE user_id = :uid AND joined_at IS NULL"),
                {"ts": now_str(), "uid": int(user_id)},
            )

        if await self._has_profile_col_db("karma") and "karma" not in mapped:
            table = Profile.__tablename__
            await self.session.execute(
                text(f"UPDATE {table} SET karma = 10 WHERE user_id = :uid AND karma IS NULL"),
                {"uid": int(user_id)},
            )

        await self.session.commit()
        return p

    async def get_profile(self, user_id: int) -> Profile | None:
        res = await self.session.execute(select(Profile).where(Profile.user_id == user_id))
        return res.scalar_one_or_none()

    async def profile_exists(self, user_id: int) -> bool:
        res = await self.session.execute(select(Profile.user_id).where(Profile.user_id == user_id))
        return res.scalar_one_or_none() is not None

    async def update_profile_username(self, user_id: int, username: str | None) -> None:
        mapped = self._profile_cols_mapped()
        values: dict = {}
        if "username" in mapped:
            values["username"] = username
        if values:
            await self.session.execute(
                update(Profile).where(Profile.user_id == user_id).values(**values)
            )
            await self.session.commit()
        if await self._has_profile_col_db("joined_at") and "joined_at" not in mapped:
            table = Profile.__tablename__
            await self.session.execute(
                text(f"UPDATE {table} SET joined_at = :ts WHERE user_id = :uid AND joined_at IS NULL"),
                {"ts": now_str(), "uid": int(user_id)},
            )
            await self.session.commit()

    async def get_top_profiles(self, *, limit: int = 10) -> list[Profile]:
        ids = [uid for uid, _u, _k in await self.get_top_by_karma(limit=limit)]
        if not ids:
            return []
        res = await self.session.execute(select(Profile).where(Profile.user_id.in_(ids)))
        by_id = {p.user_id: p for p in res.scalars()}
        return [by_id[i] for i in ids if i in by_id]

    async def has_registered(self, user_id: int) -> bool:
        if await self.profile_exists(user_id):
            return True
        app = await self.get_last_application_for_user(user_id)
        return bool(app and (app.status or "").lower() == "done")

    async def _render_profile_text(repo: "Repo", user) -> str:
        tag = f"@{getattr(user, 'username', None)}" if getattr(user, "username", None) else "—"
        karma = await repo.get_karma(user.id)
        rank = await repo.get_rank(user.id)
        rank_str = str(rank) if rank is not None else "—"
        return (
            "👤 <b>Личный кабинет</b>\n\n"
            f"<b>ID:</b> <code>{user.id}</code>\n"
            f"<b>Тег:</b> {tag}\n"
            f"<b>Карма:</b> <b>{karma}</b>\n"
            f"<b>Место в топе:</b> <b>{rank_str}</b>"
        )

    # -------- ADMINS --------

    async def list_admins(self) -> list[Admin]:
        res = await self.session.execute(select(Admin).order_by(Admin.user_id.asc()))
        return list(res.scalars().all())

    async def add_admin(self, user_id: int) -> None:
        res = await self.session.execute(select(Admin).where(Admin.user_id == user_id))
        if res.scalar_one_or_none():
            return
        self.session.add(Admin(user_id=user_id, created_at=now_str()))
        await self.session.commit()

    async def remove_admin(self, user_id: int) -> None:
        await self.session.execute(delete(Admin).where(Admin.user_id == user_id))
        await self.session.commit()
