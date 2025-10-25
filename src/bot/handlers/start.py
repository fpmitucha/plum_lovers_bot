"""
Стартовое меню КЛС с выбором языка, баннерами и навигацией.

Поведение:
- В группе: просим открыть бота в ЛС.
- В ЛС: показываем приветствие + картинку (если настроена в settings.START_PHOTO_URL)
        + выбор языка (🇷🇺/🇬🇧).
- После выбора языка показываем главное меню (баннер меняется на AFTER_LANG_BANNER):
  слева «КЛС инфо / Club info», справа «Вступить в КЛС / Join the club».
- Экран «КЛС инфо / Club info» показывает отдельный баннер INFO_BANNER, цитату,
  описание и кнопки: «Вступить / Join» и «⬅️ Назад / Back».
- При нажатии «Вступить в КЛС» сообщение динамически меняется на форму с баннером JOIN_BANNER.

Баннеры:
- Приветственный — берётся из settings.START_PHOTO_URL (локальный путь | file_id | URL).
- После выбора языка — ./data/pls_afterchangelanguage_banner.png
- Экран «КЛС инфо»  — ./data/pls_info_banner_600x400.png
- Экран «Вступить»  — ./data/pls_join_ru_banner_600x400.png / en-версия при EN.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.filters.callback_data import CallbackData
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

from bot.config import settings
from bot.keyboards.common import JoinCB
from bot.services.i18n import set_lang, get_lang
from bot.handlers.join import JoinStates

router = Router(name="start")

# --- Локальные пути баннеров ---
AFTER_LANG_BANNER = "./data/pls_afterchangelanguage_banner.png"
INFO_BANNER = "./data/pls_info_banner_600x400.png"
JOIN_BANNER = {
    "ru": "./data/pls_join_ru_banner_600x400.png",
    "en": "./data/pls_join_en_banner_600x400.png",
}


class StartCB(CallbackData, prefix="start"):
    """
    CallbackData для стартового меню.

    action:
      - "lang" — выбрать язык (value=ru|en)
      - "info" — открыть экран информации (value=ru|en)
      - "back" — вернуться в главное меню (value=ru|en)
    """
    action: str
    value: Optional[str] = None  # ru | en | None


# --- Тексты интерфейса ---

_T = {
    "greet": {
        "text": (
            "Приветствуем в официальном боте <b>Клуба Любителей Слив</b> — "
            "места, где добро превращается в знания.\n\n"
            "Чтобы продолжить, выберите язык интерфейса:"
        )
    },
    "menu": {
        "ru": "Добро пожаловать в <b>КЛС</b> — закрытое место, где добро превращается в знания.\n\nВыберите раздел ниже.",
        "en": "Welcome to the <b>Plum Lovers Club</b> — a private place where kindness becomes knowledge.\n\nChoose a section below.",
    },
    "btn_info": {"ru": "КЛС инфо", "en": "Club info"},
    "btn_join": {"ru": "Вступить в КЛС", "en": "Join the club"},
    "btn_back": {"ru": "⬅️ Назад", "en": "⬅️ Back"},
    "info": {
        "ru": (
            "<blockquote>Твори добро и не болтай о том, Хороших дел не порти хвастовством.</blockquote>"
            "КЛС — закрытое место, где добро превращается в знания. "
            "Мы здесь не за халявой, а за взаимопомощью: делимся своими конспектами, авторскими разборами "
            "и ссылками на открытые материалы, уважая труд авторов и указывая источники. "
            "Атмосфера — дружелюбие и поддержка. Никаких громких афиш и лишних имен — только тёплый чат и польза по делу.\n\n"
            "<b>Присоединяйся: возьми добро, оставь добро — и учёба станет легче.</b>"
        ),
        "en": (
            "<blockquote>Do good and don’t brag about it; boasting spoils good deeds.</blockquote>"
            "PLC is a private place where kindness turns into knowledge. "
            "We’re here for mutual help, not free rides: we share notes, original breakdowns and links to open resources, "
            "respecting authors’ work and citing sources. The vibe is friendly and supportive. "
            "No loud posters or name-dropping — just a warm chat and practical benefits.\n\n"
            "<b>Join in: take kindness, leave kindness — studying gets easier.</b>"
        ),
    },
    "join_caption": {
        "ru": (
            "Введите ваши данные в формате (на английском):\n"
            "first-last-university-program-group-course-startyear\n\n"
            "Пример: <code>ivan-ivanov-Harward-CSE-77-3-21</code>"
        ),
        "en": (
            "Enter your data in this format:\n"
            "first-last-university-program-group-course-startyear\n\n"
            "Example: <code>john-doe-Harward-CSE-77-3-21</code>"
        ),
    },
}


# --- Клавиатуры ---

def _lang_kb() -> InlineKeyboardMarkup:
    """Клавиатура выбора языка: 🇷🇺 Русский / 🇬🇧 English."""
    kb = InlineKeyboardBuilder()
    kb.add(InlineKeyboardButton(text="Русский 🇷🇺", callback_data=StartCB(action="lang", value="ru").pack()))
    kb.add(InlineKeyboardButton(text="English 🇬🇧", callback_data=StartCB(action="lang", value="en").pack()))
    kb.adjust(2)
    return kb.as_markup()


def _main_menu_kb(lang: str, *, show_join: bool = True) -> InlineKeyboardMarkup:
    """
    Главная клавиатура на выбранном языке.

    :param lang: 'ru' | 'en'
    :param show_join: показывать ли кнопку «Вступить»
    """
    kb = InlineKeyboardBuilder()
    kb.add(InlineKeyboardButton(text=_T["btn_info"][lang], callback_data=StartCB(action="info", value=lang).pack()))
    if show_join:
        kb.add(InlineKeyboardButton(text=_T["btn_join"][lang], callback_data=JoinCB(action="start").pack()))
    kb.adjust(2 if show_join else 1)
    return kb.as_markup()


def _info_menu_kb(lang: str, *, show_join: bool = True) -> InlineKeyboardMarkup:
    """
    Клавиатура под экраном «Инфо».

    :param lang: 'ru' | 'en'
    :param show_join: показывать ли кнопку «Вступить»
    """
    kb = InlineKeyboardBuilder()
    if show_join:
        kb.add(InlineKeyboardButton(text=_T["btn_join"][lang], callback_data=JoinCB(action="start").pack()))
    kb.add(InlineKeyboardButton(text=_T["btn_back"][lang], callback_data=StartCB(action="back", value=lang).pack()))
    kb.adjust(2 if show_join else 1)
    return kb.as_markup()


def _join_prompt_kb(lang: str) -> InlineKeyboardMarkup:
    """
    Клавиатура под формой «Вступить».
    Оставляем только кнопку «Назад» / «Back».
    """
    kb = InlineKeyboardBuilder()
    kb.add(InlineKeyboardButton(text=_T["btn_back"][lang], callback_data=StartCB(action="back", value=lang).pack()))
    kb.adjust(1)
    return kb.as_markup()


# --- Утилита для источника фото ---

def _resolve_photo_source(src: str) -> Union[str, FSInputFile]:
    """
    Подготовить источник фото для Telegram:
    1) 'file_id:...' → вернуть сам file_id;
    2) 'http(s)://'  → вернуть URL как есть;
    3) иначе считаем локальным путём и отдаём FSInputFile, если файл существует.
    """
    if not src:
        raise ValueError("Пустой путь к изображению")

    s = src.strip().strip('"').strip("'")

    if s.startswith("file_id:"):
        return s.split("file_id:", 1)[1].strip()
    if s.startswith(("http://", "https://")):
        return s

    p = Path(s).expanduser()
    if p.exists() and p.is_file():
        return FSInputFile(p)

    return s


# --- Хэндлеры ---

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """
    /start:
    - если чат не private — просим перейти в ЛС;
    - если private — показываем приветствие с картинкой (если настроена) и кнопки выбора языка.
    """
    if message.chat.type != "private":
        me = await message.bot.get_me()
        pm_url = f"https://t.me/{me.username}?start=join"
        await message.answer(
            "Откройте бота в личных сообщениях, чтобы продолжить:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Перейти в ЛС", url=pm_url)]]
            ),
        )
        return

    photo_src = (getattr(settings, "START_PHOTO_URL", "") or "").strip()
    if photo_src:
        try:
            photo = _resolve_photo_source(photo_src)
            await message.answer_photo(
                photo=photo,
                caption=_T["greet"]["text"],
                parse_mode=ParseMode.HTML,
                reply_markup=_lang_kb(),
            )
            return
        except Exception:
            # Падаем на текст, если фото не загрузилось
            pass

    await message.answer(
        _T["greet"]["text"],
        parse_mode=ParseMode.HTML,
        reply_markup=_lang_kb(),
    )


@router.callback_query(StartCB.filter(F.action == "lang"))
async def on_lang_selected(cb: CallbackQuery, callback_data: StartCB) -> None:
    """
    Обработчик выбора языка (ru|en).
    Меняем баннер на AFTER_LANG_BANNER и показываем главное меню.
    Также сохраняем язык пользователя.
    """
    lang = callback_data.value or "ru"
    set_lang(cb.from_user.id, lang)

    media = InputMediaPhoto(
        media=_resolve_photo_source(AFTER_LANG_BANNER),
        caption=_T["menu"][lang],
        parse_mode=ParseMode.HTML,
    )
    try:
        await cb.message.edit_media(media=media, reply_markup=_main_menu_kb(lang, show_join=True))
    except Exception:
        try:
            await cb.message.answer_photo(
                photo=_resolve_photo_source(AFTER_LANG_BANNER),
                caption=_T["menu"][lang],
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu_kb(lang, show_join=True),
            )
            await cb.message.delete()
        except Exception:
            await cb.message.answer(
                _T["menu"][lang],
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu_kb(lang, show_join=True),
            )
    await cb.answer()


@router.callback_query(StartCB.filter(F.action == "info"))
async def on_info(cb: CallbackQuery, callback_data: StartCB) -> None:
    """
    Показать экран «КЛС инфо / Club info» на выбранном языке с баннером INFO_BANNER.
    """
    lang = callback_data.value or get_lang(cb.from_user.id) or "ru"

    media = InputMediaPhoto(
        media=_resolve_photo_source(INFO_BANNER),
        caption=_T["info"][lang],
        parse_mode=ParseMode.HTML,
    )
    try:
        await cb.message.edit_media(media=media, reply_markup=_info_menu_kb(lang, show_join=True))
    except Exception:
        try:
            await cb.message.answer_photo(
                photo=_resolve_photo_source(INFO_BANNER),
                caption=_T["info"][lang],
                parse_mode=ParseMode.HTML,
                reply_markup=_info_menu_kb(lang, show_join=True),
            )
            await cb.message.delete()
        except Exception:
            await cb.message.answer(
                _T["info"][lang],
                parse_mode=ParseMode.HTML,
                reply_markup=_info_menu_kb(lang, show_join=True),
            )
    await cb.answer()


@router.callback_query(StartCB.filter(F.action == "back"))
async def on_back(cb: CallbackQuery, callback_data: StartCB) -> None:
    """
    Вернуться в главное меню (баннер снова AFTER_LANG_BANNER).
    """
    lang = callback_data.value or get_lang(cb.from_user.id) or "ru"

    media = InputMediaPhoto(
        media=_resolve_photo_source(AFTER_LANG_BANNER),
        caption=_T["menu"][lang],
        parse_mode=ParseMode.HTML,
    )
    try:
        await cb.message.edit_media(media=media, reply_markup=_main_menu_kb(lang, show_join=True))
    except Exception:
        try:
            await cb.message.answer_photo(
                photo=_resolve_photo_source(AFTER_LANG_BANNER),
                caption=_T["menu"][lang],
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu_kb(lang, show_join=True),
            )
            await cb.message.delete()
        except Exception:
            await cb.message.answer(
                _T["menu"][lang],
                parse_mode=ParseMode.HTML,
                reply_markup=_main_menu_kb(lang, show_join=True),
            )
    await cb.answer()


@router.callback_query(JoinCB.filter(F.action == "start"))
async def on_join_start(cb: CallbackQuery, state: FSMContext) -> None:
    """
    Динамически заменить текущее сообщение на форму «Вступить в КЛС»
    с баннером JOIN_BANNER (в зависимости от языка) и подсказкой по формату.
    Также переводим FSM в состояние ожидания слага.
    """
    lang = get_lang(cb.from_user.id) or "ru"

    media = InputMediaPhoto(
        media=_resolve_photo_source(JOIN_BANNER["en" if lang == "en" else "ru"]),
        caption=_T["join_caption"][lang],
        parse_mode=ParseMode.HTML,
    )
    try:
        await cb.message.edit_media(media=media, reply_markup=_join_prompt_kb(lang))
    except Exception:
        try:
            await cb.message.answer_photo(
                photo=_resolve_photo_source(JOIN_BANNER["en" if lang == "en" else "ru"]),
                caption=_T["join_caption"][lang],
                parse_mode=ParseMode.HTML,
                reply_markup=_join_prompt_kb(lang),
            )
            await cb.message.delete()
        except Exception:
            await cb.message.answer(
                _T["join_caption"][lang],
                parse_mode=ParseMode.HTML,
                reply_markup=_join_prompt_kb(lang),
            )

    # Правильная установка состояния FSM
    await state.set_state(JoinStates.waiting_slug)

    await cb.answer()


@router.message(F.photo, F.from_user.id.in_(settings.ADMIN_USER_IDS))
async def grab_file_id(message: Message) -> None:
    """
    Вернуть админам file_id последнего фото (для START_PHOTO_URL=file_id:...),
    чтобы удобно прикреплять картинку к стартовому экрану.
    """
    file_id = message.photo[-1].file_id
    await message.answer(f"file_id: `{file_id}`", parse_mode="Markdown")
