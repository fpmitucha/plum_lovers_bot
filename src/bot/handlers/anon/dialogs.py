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
    ensure_rate,
    lang,
    main_admin_id,
    new_dialog,
    notify_dialog_closed,
    resolve_target,
    send_dialog_message,
    snapshot,
    tr,
    validation_error,
)
from .states import AnonStates

router = Router(name="anon-dialogs")


@router.message(AnonStates.waiting_target)
async def on_target(message: Message, state: FSMContext, session_maker: async_sessionmaker[AsyncSession]) -> None:
    lang_code = lang(message.from_user.id)
    try:
        target_id = await resolve_target(message.text)
    except Exception:
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

    async with session_maker() as session:
        repo = Repo(session)
        existing = await active_dialog(repo, message.from_user.id, kind="user")
        if existing:
            await message.answer(tr(lang_code, "Сначала завершите текущий диалог.", "Please close the active dialog first."))
            return
        code = await new_dialog(repo, initiator_id=message.from_user.id, target_id=target_id, kind="user")
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
        dialog = await repo.get_anon_dialog_by_code(dialog_code)
        if not dialog or dialog.status != "active":
            await state.clear()
            await message.answer(tr(lang_code, "Диалог уже закрыт.", "This dialog is closed."))
            return
        dialog = snapshot(dialog)
        if message.from_user.id not in (dialog.initiator_id, dialog.target_id):
            await message.answer(tr(lang_code, "Ты не участник диалога.", "You are not a participant."))
            return
        recipient = dialog.target_id if dialog.initiator_id == message.from_user.id else dialog.initiator_id
        await repo.add_anon_message(dialog_id=dialog.id, sender_id=message.from_user.id, recipient_id=recipient, text=message.text.strip())

    delivered = await send_dialog_message(
        bot=message.bot,
        dialog=dialog,
        recipient_id=recipient,
        text=message.text,
        lang_code=lang(recipient),
    )
    if not delivered:
        await message.answer(tr(lang_code, "Не удалось доставить сообщение.", "Failed to deliver the message."))
    else:
        await message.answer(tr(lang_code, "Отправлено.", "Delivered."))


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
    await state.clear()
    await notify_dialog_closed(message.bot, dialog, message.from_user.id)
    await message.answer(tr(lang_code, "Диалог закрыт.", "Dialog closed."))
