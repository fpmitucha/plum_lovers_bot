from __future__ import annotations

import contextlib

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import settings
from bot.utils.repo import Repo

from .callbacks import PublicCB
from .common import (
    admin_targets,
    ensure_rate,
    lang,
    public_preview,
    public_request_text,
    tr,
    validation_error,
)
from .states import AnonStates

router = Router(name="anon-public")


@router.message(AnonStates.public_message)
async def handle_public_message(
    message: Message,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    lang_code = lang(message.from_user.id)
    error = validation_error(message.text, lang_code)
    if error:
        await message.answer(error)
        return
    try:
        await ensure_rate(message.from_user.id, lang_code)
    except ValueError as err:
        await message.answer(str(err))
        return

    async with session_maker() as session:
        repo = Repo(session)
        req = await repo.create_public_request(user_id=message.from_user.id, text=message.text.strip())

    targets = await admin_targets(session_maker)
    for admin_id in targets:
        try:
            admin_lang = lang(admin_id)
            kb = InlineKeyboardBuilder()
            kb.button(text=tr(admin_lang, "✅ Одобрить", "✅ Approve"), callback_data=PublicCB(action="approve", request_id=req.id).pack())
            kb.button(text=tr(admin_lang, "⛔️ Отклонить", "⛔️ Reject"), callback_data=PublicCB(action="reject", request_id=req.id).pack())
            kb.adjust(2)
            await message.bot.send_message(
                admin_id,
                public_request_text(admin_lang, req.id, message.text, message.from_user.id),
                reply_markup=kb.as_markup(),
            )
        except Exception:
            continue

    await state.clear()
    await message.answer(tr(lang_code, "Сообщение отправлено на модерацию. Уведомим о результате.", "Your text was sent for moderation. We'll notify you once it's processed."))


@router.callback_query(PublicCB.filter(F.action == "approve"))
async def approve_public(callback: CallbackQuery, callback_data: PublicCB, session_maker: async_sessionmaker[AsyncSession]) -> None:
    lang_code = lang(callback.from_user.id)
    async with session_maker() as session:
        repo = Repo(session)
        req = await repo.get_public_request(callback_data.request_id)
        if not req or req.status != "pending":
            await callback.answer(tr(lang_code, "Запрос уже обработан.", "This request is already processed."), show_alert=True)
            return
        req_user_id = req.user_id
        req_text = req.text
        try:
            await callback.bot.send_message(int(settings.TARGET_CHAT_ID), public_preview(req_text, lang_code), parse_mode="HTML")
        except Exception as exc:
            await repo.update_public_request_status(
                request_id=req.id,
                status="failed",
                processed_by=callback.from_user.id,
                reason=str(exc),
            )
            with contextlib.suppress(Exception):
                await callback.bot.send_message(req_user_id, tr(lang(req_user_id), "Не удалось опубликовать сообщение. Попробуй позже.", "Failed to post your message. Try later."))
            await callback.answer(tr(lang_code, "Ошибка публикации.", "Failed to post."), show_alert=True)
            return

        await repo.update_public_request_status(
            request_id=req.id,
            status="approved",
            processed_by=callback.from_user.id,
        )

    with contextlib.suppress(Exception):
        await callback.bot.send_message(req_user_id, tr(lang(req_user_id), "✅ Сообщение опубликовано в чате.", "✅ Your message was published."))
    await callback.message.edit_text(tr(lang_code, "Сообщение опубликовано.", "Message posted."))
    await callback.answer()


@router.callback_query(PublicCB.filter(F.action == "reject"))
async def reject_public(callback: CallbackQuery, callback_data: PublicCB, session_maker: async_sessionmaker[AsyncSession]) -> None:
    lang_code = lang(callback.from_user.id)
    async with session_maker() as session:
        repo = Repo(session)
        req = await repo.get_public_request(callback_data.request_id)
        if not req or req.status != "pending":
            await callback.answer(tr(lang_code, "Запрос уже обработан.", "This request is already processed."), show_alert=True)
            return
        req_user_id = req.user_id
        await repo.update_public_request_status(
            request_id=req.id,
            status="rejected",
            processed_by=callback.from_user.id,
            reason="rejected",
        )

    with contextlib.suppress(Exception):
        await callback.bot.send_message(req_user_id, tr(lang(req_user_id), "❌ Сообщение не прошло модерацию.", "❌ Your message was not approved."))
    await callback.message.edit_text(tr(lang_code, "Сообщение отклонено.", "Request rejected."))
    await callback.answer()
