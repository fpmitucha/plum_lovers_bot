from __future__ import annotations

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.filters.command import CommandObject
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
from src.bot.services.user_info import UserInfoSource

router = Router(name="help_member")

HELP_BANNER = "./data/pls_help_600x400.png"

# ---------- тексты ----------

def _member_help_text(lang: str) -> str:
    if lang == "en":
        return (
            "<b>Available commands</b>\n\n"
            "<b>/stats</b> — karma gain statistics\n"
            "<b>/top</b> — karma leaderboard\n"
            "<b>/help</b> — this help\n"
            "<b>/whoami</b> — show your Telegram info (ID, username, name); "
            "use <code>/whoami @username</code> to check another user\n\n"
            "<i>Most features are available via buttons in the menu: "
            "Profile, Audio→Text, Rules, Settings.</i>"
        )
    return (
        "<b>Доступные команды</b>\n\n"
        "<b>/stats</b> — статистика получения кармы\n"
        "<b>/top</b> — топ по карме\n"
        "<b>/help</b> — эта справка\n"
        "<b>/whoami</b> — показать вашу информацию (ID, @username, имя); "
        "<code>/whoami @username</code> проверяет другого участника\n\n"
        "<i>Большинство функций доступны через кнопки в меню: "
        "Личный кабинет, Аудио→Текст, Правила, Настройки.</i>"
    )


def _guest_help_text(lang: str) -> str:
    if lang == "en":
        return (
            "<b>Available commands</b>\n\n"
            "<b>/help</b> — this help\n"
            "<b>/whoami</b> — show your Telegram info (ID, username, name); "
            "use <code>/whoami @username</code> to check another user\n\n"
            "<b>Registration required</b>\n"
            "To unlock full functionality (materials, tasks, stats and saved items), "
            "please complete a short registration. This confirms your PLC membership "
            "and saves your progress."
        )
    return (
        "<b>Доступные команды</b>\n\n"
        "<b>/help</b> — эта справка\n"
        "<b>/whoami</b> — показать вашу информацию (ID, @username, имя); "
        "<code>/whoami @username</code> проверяет другого участника\n\n"
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


@router.message(Command("whoami"))
async def cmd_whoami(message: Message, command: CommandObject) -> None:
    """Показать Telegram ID пользователя."""
    import logging
    logger = logging.getLogger("innopls-bot")
    logger.info(f"Команда /whoami вызвана пользователем {message.from_user.id}")
    
    try:
        lang = (get_lang(message.from_user.id) or "ru").lower()
        logger.info(f"command object: {command}, command.args: {getattr(command, 'args', 'NO ARGS ATTR')}")
        
        if command.args and command.args.strip():
            username_to_check = command.args.strip().lstrip("@")
            try:
                user_info = UserInfoSource().get_user_info(username_to_check)
                if not user_info or "id" not in user_info:
                    raise RuntimeError("User not found")
            except RuntimeError:
                await message.answer(
                    text={"ru": "❌ Не удалось получить информацию о пользователе.",
                          "en": "❌ Failed to get user information."}[lang])
                return
            except Exception:
                await message.answer(
                    text={"ru": "❌ Не удалось получить информацию о пользователе.",
                          "en": "❌ Failed to get user information."}[lang],
                    parse_mode=ParseMode.HTML,
                )
                return

            checked_username = user_info.get("username")
            first_name = user_info.get("firstName") or ""
            last_name = user_info.get("lastName") or ""
            if lang == "en":
                text = (
                    f"<b>Telegram Information for @{username_to_check}:</b>\n\n"
                    f"<b>ID:</b> <code>{user_info['id']}</code>\n"
                    f"<b>Username:</b> {'@' + checked_username if checked_username else 'not set'}\n"
                    f"<b>Name:</b> {f'{first_name} {last_name}'.strip() or '—'}"
                )
            else:
                text = (
                    f"<b>Информация о Telegram для @{username_to_check}:</b>\n\n"
                    f"<b>ID:</b> <code>{user_info['id']}</code>\n"
                    f"<b>Username:</b> {'@' + checked_username if checked_username else 'не установлен'}\n"
                    f"<b>Имя:</b> {f'{first_name} {last_name}'.strip() or '—'}"
                )
        else:
            user_id = message.from_user.id
            username = message.from_user.username
            first_name = message.from_user.first_name or ""
            last_name = message.from_user.last_name or ""

            if lang == "en":
                text = (
                    "<b>Your Telegram Information:</b>\n\n"
                    f"<b>ID:</b> <code>{user_id}</code>\n"
                    f"<b>Username:</b> {'@' + username if username else 'not set'}\n"
                    f"<b>Name:</b> {f'{first_name} {last_name}'.strip() or '—'}"
                )
            else:
                text = (
                    "<b>Ваша информация в Telegram:</b>\n\n"
                    f"<b>ID:</b> <code>{user_id}</code>\n"
                    f"<b>Username:</b> {'@' + username if username else 'не установлен'}\n"
                    f"<b>Имя:</b> {f'{first_name} {last_name}'.strip() or '—'}"
                )

        await message.answer(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка в обработчике /whoami: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при обработке команды.")


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
