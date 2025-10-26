"""
Отслеживаем вступление в целевой чат.

Логика:
- Если вступили по нашей персональной ссылке:
    - Проверяем, что зашёл владелец ссылки.
    - При корректном входе: добавляем slug в roster, удаляем запись инвайта, пытаемся отозвать ссылку.
    - При некорректном: в чёрный список и вошедшего, и владельца ссылки; уведомляем админов; чистим инвайт.
- Если Telegram НЕ прислал invite_link (например, добавили вручную / сглючил апдейт):
    - Пытаемся найти последнюю заявку этого пользователя и добавить её slug в roster.
"""

from __future__ import annotations

import html
import logging

from aiogram import Router
from aiogram.types import ChatMemberUpdated, ChatInviteLink
from aiogram.enums import ChatMemberStatus
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from bot.config import settings
from bot.utils.repo import Repo

router = Router(name="chat_member")


def _is_join(event: ChatMemberUpdated) -> bool:
    """
    Было ли именно вступление (а не изменение роли и т.п.).
    """
    try:
        old_status = event.old_chat_member.status
        new_status = event.new_chat_member.status
        return (
                old_status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}
                and new_status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
        )
    except Exception:
        return False


@router.chat_member()
async def on_chat_member(event: ChatMemberUpdated, session_maker: async_sessionmaker[AsyncSession]) -> None:
    """
    Обработать факт вступления в целевой чат: синхронизировать roster и инвайты.
    """
    if event.chat.id != settings.TARGET_CHAT_ID:
        return
    if not _is_join(event):
        return

    invite: ChatInviteLink | None = getattr(event, "invite_link", None)
    invite_link_text = getattr(invite, "invite_link", None)
    joined_user_id = event.new_chat_member.user.id

    async with session_maker() as session:
        repo = Repo(session)

        # --- 1) Попробуем сопоставить нашу запись инвайта по ссылке (если пришла)
        inv = None
        if invite_link_text:
            try:
                inv = await repo.find_invite_for_link(invite_link_text)
            except Exception as e:
                logging.getLogger("innopls-bot").warning("find_invite_for_link failed: %s", e)

        # --- 2) Если инвайт нашли
        if inv:
            # 2.1) Чужой использовал личную ссылку — баним обоих, чистим инвайт, пытаемся отозвать
            if inv.user_id != joined_user_id:
                try:
                    await repo.blacklist_add(joined_user_id, reason="Вступил по чужой персональной ссылке")
                    await repo.blacklist_add(inv.user_id, reason="Его персональная ссылка использована чужим аккаунтом")
                except Exception as e:
                    logging.getLogger("innopls-bot").warning("blacklist_add failed: %s", e)

                warn = (
                    "🚫 <b>Некорректное вступление по персональной ссылке</b>\n\n"
                    f"<b>Ссылка принадлежала</b>: <code>{inv.user_id}</code>\n"
                    f"<b>Вступил аккаунт</b>: <code>{joined_user_id}</code>\n"
                    f"<b>Ссылка</b>: <code>{html.escape(inv.invite_link)}</code>"
                )
                for admin_id in settings.ADMIN_USER_IDS:
                    try:
                        await event.bot.send_message(admin_id, warn, parse_mode="HTML")
                    except Exception:
                        logging.getLogger("innopls-bot").warning("Не удалось уведомить админа %s", admin_id)

                try:
                    if invite:
                        await event.bot.revoke_chat_invite_link(event.chat.id, invite.invite_link)
                except Exception:
                    pass

                try:
                    await repo.delete_invite(inv.id)
                except Exception:
                    pass
                return

            # 2.2) Корректный вход владельца ссылки — пополняем roster
            app = await repo.get_last_application_for_user(inv.user_id)
            if app:
                try:
                    await repo.add_to_roster(app.slug)  # идемпотентно
                except Exception as e:
                    logging.getLogger("innopls-bot").warning("add_to_roster failed: %s", e)

            try:
                if invite:
                    await event.bot.revoke_chat_invite_link(event.chat.id, invite.invite_link)
            except Exception:
                pass

            try:
                await repo.delete_invite(inv.id)
            except Exception:
                pass
            return

        # --- 3) Фолбэк: инвайта не прислали / не нашли (добавили руками, старый инвайт и т.п.)
        try:
            app = await repo.get_last_application_for_user(joined_user_id)
            if app:
                await repo.add_to_roster(app.slug)  # идемпотентно
                try:
                    await repo.ensure_profile(
                        user_id=inv.user_id,
                        username=event.new_chat_member.user.username,
                        slug=app.slug if app else None,
                    )
                except Exception as e:
                    logging.getLogger("innopls-bot").warning("Не удалось ensure_profile: %s", e)

        except Exception as e:
            logging.getLogger("innopls-bot").warning("fallback add_to_roster failed: %s", e)
