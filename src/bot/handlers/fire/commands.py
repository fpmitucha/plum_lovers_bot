from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.utils.repo import Repo
from bot.handlers.anon.common import admin_targets

from .common import (
    VALID_DORMS,
    incident_user_text,
    incident_admin_text,
    review_keyboard,
    sanitize_description,
    validate_description,
)
from .states import FireStates

router = Router(name="fire-commands")


@router.message(Command("fire"))
async def cmd_fire(message: Message, state: FSMContext) -> None:
    await state.set_state(FireStates.waiting_dorm)
    await message.answer(
        "🔥 Сообщение о пожарке\n\n"
        "Введи номер дорма (1–7), где сработала сигнализация."
    )


@router.message(FireStates.waiting_dorm)
async def on_dorm(
    message: Message,
    state: FSMContext,
) -> None:
    if not message.text:
        await message.answer("Пришли номер дорма (1–7).")
        return
    try:
        dorm = int(message.text.strip())
    except ValueError:
        await message.answer("Нужен номер от 1 до 7.")
        return
    if dorm not in VALID_DORMS:
        await message.answer("Доступны только дормы с номерами 1–7.")
        return
    await state.update_data(dorm_number=dorm)
    await state.set_state(FireStates.waiting_description)
    await message.answer("Кратко опиши, что произошло (минимум 5 символов).")


@router.message(FireStates.waiting_description)
async def on_description(
    message: Message,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    data = await state.get_data()
    dorm_number = data.get("dorm_number")
    if not dorm_number:
        await state.clear()
        await message.answer("Контекст потерян. Начни заново через /fire.")
        return
    error = validate_description(message.text or "")
    if error:
        await message.answer(error)
        return
    description = sanitize_description(message.text)

    async with session_maker() as session:
        repo = Repo(session)
        incident = await repo.create_fire_incident(
            dorm_number=dorm_number,
            user_id=message.from_user.id,
            description=description,
        )

    await state.clear()
    await message.answer("✅ " + incident_user_text(dorm_number))
    await _notify_admins(message, incident, description, session_maker)


async def _notify_admins(message: Message, incident, description: str, session_maker) -> None:
    targets = await admin_targets(session_maker)
    if not targets:
        return
    kb = review_keyboard(incident.id).as_markup()
    text = incident_admin_text(incident, description)
    for admin_id in targets:
        try:
            await message.bot.send_message(admin_id, text, reply_markup=kb)
        except Exception:
            continue
