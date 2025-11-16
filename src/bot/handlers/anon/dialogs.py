from __future__ import annotations

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.utils.repo import Repo

from .callbacks import DialogCB
from .common import (
    active_dialog,
    awaiting_consent_text,
    cancel_all_timeouts,
    cancel_reply_timeout,
    consent_keyboard,
    consent_prompt_text,
    ensure_rate,
    lang,
    main_admin_id,
    new_dialog,
    notify_dialog_closed,
    receiver_blocked_text,
    self_blocked_text,
    dialog_role,
    resolve_target,
    schedule_reply_timeout,
    send_dialog_message,
    should_show_header,
    snapshot,
    tr,
    validation_error,
)
from .states import AnonStates

router = Router(name="anon-dialogs")


@router.message(AnonStates.waiting_target)
async def on_target(message: Message, state: FSMContext, session_maker: async_sessionmaker[AsyncSession]) -> None:
    lang_code = lang(message.from_user.id)
    async with session_maker() as session:
        repo = Repo(session)
        try:
            target_id = await resolve_target(repo, message.text)
        except ValueError:
            await message.answer(tr(lang_code, "Не удалось определить пользователя. Проверь ввод.", "Could not resolve the user. Check the input."))
            return
        if not target_id:
            await message.answer(tr(lang_code, "Укажи ID или @username.", "Send an ID or @username."))
            return
        try:
            await ensure_rate(message.from_user.id, lang_code)
        except ValueError as err:
            await message.answer(str(err))
            return
        existing = await active_dialog(repo, message.from_user.id, kind="user")
        if existing:
            await message.answer(tr(lang_code, "Сначала завершите текущий диалог.", "Please close the active dialog first."))
            return
        sender_pref = await repo.get_anon_pref_mode(message.from_user.id)
        if sender_pref == "reject":
            await message.answer(tr(lang_code, "Вы отключили анонимные чаты. Сначала включите их в настройках.", "You disabled anonymous chats. Enable them in settings first."))
            return
        target_pref = await repo.get_anon_pref_mode(target_id)
        if target_pref == "reject":
            await message.answer(tr(lang_code, "Пользователь отключил анонимные чаты.", "The user disabled anonymous chats."))
            return
        target_consent = "pending" if target_pref == "confirm" else "approved"
        code = await new_dialog(
            repo,
            initiator_id=message.from_user.id,
            target_id=target_id,
            kind="user",
            target_consent=target_consent,
        )
    await state.set_state(AnonStates.dialog_message)
    await state.update_data(dialog_code=code, kind="user")
    await message.answer(tr(lang_code, f"Диалог #{code} создан. Отправь первое сообщение.", f"Dialog #{code} is created. Send the first message."))


@router.message(AnonStates.dialog_message)
async def on_dialog_message(message: Message, state: FSMContext, session_maker: async_sessionmaker[AsyncSession]) -> None:
    lang_code = lang(message.from_user.id)
    if not message.text:
        await message.answer(tr(lang_code, "Нужно отправить текст.", "Text only."))
        return
    error = validation_error(message.text, lang_code)
    if error:
        await message.answer(error)
        return
    try:
        await ensure_rate(message.from_user.id, lang_code)
    except ValueError as err:
        await message.answer(str(err))
        return

    data = await state.get_data()
    dialog_code = data.get("dialog_code")
    if not dialog_code:
        await state.clear()
        await message.answer(tr(lang_code, "Контекст потерян. Начни заново через /anon.", "Context lost. Start again via /anon."))
        return

    async with session_maker() as session:
        repo = Repo(session)
        dialog_row = await repo.get_anon_dialog_by_code(dialog_code)
        if not dialog_row or dialog_row.status != "active":
            await state.clear()
            await message.answer(tr(lang_code, "Диалог уже закрыт.", "This dialog is closed."))
            return
        dialog = snapshot(dialog_row)
        if message.from_user.id not in (dialog.initiator_id, dialog.target_id):
            await message.answer(tr(lang_code, "Ты не участник диалога.", "You are not a participant."))
            return
        recipient = dialog.target_id if dialog.initiator_id == message.from_user.id else dialog.initiator_id
        cancel_reply_timeout(dialog.id, message.from_user.id)
        await _deliver_user_message(
            message=message,
            dialog=dialog,
            repo=repo,
            recipient_id=recipient,
            text=message.text.strip(),
            session_maker=session_maker,
        )


async def _deliver_user_message(
    *,
    message: Message,
    dialog,
    repo: Repo,
    recipient_id: int,
    text: str,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    lang_code = lang(message.from_user.id)
    sender_mode = await repo.get_anon_pref_mode(message.from_user.id)
    if sender_mode == "reject":
        await message.answer(self_blocked_text(lang_code))
        await repo.close_anon_dialog(dialog.id)
        cancel_all_timeouts(dialog.id)
        await notify_dialog_closed(message.bot, dialog, message.from_user.id)
        return
    recipient_mode = await repo.get_anon_pref_mode(recipient_id)
    role = dialog_role(dialog, recipient_id, as_recipient=True)
    consent_status = dialog.target_consent if role == "target" else dialog.initiator_consent
    if recipient_mode == "reject":
        await message.answer(receiver_blocked_text(lang_code))
        await repo.close_anon_dialog(dialog.id)
        cancel_all_timeouts(dialog.id)
        await notify_dialog_closed(message.bot, dialog, message.from_user.id)
        return
    pending_request = None
    if recipient_mode == "confirm":
        if consent_status == "rejected":
            await message.answer(tr(lang_code, "Собеседник отклонил этот диалог.", "The recipient declined this chat."))
            return
        pending_request = await repo.get_pending_consent_request(dialog.id, recipient_id)
        if pending_request:
            await message.answer(awaiting_consent_text(lang_code))
            return
    should_request_consent = recipient_mode == "confirm" and consent_status != "approved"
    with_header = should_show_header(dialog, recipient_id)
    if should_request_consent:
        msg = await repo.add_anon_message(
            dialog_id=dialog.id,
            sender_id=message.from_user.id,
            recipient_id=recipient_id,
            text=text,
            delivered=False,
        )
        await repo.set_dialog_consent(dialog.id, role, "pending")
        request = await repo.create_consent_request(
            dialog_id=dialog.id,
            recipient_id=recipient_id,
            pending_message_id=msg.id,
            placeholder_message_id=0,
        )
        recipient_lang = lang(recipient_id)
        placeholder = await message.bot.send_message(
            recipient_id,
            consent_prompt_text(dialog.dialog_code, recipient_lang),
            reply_markup=consent_keyboard(request.id, recipient_lang),
            parse_mode=ParseMode.HTML,
        )
        await repo.update_consent_placeholder(request.id, placeholder.message_id)
        if with_header:
            await repo.mark_dialog_header_sent(dialog.id, role)
        await message.answer(awaiting_consent_text(lang_code))
        return

    msg = await repo.add_anon_message(
        dialog_id=dialog.id,
        sender_id=message.from_user.id,
        recipient_id=recipient_id,
        text=text,
        delivered=True,
    )
    delivered = await send_dialog_message(
        bot=message.bot,
        dialog=dialog,
        recipient_id=recipient_id,
        text=text,
        lang_code=lang(recipient_id),
        with_header=with_header,
    )
    if not delivered:
        await message.answer(tr(lang_code, "Не удалось доставить сообщение.", "Failed to deliver the message."))
        return
    if with_header:
        await repo.mark_dialog_header_sent(dialog.id, role)
    await message.answer(tr(lang_code, "Отправлено.", "Delivered."))
    schedule_reply_timeout(
        dialog,
        waiting_for=recipient_id,
        message_id=msg.id,
        last_sender_id=message.from_user.id,
        bot=message.bot,
        session_maker=session_maker,
    )


@router.callback_query(DialogCB.filter())
async def dialog_callback(
    callback: CallbackQuery,
    callback_data: DialogCB,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    lang_code = lang(callback.from_user.id)
    async with session_maker() as session:
        repo = Repo(session)
        dialog = await repo.get_anon_dialog_by_code(callback_data.code)
        if not dialog or dialog.status != "active":
            await callback.answer(tr(lang_code, "Диалог уже закрыт.", "Dialog already closed."), show_alert=True)
            return
        dialog = snapshot(dialog)
    if callback.from_user.id not in (dialog.initiator_id, dialog.target_id) and callback.from_user.id != main_admin_id():
        await callback.answer(tr(lang_code, "Нет доступа к диалогу.", "You are not part of this dialog."), show_alert=True)
        return

    if callback_data.action == "reply":
        await state.set_state(AnonStates.dialog_message)
        await state.update_data(dialog_code=dialog.dialog_code, kind=dialog.kind)
        await callback.message.answer(tr(lang_code, "Напиши ответ.", "Send your reply."))
        await callback.answer()
        return

    if callback_data.action == "close":
        async with session_maker() as session:
            repo = Repo(session)
            await repo.close_anon_dialog(dialog.id)
        cancel_all_timeouts(dialog.id)
        await state.clear()
        await notify_dialog_closed(callback.bot, dialog, callback.from_user.id)
        await callback.message.answer(tr(lang_code, "Диалог закрыт.", "Dialog closed."))
        await callback.answer()


@router.message(Command("anon_exit"))
async def cmd_exit(message: Message, state: FSMContext, session_maker: async_sessionmaker[AsyncSession]) -> None:
    lang_code = lang(message.from_user.id)
    async with session_maker() as session:
        repo = Repo(session)
        dialog = await active_dialog(repo, message.from_user.id, kind="user")
        if not dialog:
            await message.answer(tr(lang_code, "Нет активных диалогов.", "No active dialog."))
            return
        await repo.close_anon_dialog(dialog.id)
    cancel_all_timeouts(dialog.id)
    await state.clear()
    await notify_dialog_closed(message.bot, dialog, message.from_user.id)
    await message.answer(tr(lang_code, "Диалог закрыт.", "Dialog closed."))
