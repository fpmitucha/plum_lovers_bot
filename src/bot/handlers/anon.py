from __future__ import annotations
"""
Анонимные сообщения: пользователь пишет текст, бот отправляет его администраторам,
а они могут либо прочитать его приватно, либо (после одобрения) опубликовать в чате.
"""

import contextlib
import html
import secrets
import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import settings
from bot.handlers.admin import _get_all_admin_ids
from bot.services.i18n import get_lang
from bot.utils.repo import Repo

router = Router(name="anon")

MAX_MESSAGE_LENGTH = 1200
REQUEST_TTL_SECONDS = 3600


@dataclass
class PendingAnonRequest:
    text: str
    user_id: int
    lang: str
    created_at: float


_pending_requests: Dict[str, PendingAnonRequest] = {}


class AnonStates(StatesGroup):
    waiting_text = State()
    waiting_target = State()


class AnonUserCB(CallbackData, prefix="anonusr"):
    """CallbackData от пользователя после ввода текста."""
    target: str  # "pm" | "group"


class AnonAdminCB(CallbackData, prefix="anonadm"):
    """CallbackData для админской модерации."""
    action: str  # "approve" | "reject"
    request_id: str


_T = {
    "intro": {
        "ru": (
            "✉️ <b>Анонимные сообщения</b>\n\n"
            "Пришли текст, и мы передадим его админам без указания автора. "
            "Ты сможешь выбрать: оставить сообщение только в приватных сообщениях или "
            "отправить его в общий чат (после одобрения админом).\n\n"
            "Если передумал — /cancel."
        ),
        "en": (
            "✉️ <b>Anonymous messages</b>\n\n"
            "Send a text and we will forward it to admins without revealing the author. "
            "After that you can choose whether to keep it private or request a public post "
            "in the main chat (requires admin approval).\n\n"
            "Use /cancel to stop."
        ),
    },
    "ask_text": {
        "ru": "Опиши всё одним текстовым сообщением. Без файлов, только текст.",
        "en": "Describe everything in a single text message. Text only, no files.",
    },
    "text_too_short": {
        "ru": "Сообщение слишком короткое. Напиши хотя бы 10 символов.",
        "en": "Message is too short. Please send at least 10 characters.",
    },
    "text_too_long": {
        "ru": f"Сообщение слишком длинное. Ограничение — {MAX_MESSAGE_LENGTH} символов.",
        "en": f"Message is too long. Limit — {MAX_MESSAGE_LENGTH} characters.",
    },
    "choose_target": {
        "ru": "Куда отправляем?",
        "en": "Where should we deliver it?",
    },
    "btn_pm": {"ru": "👤 Только админам", "en": "👤 Only to admins"},
    "btn_group": {"ru": "👥 В чат (модерация)", "en": "👥 To chat (needs approval)"},
    "sent_pm": {
        "ru": "✅ Анонимное сообщение отправлено администраторам. Они обсудят его приватно.",
        "en": "✅ Anonymous message sent to admins. They will read it privately.",
    },
    "sent_group": {
        "ru": "⌛ Сообщение отправлено на модерацию. После одобрения мы опубликуем его в чате.",
        "en": "⌛ Your text was sent for moderation. It will be posted after approval.",
    },
    "admin_pm_header": {
        "ru": "📥 <b>Новое анонимное сообщение (priv)</b>\n\n",
        "en": "📥 <b>New anonymous message (priv)</b>\n\n",
    },
    "admin_group_header": {
        "ru": "🆕 <b>Запрос на публикацию анонимного сообщения</b>\n\n",
        "en": "🆕 <b>Anonymous message pending publication</b>\n\n",
    },
    "admin_dup": {
        "ru": "Этот запрос уже обработан или истёк.",
        "en": "This request was already processed or has expired.",
    },
    "admin_denied": {
        "ru": "❌ Запрос отклонён.",
        "en": "❌ Request rejected.",
    },
    "admin_posted": {
        "ru": "✅ Сообщение опубликовано в чате.",
        "en": "✅ Message has been posted to the chat.",
    },
    "user_posted": {
        "ru": "✅ Твоё анонимное сообщение опубликовано в общем чате.",
        "en": "✅ Your anonymous message has been posted in the group chat.",
    },
    "user_rejected": {
        "ru": "❌ Анонимное сообщение не прошло модерацию. Попробуй переформулировать и отправить снова.",
        "en": "❌ The anonymous message was not approved. Feel free to rephrase and send again.",
    },
    "cancelled": {
        "ru": "Готово. Если захочешь отправить новое анонимное сообщение — напиши /anon.",
        "en": "Done. Use /anon when you want to send another anonymous message.",
    },
    "no_admins": {
        "ru": "Не удалось найти админов для доставки сообщения. Попробуй позже.",
        "en": "Could not reach admins right now. Please try again later.",
    },
    "not_allowed": {
        "ru": "Нет доступа.",
        "en": "Not allowed.",
    },
}


def _lang(user_id: int) -> str:
    return (get_lang(user_id) or "ru").lower()


def _target_keyboard(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=_T["btn_pm"][lang], callback_data=AnonUserCB(target="pm").pack())
    kb.button(text=_T["btn_group"][lang], callback_data=AnonUserCB(target="group").pack())
    kb.adjust(1)
    return kb.as_markup()


async def _admin_ids(session_maker: async_sessionmaker[AsyncSession]) -> set[int]:
    async with session_maker() as session:
        repo = Repo(session)
        return await _get_all_admin_ids(repo)


async def _admin_targets(session_maker: async_sessionmaker[AsyncSession]) -> list[int]:
    ids = await _admin_ids(session_maker)
    targets: list[int] = list(ids)
    admin_notify_chat_id = getattr(settings, "ADMIN_NOTIFY_CHAT_ID", None)
    if admin_notify_chat_id:
        targets.append(int(admin_notify_chat_id))
    return targets


def _purge_expired_requests() -> None:
    now = time.time()
    for req_id, data in list(_pending_requests.items()):
        if now - data.created_at > REQUEST_TTL_SECONDS:
            _pending_requests.pop(req_id, None)


def _store_request(text: str, user_id: int, lang: str) -> str:
    _purge_expired_requests()
    request_id = secrets.token_hex(4)
    _pending_requests[request_id] = PendingAnonRequest(
        text=text,
        user_id=user_id,
        lang=lang,
        created_at=time.time(),
    )
    return request_id


def _format_admin_message(header: str, text: str, request_id: Optional[str] = None) -> str:
    body = html.escape(text).strip()
    lines = [header]
    if request_id:
        lines.append(f"<b>ID:</b> <code>{request_id}</code>\n")
    lines.append(body or "—")
    return "".join(lines)


def _format_public_message(text: str) -> str:
    body = html.escape(text).strip()
    return f"💌 <b>Анонимное сообщение</b>\n\n{body}"


async def _broadcast_admins(
    bot,
    targets: Iterable[int],
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    delivered = False
    for chat_id in targets:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
            delivered = True
        except Exception:
            continue
    return delivered


async def _ensure_admin(callback: CallbackQuery, session_maker: async_sessionmaker[AsyncSession]) -> bool:
    if not callback.from_user:
        return False
    admin_ids = await _admin_ids(session_maker)
    return callback.from_user.id in admin_ids


@router.message(Command("anon"))
async def cmd_anon(message: Message, state: FSMContext) -> None:
    lang = _lang(message.from_user.id)
    await state.clear()
    await state.set_state(AnonStates.waiting_text)
    await message.answer(
        text=_T["intro"][lang] + "\n\n" + _T["ask_text"][lang],
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if not await state.get_state():
        return
    lang = _lang(message.from_user.id)
    await state.clear()
    await message.answer(_T["cancelled"][lang])


@router.message(AnonStates.waiting_text)
async def anon_collect_text(message: Message, state: FSMContext) -> None:
    if not message.text:
        lang = _lang(message.from_user.id)
        await message.answer(_T["ask_text"][lang])
        return
    text = message.text.strip()
    lang = _lang(message.from_user.id)
    if len(text) < 10:
        await message.answer(_T["text_too_short"][lang])
        return
    if len(text) > MAX_MESSAGE_LENGTH:
        await message.answer(_T["text_too_long"][lang])
        return
    await state.update_data(text=text, lang=lang)
    await state.set_state(AnonStates.waiting_target)
    await message.answer(_T["choose_target"][lang], reply_markup=_target_keyboard(lang))


@router.callback_query(AnonStates.waiting_target, AnonUserCB.filter())
async def anon_choose_target(
    callback: CallbackQuery,
    callback_data: AnonUserCB,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    data = await state.get_data()
    text = data.get("text")
    lang = data.get("lang") or _lang(callback.from_user.id)
    if not text:
        await state.clear()
        await callback.answer("Ошибка. Попробуй заново.", show_alert=True)
        return

    targets = await _admin_targets(session_maker)
    if not targets:
        await callback.answer(_T["no_admins"][lang], show_alert=True)
        await state.clear()
        return

    if callback_data.target == "pm":
        msg = _format_admin_message(_T["admin_pm_header"][lang], text)
        ok = await _broadcast_admins(callback.message.bot, targets, msg)
        await state.clear()
        if ok:
            await callback.message.answer(_T["sent_pm"][lang])
        else:
            await callback.message.answer(_T["no_admins"][lang])
        await callback.answer()
        return

    if callback_data.target == "group":
        request_id = _store_request(text, callback.from_user.id, lang)
        kb = InlineKeyboardBuilder()
        kb.button(
            text="✅ Approve",
            callback_data=AnonAdminCB(action="approve", request_id=request_id).pack(),
        )
        kb.button(
            text="⛔️ Reject",
            callback_data=AnonAdminCB(action="reject", request_id=request_id).pack(),
        )
        kb.adjust(2)
        msg = _format_admin_message(_T["admin_group_header"][lang], text, request_id=request_id)
        ok = await _broadcast_admins(callback.message.bot, targets, msg, kb.as_markup())
        await state.clear()
        if ok:
            await callback.message.answer(_T["sent_group"][lang])
        else:
            _pending_requests.pop(request_id, None)
            await callback.message.answer(_T["no_admins"][lang])
        await callback.answer()
        return

    await callback.answer("Unknown target", show_alert=True)


@router.callback_query(AnonAdminCB.filter(F.action == "approve"))
async def anon_admin_approve(
    callback: CallbackQuery,
    callback_data: AnonAdminCB,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    if not await _ensure_admin(callback, session_maker):
        lang = _lang(callback.from_user.id) if callback.from_user else "ru"
        await callback.answer(_T["not_allowed"][lang], show_alert=True)
        return
    _purge_expired_requests()
    req = _pending_requests.pop(callback_data.request_id, None)
    lang = _lang(callback.from_user.id) if callback.from_user else "ru"
    if not req:
        await callback.answer(_T["admin_dup"][lang], show_alert=True)
        with contextlib.suppress(Exception):
            await callback.message.edit_reply_markup()
        return
    text = _format_public_message(req.text)
    await callback.bot.send_message(settings.TARGET_CHAT_ID, text, parse_mode=ParseMode.HTML)
    with contextlib.suppress(Exception):
        await callback.message.edit_text(
            _T["admin_posted"][lang],
            parse_mode=ParseMode.HTML,
        )
    await callback.answer("OK")
    with contextlib.suppress(Exception):
        await callback.bot.send_message(req.user_id, _T["user_posted"][req.lang])


@router.callback_query(AnonAdminCB.filter(F.action == "reject"))
async def anon_admin_reject(
    callback: CallbackQuery,
    callback_data: AnonAdminCB,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    if not await _ensure_admin(callback, session_maker):
        lang = _lang(callback.from_user.id) if callback.from_user else "ru"
        await callback.answer(_T["not_allowed"][lang], show_alert=True)
        return
    _purge_expired_requests()
    req = _pending_requests.pop(callback_data.request_id, None)
    lang = _lang(callback.from_user.id) if callback.from_user else "ru"
    if not req:
        await callback.answer(_T["admin_dup"][lang], show_alert=True)
        with contextlib.suppress(Exception):
            await callback.message.edit_reply_markup()
        return
    with contextlib.suppress(Exception):
        await callback.message.edit_text(_T["admin_denied"][lang])
    await callback.answer("OK")
    with contextlib.suppress(Exception):
        await callback.bot.send_message(req.user_id, _T["user_rejected"][req.lang])
