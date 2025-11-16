from __future__ import annotations

import contextlib

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.utils.repo import Repo

from .callbacks import ConsentCB
from .common import (
    cancel_all_timeouts,
    dialog_role,
    format_dialog_text,
    lang,
    notify_dialog_closed,
    reply_keyboard,
    schedule_reply_timeout,
    should_show_header,
    tr,
)

router = Router(name="anon-consent")


@router.callback_query(ConsentCB.filter())
async def on_consent(
    callback: CallbackQuery,
    callback_data: ConsentCB,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        repo = Repo(session)
        request = await repo.get_consent_request(callback_data.request_id)
        if not request:
            await callback.answer("Not found", show_alert=True)
            return
        if request.recipient_id != callback.from_user.id:
            await callback.answer("Это уведомление не для вас.", show_alert=True)
            return
        if request.status != "pending":
            await callback.answer("Запрос уже обработан.", show_alert=True)
            return
        message = await repo.get_anon_message(request.pending_message_id)
        dialog = await repo.get_anon_dialog(request.dialog_id)
        if not message or not dialog or dialog.status != "active":
            await repo.update_consent_request_status(request_id=request.id, status="rejected")
            await callback.answer("Диалог закрыт.", show_alert=True)
            return

    lang_code = lang(callback.from_user.id)
    role = dialog_role(dialog, callback.from_user.id, as_recipient=True)
    if callback_data.action == "accept":
        await handle_accept(callback, session_maker, request, message, dialog, lang_code, role)
    else:
        await handle_reject(callback, session_maker, request, message, dialog, lang_code, role)


async def handle_accept(callback, session_maker, request, message, dialog, lang_code, role) -> None:
    with_header = should_show_header(dialog, callback.from_user.id)
    async with session_maker() as session:
        repo = Repo(session)
        await repo.update_consent_request_status(request_id=request.id, status="approved")
        await repo.set_dialog_consent(dialog.id, role, "approved")
        await repo.set_message_delivered(message.id, True)
        if with_header:
            await repo.mark_dialog_header_sent(dialog.id, role)
    text = format_dialog_text(dialog, message.text, lang_code, with_header=with_header)
    try:
        await callback.bot.edit_message_text(
            text,
            chat_id=callback.message.chat.id,
            message_id=request.placeholder_message_id,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_keyboard(dialog.dialog_code, lang_code),
        )
    except Exception:
        pass
    await callback.answer(tr(lang_code, "Сообщение принято.", "Message accepted."))
    schedule_reply_timeout(
        dialog,
        waiting_for=callback.from_user.id,
        message_id=message.id,
        last_sender_id=message.sender_id,
        bot=callback.bot,
        session_maker=session_maker,
    )


async def handle_reject(callback, session_maker, request, message, dialog, lang_code, role) -> None:
    async with session_maker() as session:
        repo = Repo(session)
        await repo.update_consent_request_status(request_id=request.id, status="rejected")
        await repo.set_dialog_consent(dialog.id, role, "rejected")
        await repo.close_anon_dialog(dialog.id)
    cancel_all_timeouts(dialog.id)
    with contextlib.suppress(Exception):
        await callback.bot.edit_message_text(
            tr(lang_code, "⛔️ Чат отклонён.", "⛔️ Chat declined."),
            chat_id=callback.message.chat.id,
            message_id=request.placeholder_message_id,
        )
    sender_text = tr(
        lang(message.sender_id),
        "Пользователь отклонил анонимный чат.",
        "The user declined the anonymous chat.",
    )
    with contextlib.suppress(Exception):
        await callback.bot.send_message(message.sender_id, sender_text)
    await notify_dialog_closed(callback.bot, dialog, callback.from_user.id)
    await callback.answer(tr(lang_code, "Чат отклонён.", "Chat declined."))
