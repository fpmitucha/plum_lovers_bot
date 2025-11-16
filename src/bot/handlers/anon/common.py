from __future__ import annotations

import asyncio
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

from .callbacks import DialogCB, ConsentCB

_flood = FloodControl()
_log = logging.getLogger("innopls-bot")
_reply_timeouts: dict[tuple[int, int], asyncio.Task] = {}
REPLY_TIMEOUT_SECONDS = 15 * 60

PREF_LABELS = {
    "auto": ("Автоматически принимать чаты", "Auto-accept chats"),
    "confirm": ("Нужно подтверждение", "Require confirmation"),
    "reject": ("Отказ от анонимных чатов", "Reject anonymous chats"),
}


def lang(user_id: int) -> str:
    return (get_lang(user_id) or "ru").lower()


def tr(lang_code: str, ru: str, en: str) -> str:
    return en if lang_code == "en" else ru


def pref_label(mode: str, lang_code: str) -> str:
    ru, en = PREF_LABELS.get(mode, PREF_LABELS["auto"])
    return ru if lang_code != "en" else en


def main_admin_id() -> int | None:
    return main_admin_id_from_settings()


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


def consent_prompt_text(dialog_code: str, lang_code: str) -> str:
    return tr(
        lang_code,
        f"💌 <b>Анонимный чат #{dialog_code}</b>\n\nВам отправили сообщение. Принять чат?",
        f"💌 <b>Anonymous chat #{dialog_code}</b>\n\nYou have a pending message. Accept the chat?",
    )


def consent_declined_text(lang_code: str) -> str:
    return tr(
        lang_code,
        "⛔️ Чат отклонён.",
        "⛔️ Chat declined.",
    )


def receiver_blocked_text(lang_code: str) -> str:
    return tr(
        lang_code,
        "Пользователь отключил анонимные чаты. Вы тоже не можете отправлять сообщения при этом режиме.",
        "The user disabled anonymous chats. You cannot send anonymous messages while this mode is active.",
    )


def self_blocked_text(lang_code: str) -> str:
    return tr(
        lang_code,
        "Вы отключили анонимные чаты. Измените настройку, чтобы продолжить.",
        "You disabled anonymous chats. Change settings to continue.",
    )


def awaiting_consent_text(lang_code: str) -> str:
    return tr(
        lang_code,
        "Ждём подтверждения собеседника.",
        "Waiting for the recipient to confirm.",
    )


def unanswered_text(lang_code: str) -> str:
    return tr(
        lang_code,
        "Диалог закрыт: пользователь не ответил на ваше сообщение.",
        "Dialog closed: the user did not reply to your message.",
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


async def new_dialog(repo: Repo, *, initiator_id: int, target_id: int, kind: str, target_consent: str = "approved") -> str:
    code = await generate_dialog_code(repo)
    dialog = await repo.create_anon_dialog(
        dialog_code=code,
        initiator_id=initiator_id,
        target_id=target_id,
        kind=kind,
        target_consent=target_consent,
    )
    return dialog.dialog_code


async def resolve_target(repo: Repo, value: str | None) -> int | None:
    if not value:
        return None
    candidate = (value or "").strip()
    if not candidate:
        return None
    if candidate.startswith("@"):
        username = candidate.lstrip("@").lower()
        user_id = await repo.find_user_id_by_username(username)
        if not user_id:
            raise ValueError("user_not_found")
        return user_id
    try:
        return await resolve_user_identifier(candidate)
    except ValueError:
        username = candidate.lower()
        user_id = await repo.find_user_id_by_username(username)
        if not user_id:
            raise ValueError("user_not_found")
        return user_id


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


def consent_keyboard(request_id: int, lang_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text=tr(lang_code, "✅ Принять", "✅ Accept"),
        callback_data=ConsentCB(action="accept", request_id=request_id).pack(),
    )
    kb.button(
        text=tr(lang_code, "⛔️ Отклонить", "⛔️ Decline"),
        callback_data=ConsentCB(action="reject", request_id=request_id).pack(),
    )
    kb.adjust(2)
    return kb.as_markup()


def dialog_role(dialog, user_id: int, *, as_recipient: bool = False) -> str:
    if as_recipient:
        if user_id == dialog.target_id:
            return "target"
        if user_id == dialog.initiator_id:
            return "initiator" if dialog.target_id != user_id else "target"
    return "initiator" if user_id == dialog.initiator_id else "target"


def should_show_header(dialog, recipient_id: int) -> bool:
    role = dialog_role(dialog, recipient_id, as_recipient=True)
    if role == "initiator":
        return not bool(dialog.initiator_header_sent)
    return not bool(dialog.target_header_sent)


def format_dialog_text(dialog, text: str, lang_code: str, *, with_header: bool) -> str:
    body = html.escape((text or "").strip()) or "—"
    if with_header:
        return tr(
            lang_code,
            f"💌 <b>Анонимный чат #{dialog.dialog_code}</b>\n\n{body}\n\nНажми «Ответить», чтобы ответить.",
            f"💌 <b>Anonymous chat #{dialog.dialog_code}</b>\n\n{body}\n\nTap “Reply” to respond.",
        )
    return body


async def send_dialog_message(bot, dialog, recipient_id: int, text: str, lang_code: str, *, with_header: bool) -> bool:
    payload = format_dialog_text(dialog, text, lang_code, with_header=with_header)
    try:
        await bot.send_message(
            recipient_id,
            payload,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_keyboard(dialog.dialog_code, lang_code),
        )
        return True
    except Exception as exc:
        _log.warning("Не удалось отправить анонимное сообщение %s получателю %s: %s", dialog.dialog_code, recipient_id, exc)
        return False


def schedule_reply_timeout(dialog, *, waiting_for: int, message_id: int, last_sender_id: int, bot, session_maker) -> None:
    if dialog.kind != "user":
        return
    key = (dialog.id, waiting_for)
    existing = _reply_timeouts.pop(key, None)
    if existing:
        existing.cancel()

    async def _worker():
        try:
            await asyncio.sleep(REPLY_TIMEOUT_SECONDS)
            async with session_maker() as session:
                repo = Repo(session)
                if await repo.has_reply_since(dialog.id, message_id, waiting_for):
                    return
                fresh = await repo.get_anon_dialog(dialog.id)
                if not fresh or fresh.status != "active":
                    return
                await repo.close_anon_dialog(dialog.id)
                snap = snapshot(fresh)
            lang_code = lang(last_sender_id)
            text = unanswered_text(lang_code)
            with contextlib.suppress(Exception):
                await bot.send_message(last_sender_id, text)
            await notify_dialog_closed(bot, snap, last_sender_id)
        finally:
            _reply_timeouts.pop(key, None)

    _reply_timeouts[key] = asyncio.create_task(_worker())


def cancel_reply_timeout(dialog_id: int, responder_id: int) -> None:
    key = (dialog_id, responder_id)
    task = _reply_timeouts.pop(key, None)
    if task:
        task.cancel()


def cancel_all_timeouts(dialog_id: int) -> None:
    keys = [k for k in _reply_timeouts if k[0] == dialog_id]
    for key in keys:
        task = _reply_timeouts.pop(key)
        task.cancel()
