# src/bot/handlers/cleanup.py
from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest

from bot.config import settings

router = Router(name="service_cleanup")

# Удаляем сообщения "X joined the group"
@router.message(F.chat.id == settings.TARGET_CHAT_ID, F.new_chat_members)
async def purge_join_messages(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        logging.getLogger("innopls-bot").warning("Не смог удалить join-сообщение %s", message.message_id)

# (Опционально) Удаляем сообщения "X left the group"
@router.message(F.chat.id == settings.TARGET_CHAT_ID, F.left_chat_member)
async def purge_left_messages(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        # Ничего страшного — просто замолчим
        pass
