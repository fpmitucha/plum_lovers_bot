from __future__ import annotations
"""
Личный кабинет:
- Карточка с локализацией (TOP/KARMA).
- «Назад» возвращает в то же сообщение на новое главное меню (гость/пользователь).
- Под карточкой дубль: место в топе, карма, тег, айди.
"""

import os
import contextlib

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.types.input_file import FSInputFile
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from bot.utils.repo import Repo
from bot.keyboards.common import CabCB, JoinCB
from bot.graphics.cabinet_card import render_cabinet_card
from bot.services.i18n import get_lang

router = Router(name="cabinet")

AFTER_LANG_BANNER = "./data/pls_afterchangelanguage_banner.png"
CABINET_CARD_TEMPLATE = "./data/profile_card_base.png"

_T = {
    "btn_profile": {"ru": "👤 Личный кабинет", "en": "👤 Profile"},
    "btn_back": {"ru": "⬅️ Назад", "en": "⬅️ Back"},

    # подписи к меню (те же, что и в start.py)
    "menu_guest": {
        "ru": "<b>Привет!</b>\nТы в официальном боте <b>Клуба Любителей Сливов</b>. Здесь добро превращается в знания — делимся конспектами, разборами и поддержкой.\n\nЧто выбираем сегодня? 👇\n<i>Подсказка: если ты впервые здесь — начни с 🧭 Правила.\nМы не пираты — мы архивисты энтузиазма.</i>",
        "en": "<b>Hi!</b>\nYou’re in the official bot of the <b>Plum Lovers Club</b>. Kindness turns into knowledge here — we share notes, breakdowns, and support.\n\nWhat shall we choose today? 👇\n<i>Tip: if you’re new here — start with 🧭 Rules.\nWe’re not pirates — we’re archivists of enthusiasm.</i>",
    },
    "menu_user": {
        "ru": "<b>Привет!</b>\nТы в официальном боте <b>Клуба Любителей Сливов</b>. Здесь добро превращается в знания — делимся конспектами, разборами и поддержкой.\n\nЧто выбираем сегодня? 👇",
        "en": "<b>Hi!</b>\nYou’re in the official bot of the <b>Plum Lovers Club</b>. Kindness turns into knowledge here — we share notes, breakdowns, and support.\n\nWhat shall we choose today? 👇",
    },
    "btn_rules":   {"ru": "🧭 Правила",       "en": "🧭 Rules"},
    "btn_help":    {"ru": "❓ Помощь",        "en": "❓ Help"},
    "btn_join":    {"ru": "👉 Вступить в КЛС","en": "👉 Join the club"},
    "btn_info":    {"ru": "📗 КЛС инфо",      "en": "📗 Club info"},
    "btn_profile": {"ru": "👤 Личный кабинет","en": "👤 Profile"},
    "btn_a2t":     {"ru": "🔊 Аудио в текст", "en": "🔊 Audio to text"},
    "btn_gpt":     {"ru": "⚡ Chat GPT 5",    "en": "⚡ Chat GPT 5"},
    "btn_settings":{"ru": "⚙️ Настройки",     "en": "⚙️ Settings"},
    "btn_features":{"ru": "🗂 Функции",      "en": "🗂 Features"},
    "btn_link_platform": {"ru": "🔗 Подключить платформу", "en": "🔗 Connect platform"},
}

def _back_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_T["btn_back"][lang], callback_data=CabCB(action="back").pack())]]
    )

def _guest_menu_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=_T["btn_rules"][lang],   callback_data="start:rules:" + lang)
    kb.button(text=_T["btn_help"][lang],    callback_data="start:help:" + lang)
    kb.button(text=_T["btn_join"][lang],    callback_data=JoinCB(action="start").pack())
    kb.button(text=_T["btn_info"][lang],    callback_data="start:info:" + lang)
    kb.adjust(2, 2)
    return kb.as_markup()

def _user_menu_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=_T["btn_profile"][lang],       callback_data=CabCB(action="open").pack())
    kb.button(text=_T["btn_rules"][lang],         callback_data="start:rules:"  + lang)
    kb.button(text=_T["btn_features"][lang],      callback_data="start:features:" + lang)
    kb.button(text=_T["btn_help"][lang],          callback_data="start:help:"   + lang)
    kb.button(text=_T["btn_link_platform"][lang], callback_data="start:link_platform:" + lang)
    kb.adjust(2, 2, 1)
    return kb.as_markup()

async def _is_registered_and_ensure_profile(repo: Repo, user_id: int, username: str | None) -> bool:
    if await repo.profile_exists(user_id):
        return True
    app = await repo.get_last_application_for_user(user_id)
    if app and (app.status or "").lower() == "done":
        await repo.ensure_profile(user_id=user_id, username=username, slug=getattr(app, "slug", None))
        return True
    return False


@router.callback_query(CabCB.filter(F.action == "open"))
async def cb_open(c: CallbackQuery, session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as s:
        repo = Repo(s)
        prof = await repo.get_profile(c.from_user.id)
        if not prof:
            await c.answer("Profile not found. Please register first.", show_alert=True)
            return
        rank = await repo.get_rank(c.from_user.id) or 0
        # ВАЖНО: берём карму из repo.get_karma, а не напрямую из профиля
        karma = await repo.get_karma(c.from_user.id)

    lang = (get_lang(c.from_user.id) or "ru").lower()
    tmp_path = render_cabinet_card(
        CABINET_CARD_TEMPLATE,
        rank=rank,
        karma=karma,
        username=c.from_user.username,
        user_id=c.from_user.id,
        lang=lang,
    )

    # Текстовый дубль под карточкой
    tag = f"@{c.from_user.username}" if c.from_user.username else "—"
    caption = (
        f"{_T['btn_profile'][lang]}\n\n"
        f"<b>Место в топе:</b> {rank if rank else '—'}\n"
        f"<b>Карма:</b> {karma}\n"
        f"<b>Тег:</b> {tag}\n"
        f"<b>Айди:</b> <code>{c.from_user.id}</code>"
    )

    try:
        media = InputMediaPhoto(media=FSInputFile(tmp_path), caption=caption, parse_mode=ParseMode.HTML)
        await c.message.edit_media(media=media, reply_markup=_back_menu(lang))
    except Exception:
        await c.message.answer_photo(photo=FSInputFile(tmp_path), caption=caption,
                                     parse_mode=ParseMode.HTML, reply_markup=_back_menu(lang))
    finally:
        with contextlib.suppress(Exception):
            os.remove(tmp_path)
    with contextlib.suppress(TelegramBadRequest):
        await c.answer()


@router.callback_query(CabCB.filter(F.action == "back"))
async def cb_back(c: CallbackQuery, session_maker: async_sessionmaker[AsyncSession]) -> None:
    lang = (get_lang(c.from_user.id) or "ru").lower()
    async with session_maker() as s:
        repo = Repo(s)
        is_reg = await _is_registered_and_ensure_profile(repo, c.from_user.id, c.from_user.username)

    caption = _T["menu_user"][lang] if is_reg else _T["menu_guest"][lang]
    kb = _user_menu_kb(lang) if is_reg else _guest_menu_kb(lang)
    media = InputMediaPhoto(media=FSInputFile(AFTER_LANG_BANNER), caption=caption, parse_mode=ParseMode.HTML)
    try:
        await c.message.edit_media(media=media, reply_markup=kb)
    except Exception:
        await c.message.answer_photo(photo=FSInputFile(AFTER_LANG_BANNER), caption=caption,
                                     parse_mode=ParseMode.HTML, reply_markup=kb)
        with contextlib.suppress(Exception):
            await c.message.delete()
    with contextlib.suppress(TelegramBadRequest):
        await c.answer()
