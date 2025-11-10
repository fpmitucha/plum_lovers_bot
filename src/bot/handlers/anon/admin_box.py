from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.utils.repo import Repo

from .callbacks import DialogCB
from .common import (
    active_dialog,
    admin_inbox_text,
    admin_targets,
    ensure_rate,
    lang,
    main_admin_id,
    new_dialog,
    snapshot,
    tr,
    validation_error,
)
from .states import AnonStates

router = Router(name="anon-admin")


@router.message(AnonStates.admin_message)
async def handle_admin_message(
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
        dialog = await active_dialog(repo, message.from_user.id, kind="admin")
        target_admin = main_admin_id()
        if not target_admin:
            await message.answer(tr(lang_code, "Главный админ не настроен. Обратись к саппорту.", "Main admin is not configured."))
            return
        if dialog and dialog.target_id != target_admin:
            await repo.close_anon_dialog(dialog.id)
            dialog = None
        if not dialog:
            code = await new_dialog(repo, initiator_id=message.from_user.id, target_id=target_admin, kind="admin")
            dialog = snapshot(await repo.get_anon_dialog_by_code(code))
        await repo.add_anon_message(
            dialog_id=dialog.id,
            sender_id=message.from_user.id,
            recipient_id=target_admin,
            text=message.text.strip(),
        )

    kb = InlineKeyboardBuilder()
    kb.button(
        text="✍️ Reply (main admin)",
        callback_data=DialogCB(action="reply", code=dialog.dialog_code).pack(),
    )
    kb.adjust(1)

    targets = await admin_targets(session_maker)
    for admin_id in targets:
        try:
            await message.bot.send_message(
                admin_id,
                admin_inbox_text(lang(admin_id), dialog.dialog_code, message.text, message.from_user.id),
                reply_markup=kb.as_markup(),
            )
        except Exception:
            continue

    await state.set_state(AnonStates.dialog_message)
    await state.update_data(dialog_code=dialog.dialog_code, kind="admin")
    await message.answer(tr(lang_code, "Сообщение отправлено админам. Жди ответ.", "Message sent to admins. Wait for a reply."))
