from __future__ import annotations

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)
from aiogram.types.input_file import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from bot.handlers.start import StartCB  # используем ту же callback-data
from bot.keyboards.common import JoinCB
from bot.services.i18n import get_lang
from bot.utils.repo import Repo

router = Router(name="help_member")

HELP_BANNER = "./data/pls_help_600x400.png"

# ---------- тексты ----------

def _member_help_text(lang: str) -> str:
    if lang == "en":
        return (
            "<b>Available commands</b>\n\n"
            "<b>/start</b> — open the main menu\n"
            "<b>/menu</b> — show the menu again\n"
            "<b>/top</b> — karma leaderboard\n"
            "<b>/help</b> — this help\n\n"
            "<i>Most features are available via buttons in the menu: "
            "Profile, Audio→Text, Rules, Settings.</i>"
        )
    return (
        "<b>Доступные команды</b>\n\n"
        "<b>/start</b> — открыть основное меню\n"
        "<b>/menu</b> — показать меню ещё раз\n"
        "<b>/top</b> — топ по карме\n"
        "<b>/help</b> — эта справка\n\n"
        "<i>Большинство функций доступны через кнопки в меню: "
        "Личный кабинет, Аудио→Текст, Правила, Настройки.</i>"
    )


def _guest_help_text(lang: str) -> str:
    if lang == "en":
        return (
            "<b>Registration required</b>\n"
            "To unlock full functionality (materials, tasks, stats and saved items), "
            "please complete a short registration. This confirms your PLC membership "
            "and saves your progress."
        )
    return (
        "<b>Нужна регистрация</b>\n"
        "Чтобы открыть полный доступ к функционалу бота (материалы, задания, "
        "статистика и сохранённые), пройди короткую регистрацию. "
        "Это нужно, чтобы подтвердить участника КЛС и сохранить твой прогресс."
    )

# ---------- клавиатуры ----------

def _back_kb(lang: str) -> InlineKeyboardMarkup:
    txt = {"ru": "⬅️ Назад", "en": "⬅️ Back"}[lang]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=txt, callback_data=StartCB(action="back", value=lang).pack())]
    ])


def _guest_help_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text={"ru": "✅ Вступить в клуб", "en": "✅ Join the club"}[lang],
              callback_data=JoinCB(action="start").pack())
    kb.button(text={"ru": "⬅️ Назад", "en": "⬅️ Back"}[lang],
              callback_data=StartCB(action="back", value=lang).pack())
    kb.adjust(1, 1)
    return kb.as_markup()

# ---------- утилита показа экрана ----------

async def _render_help_for_user(
    *,
    lang: str,
    is_member: bool,
) -> tuple[InputMediaPhoto, InlineKeyboardMarkup]:
    """
    Возвращает (media, keyboard) для редактирования сообщения.
    Мы всегда рендерим как картинку с подписью — так безопаснее редактировать.
    """
    caption = _member_help_text(lang) if is_member else _guest_help_text(lang)
    kb = _back_kb(lang) if is_member else _guest_help_kb(lang)
    media = InputMediaPhoto(
        media=FSInputFile(HELP_BANNER),
        caption=caption,
        parse_mode=ParseMode.HTML,
    )
    return media, kb

# ---------- handlers ----------

@router.message(Command("help"))
async def cmd_help(message: Message, session_maker: async_sessionmaker[AsyncSession]) -> None:
    lang = (get_lang(message.from_user.id) or "ru").lower()
    async with session_maker() as s:
        repo = Repo(s)
        is_member = await repo.has_registered(message.from_user.id)

    media, kb = await _render_help_for_user(lang=lang, is_member=is_member)
    await message.answer_photo(media.media, caption=media.caption, parse_mode=media.parse_mode, reply_markup=kb)


@router.callback_query(StartCB.filter(F.action == "help"))
async def cb_help(c: CallbackQuery, session_maker: async_sessionmaker[AsyncSession]) -> None:
    lang = (get_lang(c.from_user.id) or "ru").lower()

    async with session_maker() as s:
        repo = Repo(s)
        is_member = await repo.has_registered(c.from_user.id)

    media, kb = await _render_help_for_user(lang=lang, is_member=is_member)

    # В исходном меню сообщение — с фото. Меняем его через edit_media.
    try:
        await c.message.edit_media(media=media, reply_markup=kb)
    except TelegramBadRequest:
        # если почему-то нельзя — отправим новое и удалим старое
        try:
            await c.message.answer_photo(media.media, caption=media.caption,
                                         parse_mode=media.parse_mode, reply_markup=kb)
            await c.message.delete()
        except Exception:
            pass

    # Закрыть «часики» на кнопке
    try:
        await c.answer()
    except Exception:
        pass
