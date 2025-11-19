import contextlib
from pathlib import Path
from typing import Optional, Union
from venv import logger
from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)
from aiogram.types.input_file import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy import text as sql_text

from bot.config import settings
from bot.keyboards.common import JoinCB, CabCB, SettingsCB, StartCB
from bot.services.i18n import set_lang, get_lang
from bot.utils.repo import Repo, now_str


SET_BANNER = "./data/pls_settings_600x400.png"

router = Router(name="settings")

_T = {
    "btn_sets_eng_group": {"ru": "Выбрать группу английского", "en": "Change eng group"},
    "btn_back": {"ru": "⬅️ Назад", "en": "⬅️ Back"},
}


def _resolve_photo_source(src: str) -> Union[str, FSInputFile]:
    s = (src or "").strip().strip('"').strip("'")
    if s.startswith("file_id:"):
        return s.split("file_id:", 1)[1].strip()
    if s.startswith(("http://", "https://")):
        return s
    p = Path(s).expanduser()
    if p.exists() and p.is_file():
        return FSInputFile(p)
    return s


async def _answer_photo_or_text(
    message: Message, media: InputMediaPhoto, reply_markup: Optional[InlineKeyboardMarkup]
) -> None:
    """
    Пытаемся отправить фото. Если файла нет или Telegram не принимает — отправляем просто текст.
    """
    try:
        await message.answer_photo(
            media.media,
            caption=media.caption,
            parse_mode=media.parse_mode,
            reply_markup=reply_markup,
        )
    except Exception:
        caption = media.caption or ""
        await message.answer(
            caption, parse_mode=media.parse_mode or ParseMode.HTML, reply_markup=reply_markup
        )


def _set_eng_group(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="FL", callback_data="settings:set_eng_group_set:" + lang + "|FL")
    kb.button(text="EAP", callback_data="settings:set_eng_group_set:" + lang + "|EAP")
    kb.button(text="AWA1", callback_data="settings:set_eng_group_set:" + lang + "|AWA1")
    # kb.button(text=_T["btn_sets_eng_group"][lang], callback_data="start:set_eng_group:" + lang)
    kb.button(text=_T["btn_back"][lang], callback_data=CabCB(action="back").pack())
    kb.adjust(3, 1)
    return kb.as_markup()


def _settings_menu_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text=_T["btn_sets_eng_group"][lang], callback_data="settings:set_eng_group:" + lang + "|"
    )
    kb.button(text=_T["btn_back"][lang], callback_data=CabCB(action="back").pack())
    kb.adjust(1, 1)
    return kb.as_markup()


def _back_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_T["btn_back"][lang], callback_data=CabCB(action="back").pack()
                )
            ]
        ]
    )


@router.callback_query(SettingsCB.filter(F.action == "open"))
async def on_settings(
    cb: CallbackQuery, callback_data: StartCB, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    lang = (callback_data.value or get_lang(cb.from_user.id) or "ru").lower()
    action = callback_data.action

    async with session_maker() as s:
        repo = Repo(s)

        app = await repo.get_last_application_for_user(cb.from_user.id)
        if (app.slug.split("-")[2]) != "Innopolis":
            caption = {
                "ru": "⚙️ <b>Раздел в разработке</b>.",
                "en": "⚙️ <b>Section is under construction</b>.",
            }[lang]

            media = InputMediaPhoto(
                media=_resolve_photo_source(SET_BANNER),
                caption=caption,
                parse_mode=ParseMode.HTML,
            )

            try:
                await cb.message.edit_media(media=media, reply_markup=_back_menu(lang))
            except Exception:
                await _answer_photo_or_text(cb.message, media, _back_menu(lang))
                with contextlib.suppress(Exception):
                    await cb.message.delete()
            with contextlib.suppress(TelegramBadRequest):
                await cb.answer()
        else:
            caption = {
                "ru": "⚙️ Настройки",
                "en": "⚙️ Settings",
            }[lang]
            media = InputMediaPhoto(
                media=_resolve_photo_source(SET_BANNER),
                caption=caption,
                parse_mode=ParseMode.HTML,
            )

            try:
                await cb.message.edit_media(media=media, reply_markup=_settings_menu_kb(lang))
            except Exception:
                await _answer_photo_or_text(cb.message, media, _settings_menu_kb(lang))
                with contextlib.suppress(Exception):
                    await cb.message.delete()
            with contextlib.suppress(TelegramBadRequest):
                await cb.answer()


@router.callback_query(SettingsCB.filter(F.action == "set_eng_group"))
async def on_set_eng_group(
    cb: CallbackQuery, callback_data: SettingsCB, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    lang = (callback_data.value.split("|")[0] or get_lang(cb.from_user.id) or "ru").lower()
    caption = {
        "ru": "Выберете группу по английскому языку\nТекущая группа: ",
        "en": "Chose your english group\nCurrent group: ",
    }[lang]
    eng_group = {"ru": "не выбрана", "en": "not chosen"}[lang]
    async with session_maker() as s:
        repo = Repo(s)
        res = await repo.get_profile(cb.from_user.id)
        if res.eng_group is not None:
            eng_group = res.eng_group

    media = InputMediaPhoto(
        media=_resolve_photo_source(SET_BANNER),
        caption=(caption + eng_group),
        parse_mode=ParseMode.HTML,
    )
    await cb.message.edit_media(
        media=media, parse_mode=ParseMode.HTML, reply_markup=_set_eng_group(lang)
    )


@router.callback_query(SettingsCB.filter(F.action == "set_eng_group_set"))
async def on_set_eng_group_set(
    cb: CallbackQuery, callback_data: SettingsCB, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    group = callback_data.value.split("|")[1] or ""

    # logger.info("Группа: " + group)
    async with session_maker() as s:
        repo = Repo(s)
        res = await repo.set_eng_group_profile(cb.from_user.id, group)
        # logger.info("Изменненая группа: " + str(res))

    await on_set_eng_group(cb, callback_data=callback_data, session_maker=session_maker)
