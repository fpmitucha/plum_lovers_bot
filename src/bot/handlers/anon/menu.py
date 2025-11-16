from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.utils.repo import Repo

from .callbacks import MenuCB
from .common import (
    active_dialog,
    admin_targets,
    ensure_rate,
    lang,
    main_admin_id,
    new_dialog,
    notify_dialog_closed,
    receiver_blocked_text,
    resolve_target,
    self_blocked_text,
    snapshot,
    tr,
)
from .dialogs import _deliver_user_message
from .states import AnonStates

router = Router(name="anon-menu")


def _menu_caption(lang_code: str, dialog_code: str | None) -> str:
    text = tr(
        lang_code,
        "✉️ <b>Анонимный центр связи</b>\n\nВыбери действие: написать пользователю,"
        " обратиться к админам или отправить сообщение в общий чат (только после одобрения).\n",
        "✉️ <b>Anonymous hub</b>\n\nChoose your next step: message a user, contact admins,"
        " or request a public post (requires approval).\n",
    )
    if dialog_code:
        text += tr(
            lang_code,
            f"\nТекущий диалог: <b>#{dialog_code}</b>. Можно продолжить или завершить.\n",
            f"\nActive dialog: <b>#{dialog_code}</b>. You can continue or close it.\n",
        )
    return text


def _menu_keyboard(lang_code: str, has_dialog: bool) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang_code, "💬 Написать пользователю", "💬 Message a user"), callback_data=MenuCB(action="dialog_start").pack())
    if has_dialog:
        kb.button(text=tr(lang_code, "▶️ Продолжить диалог", "▶️ Continue dialog"), callback_data=MenuCB(action="dialog_continue").pack())
        kb.button(text=tr(lang_code, "🚪 Завершить диалог", "🚪 Close dialog"), callback_data=MenuCB(action="dialog_close").pack())
    kb.button(text=tr(lang_code, "🛎 Сообщение админам", "🛎 Message admins"), callback_data=MenuCB(action="admins").pack())
    kb.button(text=tr(lang_code, "📣 В общий чат", "📣 Public chat"), callback_data=MenuCB(action="public").pack())
    kb.button(text=tr(lang_code, "⚙️ Настройки", "⚙️ Settings"), callback_data=MenuCB(action="settings").pack())
    kb.adjust(1)
    return kb


@router.message(Command("anon"))
async def cmd_anon(
    message: Message,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
    command: CommandObject | None = None,
) -> None:
    await state.clear()
    if command and (command.args or "").strip():
        handled = await _handle_direct_command(message, state, session_maker, command.args.strip())
        if handled:
            return
    lang_code = lang(message.from_user.id)
    async with session_maker() as session:
        repo = Repo(session)
        dialog = await active_dialog(repo, message.from_user.id, kind="user")
    await message.answer(
        _menu_caption(lang_code, dialog.dialog_code if dialog else None),
        reply_markup=_menu_keyboard(lang_code, bool(dialog)).as_markup(),
    )


@router.callback_query(MenuCB.filter(F.action == "dialog_start"))
async def cb_start_dialog(callback: CallbackQuery, state: FSMContext, session_maker: async_sessionmaker[AsyncSession]) -> None:
    lang_code = lang(callback.from_user.id)
    async with session_maker() as session:
        repo = Repo(session)
        dialog = await active_dialog(repo, callback.from_user.id, kind="user")
    if dialog:
        await callback.answer(tr(lang_code, "Диалог уже открыт.", "You already have an active dialog."), show_alert=True)
        return
    await state.set_state(AnonStates.waiting_target)
    await callback.message.answer(tr(lang_code, "Введи ID или @username получателя.", "Send the recipient ID or @username."))
    await callback.answer()


@router.callback_query(MenuCB.filter(F.action == "dialog_continue"))
async def cb_continue_dialog(callback: CallbackQuery, state: FSMContext, session_maker: async_sessionmaker[AsyncSession]) -> None:
    lang_code = lang(callback.from_user.id)
    async with session_maker() as session:
        repo = Repo(session)
        dialog = await active_dialog(repo, callback.from_user.id, kind="user")
    if not dialog:
        await callback.answer(tr(lang_code, "Активного диалога нет.", "No active dialog found."), show_alert=True)
        return
    await state.set_state(AnonStates.dialog_message)
    await state.update_data(dialog_code=dialog.dialog_code, kind="user")
    await callback.message.answer(tr(lang_code, "Напиши сообщение собеседнику.", "Send your message."))
    await callback.answer()


@router.callback_query(MenuCB.filter(F.action == "dialog_close"))
async def cb_close_dialog(callback: CallbackQuery, state: FSMContext, session_maker: async_sessionmaker[AsyncSession]) -> None:
    lang_code = lang(callback.from_user.id)
    async with session_maker() as session:
        repo = Repo(session)
        dialog = await active_dialog(repo, callback.from_user.id, kind="user")
        if not dialog:
            await callback.answer(tr(lang_code, "Диалог уже закрыт.", "Dialog already closed."), show_alert=True)
            return
        await repo.close_anon_dialog(dialog.id)
    await state.clear()
    await notify_dialog_closed(callback.bot, dialog, callback.from_user.id)
    await callback.message.answer(tr(lang_code, "Диалог закрыт.", "Dialog closed."))
    await callback.answer()


@router.callback_query(MenuCB.filter(F.action == "admins"))
async def cb_admin_box(callback: CallbackQuery, state: FSMContext) -> None:
    lang_code = lang(callback.from_user.id)
    await state.set_state(AnonStates.admin_message)
    await callback.message.answer(tr(lang_code, "Опиши ситуацию для админов. Ответит главный админ.", "Describe the issue for admins; only the main admin will reply."))
    await callback.answer()


@router.callback_query(MenuCB.filter(F.action == "public"))
async def cb_public(callback: CallbackQuery, state: FSMContext) -> None:
    lang_code = lang(callback.from_user.id)
    await state.set_state(AnonStates.public_message)
    await callback.message.answer(tr(lang_code, "Напиши текст для публикации. Админы одобрят или отклонят.", "Send the text you want to publish. Admins will approve or reject it."))
    await callback.answer()


async def _handle_direct_command(
    message: Message,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
    raw_args: str,
) -> bool:
    lang_code = lang(message.from_user.id)
    args = (raw_args or "").strip()
    if not args:
        return False
    parts = args.split(maxsplit=1)
    target_raw = parts[0]
    body = parts[1].strip() if len(parts) > 1 else ""
    if not body:
        await message.answer(tr(lang_code, "Добавь текст сообщения после ID или username.", "Add the message text after the ID or username."))
        return True
    async with session_maker() as session:
        repo = Repo(session)
        try:
            target_id = await resolve_target(repo, target_raw)
        except ValueError:
            await message.answer(tr(lang_code, "Не удалось определить пользователя.", "Could not resolve the user."))
            return True
        if not target_id:
            await message.answer(tr(lang_code, "Укажи корректный ID или @username.", "Provide a valid ID or @username."))
            return True
        try:
            await ensure_rate(message.from_user.id, lang_code)
        except ValueError as err:
            await message.answer(str(err))
            return True
        existing = await active_dialog(repo, message.from_user.id, kind="user")
        if existing:
            await message.answer(tr(lang_code, "Сначала завершите текущий диалог.", "Please close the active dialog first."))
            return True
        sender_pref = await repo.get_anon_pref_mode(message.from_user.id)
        if sender_pref == "reject":
            await message.answer(self_blocked_text(lang_code))
            return True
        target_pref = await repo.get_anon_pref_mode(target_id)
        if target_pref == "reject":
            await message.answer(receiver_blocked_text(lang_code))
            return True
        target_consent = "pending" if target_pref == "confirm" else "approved"
        code = await new_dialog(
            repo,
            initiator_id=message.from_user.id,
            target_id=target_id,
            kind="user",
            target_consent=target_consent,
        )
        dialog_row = await repo.get_anon_dialog_by_code(code)
        dialog = snapshot(dialog_row)
        await state.set_state(AnonStates.dialog_message)
        await state.update_data(dialog_code=dialog.dialog_code, kind="user")
        await _deliver_user_message(
            message=message,
            dialog=dialog,
            repo=repo,
            recipient_id=dialog.target_id,
            text=body,
            session_maker=session_maker,
        )
    return True
