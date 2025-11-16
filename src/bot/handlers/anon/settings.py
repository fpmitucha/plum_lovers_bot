from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.utils.repo import Repo

from .callbacks import MenuCB, PrefCB
from .common import (
    active_dialog,
    cancel_all_timeouts,
    lang,
    notify_dialog_closed,
    pref_label,
    tr,
)

router = Router(name="anon-settings")


@router.callback_query(MenuCB.filter(F.action == "settings"))
async def cb_settings(callback: CallbackQuery, session_maker: async_sessionmaker[AsyncSession]) -> None:
    lang_code = lang(callback.from_user.id)
    async with session_maker() as session:
        repo = Repo(session)
        mode = await repo.get_anon_pref_mode(callback.from_user.id)
    kb = InlineKeyboardBuilder()
    for value in ("auto", "confirm", "reject"):
        kb.button(
            text=("✅ " if mode == value else "• ") + pref_label(value, lang_code),
            callback_data=PrefCB(mode=value).pack(),
        )
    kb.button(text=tr(lang_code, "⬅️ Назад", "⬅️ Back"), callback_data=MenuCB(action="menu").pack())
    kb.adjust(1)
    text = tr(
        lang_code,
        "⚙️ <b>Настройки анонимных чатов</b>\n\n"
        "Выбери режим обработки входящих чатов:\n"
        "1. Автопринятие.\n"
        "2. Нужна ручная проверка — придёт запрос «принять / отклонить».\n"
        "3. Полный отказ (нельзя отправлять и получать).\n\n"
        f"Текущий режим: <b>{pref_label(mode, lang_code)}</b>.",
        "⚙️ <b>Anonymous chat settings</b>\n\n"
        "Choose how to handle incoming chats:\n"
        "1. Auto accept.\n"
        "2. Require confirmation (you'll get Accept / Decline buttons).\n"
        "3. Decline everything (you also can't send chats).\n\n"
        f"Current mode: <b>{pref_label(mode, lang_code)}</b>.",
    )
    await callback.message.edit_text(text, reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(PrefCB.filter())
async def cb_set_pref(
    callback: CallbackQuery,
    callback_data: PrefCB,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    lang_code = lang(callback.from_user.id)
    mode = callback_data.mode
    if mode not in {"auto", "confirm", "reject"}:
        await callback.answer("Unknown option", show_alert=True)
        return
    dialog = None
    async with session_maker() as session:
        repo = Repo(session)
        await repo.set_anon_pref_mode(callback.from_user.id, mode)
        dialog = await active_dialog(repo, callback.from_user.id, kind="user")
        if mode == "reject" and dialog:
            await repo.close_anon_dialog(dialog.id)
            cancel_all_timeouts(dialog.id)
    if mode == "reject" and dialog:
        await notify_dialog_closed(callback.bot, dialog, callback.from_user.id)
    await callback.answer(tr(lang_code, "Режим обновлён.", "Preference updated."))
    await cb_settings(callback, session_maker)
