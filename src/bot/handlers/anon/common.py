from __future__ import annotations

import contextlib
import html

import logging

from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from bot.config import settings
from bot.handlers.admin import _get_all_admin_ids
from bot.utils.admins import admin_notify_chat_id, main_admin_id_from_settings
from bot.services.anon import (
    FloodControl,
    RateLimitExceeded,
    generate_dialog_code,
    resolve_user_identifier,
    snapshot,
    validate_text,
)
from bot.services.i18n import get_lang
from bot.utils.repo import Repo

from .callbacks import DialogCB

_flood = FloodControl()
_log = logging.getLogger("innopls-bot")


def lang(user_id: int) -> str:
    return (get_lang(user_id) or "ru").lower()


def tr(lang_code: str, ru: str, en: str) -> str:
    return en if lang_code == "en" else ru


def main_admin_id() -> int | None:
    return main_admin_id_from_settings()


def dialog_header(dialog_code: str, text: str | None, lang_code: str) -> str:
    body = html.escape((text or "").strip()) or "—"
    return tr(
        lang_code,
        f"💌 <b>Анонимный чат #{dialog_code}</b>\n\n{body}\n\nНажми «Ответить», чтобы ответить.",
        f"💌 <b>Anonymous chat #{dialog_code}</b>\n\n{body}\n\nTap “Reply” to respond.",
    )


def admin_inbox_text(lang_code: str, dialog_code: str, text: str, author_id: int) -> str:
    body = html.escape(text.strip()) or "—"
    return tr(
        lang_code,
        f"🆘 <b>Анонимное обращение #{dialog_code}</b>\n\n{body}\n\n<b>Автор:</b> <code>{author_id}</code>\nОтветить может только главный админ.",
        f"🆘 <b>Anonymous request #{dialog_code}</b>\n\n{body}\n\n<b>Author ID:</b> <code>{author_id}</code>\nOnly the main admin may reply.",
    )


def public_request_text(lang_code: str, request_id: int, text: str, author_id: int) -> str:
    body = html.escape(text.strip()) or "—"
    return tr(
        lang_code,
        f"📣 <b>Запрос в общий чат #{request_id}</b>\n\n{body}\n\n<b>Автор:</b> <code>{author_id}</code>\nОдобри публикацию или отклони.",
        f"📣 <b>Anonymous post request #{request_id}</b>\n\n{body}\n\n<b>Author ID:</b> <code>{author_id}</code>\nApprove to publish or reject.",
    )


def public_preview(text: str, lang_code: str) -> str:
    body = html.escape(text.strip()) or "—"
    return tr(
        lang_code,
        f"💌 <b>Анонимное сообщение</b>\n\n{body}",
        f"💌 <b>Anonymous message</b>\n\n{body}",
    )


async def ensure_rate(user_id: int, lang_code: str) -> None:
    try:
        _flood.check(user_id)
    except RateLimitExceeded as exc:
        raise ValueError(tr(lang_code, f"⛔️ Слишком часто. Попробуй через {exc.seconds} сек.", f"⛔️ Too fast. Try again in {exc.seconds} sec.")) from exc


async def admin_targets(session_maker: async_sessionmaker[AsyncSession]) -> list[int]:
    async with session_maker() as session:
        repo = Repo(session)
        ids = await _get_all_admin_ids(repo)
    targets = list(ids)
    main_admin = main_admin_id()
    if main_admin and main_admin not in targets:
        targets.append(main_admin)
    notify_chat = admin_notify_chat_id()
    if notify_chat:
        targets.append(notify_chat)
    return targets


async def active_dialog(repo: Repo, user_id: int, *, kind: str | None = None):
    dlg = await repo.get_active_anon_dialog_for_user(user_id, kind=kind)
    return snapshot(dlg) if dlg else None


async def new_dialog(repo: Repo, *, initiator_id: int, target_id: int, kind: str) -> str:
    code = await generate_dialog_code(repo)
    dialog = await repo.create_anon_dialog(
        dialog_code=code,
        initiator_id=initiator_id,
        target_id=target_id,
        kind=kind,
    )
    return dialog.dialog_code


async def resolve_target(value: str | None) -> int | None:
    if not value:
        return None
    return await resolve_user_identifier(value)


def validation_error(text: str, lang_code: str) -> str | None:
    return validate_text(text, lang_code)


async def notify_dialog_closed(bot, dialog, closed_by: int) -> None:
    other = dialog.target_id if closed_by == dialog.initiator_id else dialog.initiator_id
    text = tr(lang(other), f"Диалог #{dialog.dialog_code} завершён.", f"Dialog #{dialog.dialog_code} has been closed.")
    with contextlib.suppress(Exception):
        await bot.send_message(other, text)


def reply_keyboard(dialog_code: str, lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text=tr(lang_code, "✍️ Ответить", "✍️ Reply"),
        callback_data=DialogCB(action="reply", code=dialog_code).pack(),
    )
    kb.button(
        text=tr(lang_code, "🚪 Завершить", "🚪 Close"),
        callback_data=DialogCB(action="close", code=dialog_code).pack(),
    )
    kb.adjust(1)
    return kb.as_markup()


async def send_dialog_message(bot, dialog, recipient_id: int, text: str, lang_code: str) -> bool:
    try:
        await bot.send_message(
            recipient_id,
            dialog_header(dialog.dialog_code, text, lang_code),
            parse_mode=ParseMode.HTML,
            reply_markup=reply_keyboard(dialog.dialog_code, lang_code),
        )
        return True
    except Exception as exc:
        _log.warning("Не удалось отправить анонимное сообщение %s получателю %s: %s", dialog.dialog_code, recipient_id, exc)
        return False
