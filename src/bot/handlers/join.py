from __future__ import annotations
"""
Диалог «вступления в PLS» с авто-завершением заявки, если пользователь уже в чате.

Дополнительно:
- Анти-дубликат slug (без падений, если метод в Repo отсутствует).
- ChatMemberStatus.CREATOR (вместо несуществующего OWNER).
- Отправка главного меню для авторизованного пользователя после фактического вступления
  (обработчик chat_member).
"""

import html
import logging
import contextlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Union

from aiogram import Router, F
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    CallbackQuery,
    ChatInviteLink,
    ChatMemberAdministrator,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.types.input_file import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import settings
from bot.keyboards.common import AdminCB, JoinCB, admin_review_kb, CabCB
from bot.services.i18n import get_lang
from bot.utils.parsing import normalize_slug, parse_slug
from bot.utils.repo import Repo

router = Router(name="join")

# ---- БАННЕРЫ ----
APPROVE_BANNER = {
    "ru": "./data/pls_approve_ru_banner_600x400.png",
    "en": "./data/pls_approve_en_banner_600x400.png",
}
DENY_BANNER = {
    "ru": "./data/pls_deny_ru_banner_600x400.png",
    "en": "./data/pls_deny_en_banner_600x400.png",
}
LINK_BANNER = "./data/pls_link_banner_600x400.png"
AFTER_LANG_BANNER = "./data/pls_afterchangelanguage_banner.png"

# ---- Тексты для меню, которое отправляем после вступления ----
_MENU_T = {
    "user_caption": {
        "ru": (
            "<b>Привет!</b>\n"
            "Ты в официальном боте <b>Клуба Любителей Сливов</b>. "
            "Здесь добро превращается в знания — делимся конспектами, разборами и поддержкой.\n\n"
            "Что выбираем сегодня? 👇"
        ),
        "en": (
            "<b>Hi!</b>\n"
            "You’re in the official bot of the <b>Plum Lovers Club</b>. "
            "Kindness turns into knowledge here — we share notes, breakdowns, and support.\n\n"
            "What shall we choose today? 👇"
        ),
    },
    "btn_profile":  {"ru": "👤 Личный кабинет", "en": "👤 Profile"},
    "btn_rules":    {"ru": "🧭 Правила",       "en": "🧭 Rules"},
    "btn_a2t":      {"ru": "🔊 Аудио в текст", "en": "🔊 Audio to text"},
    "btn_gpt":      {"ru": "⚡ Chat GPT 5",    "en": "⚡ Chat GPT 5"},
    "btn_help":     {"ru": "❓ Помощь",        "en": "❓ Help"},
    "btn_settings": {"ru": "⚙️ Настройки",     "en": "⚙️ Settings"},
}

def _user_menu_kb_join(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=_MENU_T["btn_profile"][lang],  callback_data=CabCB(action="open").pack())
    kb.button(text=_MENU_T["btn_rules"][lang],    callback_data=f"start:rules:{lang}")
    kb.button(text=_MENU_T["btn_a2t"][lang],      callback_data=f"start:a2t:{lang}")
    kb.button(text=_MENU_T["btn_gpt"][lang],      callback_data=f"start:gpt:{lang}")
    kb.button(text=_MENU_T["btn_help"][lang],     callback_data=f"start:help:{lang}")
    kb.button(text=_MENU_T["btn_settings"][lang], callback_data=f"start:settings:{lang}")
    kb.adjust(2, 2, 2)
    return kb.as_markup()

# ---- FSM ----
class JoinStates(StatesGroup):
    waiting_slug = State()

class AdminStates(StatesGroup):
    waiting_deny_reason = State()

# ---- УТИЛИТЫ ----
def _resolve_photo_source(src: str) -> Union[str, FSInputFile]:
    s = (src or "").strip().strip('"').strip("'")
    if not s:
        raise ValueError("Пустой путь к изображению")
    if s.startswith("file_id:"):
        return s.split("file_id:", 1)[1].strip()
    if s.startswith(("http://", "https://")):
        return s
    p = Path(s).expanduser()
    return FSInputFile(p) if p.exists() and p.is_file() else s

async def _is_already_in_target_chat(bot, user_id: int) -> bool:
    """True, если пользователь уже состоит в целевом чате."""
    try:
        cm = await bot.get_chat_member(settings.TARGET_CHAT_ID, user_id)
        return cm.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,  # важно: CREATOR, не OWNER
        }
    except TelegramBadRequest:
        return False
    except Exception:
        return False

async def _revoke_active_invite(bot, repo: Repo, user_id: int) -> None:
    """Отозвать активную персональную ссылку пользователя (если есть) и удалить запись из БД."""
    try:
        inv = await repo.get_active_invite(user_id)
    except Exception:
        inv = None
    if not inv:
        return
    try:
        await bot.revoke_chat_invite_link(settings.TARGET_CHAT_ID, inv.invite_link)
    except Exception:
        pass
    await repo.delete_invite(inv.id)

async def _close_admin_request_message(cb: CallbackQuery, notice: str | None = None) -> None:
    """
    Спрятать «карточку» заявки из админского чата:
    1) пробуем удалить сообщение;
    2) если нельзя — снимаем клавиатуру / меняем текст;
    3) закрываем «часики» на кнопке.
    """
    # 1) Удалить целиком
    with contextlib.suppress(Exception):
        await cb.message.delete()
        with contextlib.suppress(Exception):
            await cb.answer()
        return
    # 2) Иначе — убрать клавиатуру или заменить текст
    with contextlib.suppress(Exception):
        if notice:
            await cb.message.edit_text(notice, reply_markup=None)
        else:
            await cb.message.edit_reply_markup(reply_markup=None)
    # 3) Закрыть спиннер
    with contextlib.suppress(Exception):
        await cb.answer()

# ---- HANDLERS: USER FLOW ----
@router.callback_query(JoinCB.filter(F.action == "start"))
async def on_join_click(cb: CallbackQuery, state: FSMContext) -> None:
    """Переводим пользователя на ввод slug (из любой точки)."""
    if cb.message.chat.type != "private":
        me = await cb.bot.get_me()
        pm_url = f"https://t.me/{me.username}?start=join"
        await cb.answer("Откройте бота в личке, я продолжу там.", show_alert=True)
        await cb.message.answer(
            "Для продолжения нажмите кнопку:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Перейти в ЛС", url=pm_url)]]
            ),
        )
        return

    await state.set_state(JoinStates.waiting_slug)
    await cb.message.answer(
        "Введите ваши данные в формате (на английском):\n"
        "<b>first-last-university-program-group-course-startyear</b>\n\n"
        "Пример: <code>ivan-ivanov-Harward-CSE-77-3-21</code>",
        parse_mode=ParseMode.HTML,
    )
    await cb.answer()

@router.message(JoinStates.waiting_slug)
async def on_slug_received(
    message: Message,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Принимаем slug. Если пользователь уже в чате — заявка ставится в done, профиль/roster создаются,
    активная ссылка (если была) отзываетcя. Иначе — обычный поток (заявка pending).

    Новое: если введённый slug занят другим user_id, и этот владелец реально в чате —
    прерываем поток (анти-дубликат) — проверка безопасна даже если метода в Repo нет.
    """
    if message.chat.type != "private":
        me = await message.bot.get_me()
        pm_url = f"https://t.me/{me.username}?start=join"
        await message.answer(
            "Введите данные в личке с ботом:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Перейти в ЛС", url=pm_url)]]
            ),
        )
        return

    # нормализуем/валидируем slug
    raw = (message.text or "").strip()
    try:
        normalized = normalize_slug(raw)
        parse_slug(normalized)
    except Exception as e:
        await message.answer(f"Формат не принят: {e}\nПопробуйте ещё раз.")
        return

    # Проверяем членство текущего пользователя в чате
    already_member = await _is_already_in_target_chat(message.bot, message.from_user.id)

    async with session_maker() as session:
        repo = Repo(session)

        # --- анти-дубликат по slug (если репозиторий умеет искать профиль по slug) ---
        owner = None
        if hasattr(repo, "get_profile_by_slug"):
            try:
                owner = await repo.get_profile_by_slug(normalized)  # type: ignore[attr-defined]
            except Exception:
                owner = None
        if owner and int(getattr(owner, "user_id", 0)) != message.from_user.id:
            if await _is_already_in_target_chat(message.bot, int(owner.user_id)):  # type: ignore[arg-type]
                ui = (get_lang(message.from_user.id) or "ru").lower()
                msg = {
                    "ru": (
                        "Участник с такими данными уже состоит в чате КЛС.\n"
                        "Пожалуйста, используйте только один аккаунт.\n\n"
                        "Если это вы, просто откройте /menu — «Личный кабинет» доступен."
                    ),
                    "en": (
                        "A member with these details is already in the PLC chat.\n"
                        "Please use only one account.\n\n"
                        "If this is you, just open /menu — your Profile is available."
                    ),
                }[ui]
                await state.clear()
                await message.answer(msg)
                return

        # Чёрный список
        if await repo.blacklist_contains(message.from_user.id):
            await state.clear()
            await message.answer(
                "❌ Ваш аккаунт находится в чёрном списке. Вступление невозможно.\n"
                "Если считаете это ошибкой — свяжитесь с администратором."
            )
            return

        # Уже в чате → сразу done, профиль, roster, отзыв инвайта
        if already_member:
            app = await repo.add_application(
                user_id=message.from_user.id,
                username=message.from_user.username,
                slug=normalized,
            )
            await repo.set_application_status(app.id, status="done")
            await repo.ensure_profile(
                user_id=message.from_user.id,
                username=message.from_user.username,
                slug=normalized,
            )
            # Убеждаемся, что карма инициализирована правильно
            await repo._ensure_karma_column()
            karma = await repo.get_karma(message.from_user.id)
            if karma == 10:  # Если карма равна значению по умолчанию, значит все в порядке
                pass
            else:
                # Если карма не инициализирована, устанавливаем значение по умолчанию
                await repo.set_karma(message.from_user.id, 10)
            try:
                await repo.add_to_roster(normalized)
            except Exception:
                pass
            await _revoke_active_invite(message.bot, repo, message.from_user.id)

            await state.clear()
            lang = get_lang(message.from_user.id) or "ru"
            msg = {
                "ru": "Вы уже состоите в чате. Заявка отмечена выполненной ✅\nОткройте /menu — «Личный кабинет» доступен.",
                "en": "You are already in the chat. Your application has been marked done ✅\nOpen /menu — your Profile is available.",
            }[lang]
            await message.answer(msg)
            return

        # --- Обычный поток, если ещё не в чате ---
        if await repo.roster_contains(normalized):
            await state.clear()
            await message.answer(
                "По нашей базе вы уже числитесь в группе. Если это ошибка — напишите админу."
            )
            return

        if await repo.get_active_invite(message.from_user.id):
            await state.clear()
            await message.answer(
                "У вас уже есть активная персональная ссылка на вступление. "
                "Проверьте предыдущие сообщения — она всё ещё действительна."
            )
            return

        if await repo.has_active_application(message.from_user.id):
            await state.clear()
            await message.answer("У вас уже есть активная заявка. Дождитесь решения администратора.")
            return

        # Создаём новую заявку (pending) и уведомляем админов
        app = await repo.add_application(
            user_id=message.from_user.id,
            username=message.from_user.username,
            slug=normalized,
        )

        mention = f"@{message.from_user.username}" if message.from_user.username else f"id:{message.from_user.id}"
        text = (
            "📝 Новая заявка на вступление\n\n"
            f"<b>Slug:</b> <code>{html.escape(normalized)}</code>\n"
            f"<b>Пользователь:</b> <code>{html.escape(mention)}</code>\n"
            f"<b>Telegram ID:</b> <code>{message.from_user.id}</code>\n"
            f"<b>ID заявки:</b> <code>{app.id}</code>"
        )

        targets: list[int] = []
        admin_notify_chat_id = getattr(settings, "ADMIN_NOTIFY_CHAT_ID", None)
        if admin_notify_chat_id:
            targets.append(int(admin_notify_chat_id))
        targets.extend(settings.ADMIN_USER_IDS)

        for admin_id in targets:
            try:
                await message.bot.send_message(
                    chat_id=admin_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=admin_review_kb(app.id).as_markup(),
                )
            except Exception:
                logging.getLogger("innopls-bot").warning("Не удалось уведомить %s", admin_id)

        await state.clear()
        lang = get_lang(message.from_user.id) or "ru"
        ok_text = {
            "ru": "Ваша заявка отправлена на рассмотрение администратору ✅",
            "en": "Your application has been sent to the administrator for review ✅",
        }[lang]
        await message.answer(ok_text)

# ---- HANDLERS: ADMIN APPROVE/DENY ----
@router.callback_query(AdminCB.filter(F.action == "approve"))
async def on_admin_approved(
    cb: CallbackQuery,
    callback_data: AdminCB,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Если пользователь уже в чате — сразу ставим done, создаём профиль/roster,
    отзы́ваем активные ссылки и шлём ему уведомление без «правил».
    Иначе — обычный поток: статус approved и карточка с правилами.

    В любом случае текущая «карточка» заявки у администратора скрывается.
    """
    app_id = int(callback_data.app_id or 0)
    async with session_maker() as session:
        repo = Repo(session)
        app = await repo.get_application(app_id)
        if not app:
            await _close_admin_request_message(cb, "Заявка уже обработана или не найдена.")
            return

        # если уже не pending — просто закрыть карточку
        if (app.status or "").lower() != "pending":
            await _close_admin_request_message(cb)
            return

        already_member = await _is_already_in_target_chat(cb.bot, app.user_id)

        if already_member:
            await repo.set_application_status(app_id, status="done")
            await repo.ensure_profile(user_id=app.user_id, username=app.username, slug=app.slug)
            # Убеждаемся, что карма инициализирована правильно
            await repo._ensure_karma_column()
            karma = await repo.get_karma(app.user_id)
            if karma != 10:  # Если карма не равна значению по умолчанию
                await repo.set_karma(app.user_id, 10)
            with contextlib.suppress(Exception):
                await repo.add_to_roster(app.slug)
            await _revoke_active_invite(cb.bot, repo, app.user_id)

            # уведомим пользователя
            lang = get_lang(app.user_id) or "ru"
            msg = {
                "ru": "Заявка отмечена выполненной: вы уже состоите в чате ✅\nОткройте /menu — «Личный кабинет» доступен.",
                "en": "Your application has been marked done: you are already in the chat ✅\nOpen /menu — your Profile is available.",
            }[lang]
            with contextlib.suppress(Exception):
                await cb.bot.send_message(chat_id=app.user_id, text=msg)

            await _close_admin_request_message(cb)
            return

        # ---- обычный approve ----
        await repo.set_application_status(app_id, status="approved")

    lang = get_lang(app.user_id) or "ru"
    caption = {
        "ru": (
            "✅ Ваша заявка одобрена администратором.\n\n"
            f"Прежде чем вступить, ознакомьтесь со сводом правил:\n{html.escape(settings.RULES_URL)}\n\n"
            "<b><u>Вступайте только с этого аккаунта, в который бот отправил ссылку, иначе будете заблокированы в беседе.</u></b>\n\n"
            "Нажмите кнопку ниже, если принимаете правила.\n\n\n\n"
            "<i>Принимая правила, вы разрешаете боту отправлять сообщения рекламного характера</i>"
        ),
        "en": (
            "✅ Your application has been approved.\n\n"
            f"Before joining, please read our rules:\n{html.escape(settings.RULES_URL)}\n\n"
            "<b><u>Join only from this account that received the link, otherwise you will be blocked in the chat.</u></b>\n\n"
            "Press the button below if you accept the rules.\n\n\n\n"
            "<i>By accepting the rules, you allow the bot to send advertising messages</i>"
        ),
    }[lang]

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text={"ru": "Принимаю правила", "en": "I accept the rules"}[lang],
                callback_data=JoinCB(action="accept_rules", app_id=str(app_id)).pack(),
            )
        ]]
    )

    with contextlib.suppress(Exception):
        await cb.bot.send_photo(
            chat_id=app.user_id,
            photo=_resolve_photo_source(APPROVE_BANNER[lang]),
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )

    # скрываем карточку у нажавшего админа
    await _close_admin_request_message(cb)

@router.callback_query(AdminCB.filter(F.action == "deny"))
async def on_admin_deny_click(
    cb: CallbackQuery,
    callback_data: AdminCB,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Отказ по заявке: карточка сразу скрывается у админа, затем спрашиваем причину.
    """
    app_id = int(callback_data.app_id or 0)
    async with session_maker() as session:
        repo = Repo(session)
        app = await repo.get_application(app_id)
        if not app:
            await _close_admin_request_message(cb, "Заявка уже обработана или не найдена.")
            return
        # если уже не pending — просто закрыть карточку
        if (app.status or "").lower() != "pending":
            await _close_admin_request_message(cb)
            return

    # прячем карточку сразу
    await _close_admin_request_message(cb)

    await state.set_state(AdminStates.waiting_deny_reason)
    await state.update_data(app_id=app_id)
    await cb.message.answer(
        "✋ Отказ по заявке.\n"
        "Пожалуйста, отправьте одним сообщением <b>причину отказа</b> для пользователя.\n"
        "Если хотите отправить без причины — пришлите дефис «-».",
        parse_mode=ParseMode.HTML,
    )

@router.message(AdminStates.waiting_deny_reason)
async def on_admin_deny_reason(
    message: Message,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    data = await state.get_data()
    app_id = int(data.get("app_id") or 0)
    reason_raw = (message.text or "").strip()
    reason_to_save = None if reason_raw in {"", "-", "—"} else reason_raw

    async with session_maker() as session:
        repo = Repo(session)
        app = await repo.get_application(app_id)
        if not app:
            await message.answer("Заявка не найдена. Отмена.")
            await state.clear()
            return

        await repo.set_application_status(app_id, status="rejected", reason=reason_to_save)

        lang = get_lang(app.user_id) or "ru"
        caption = {
            "ru": "Ваша заявка была отклонена администратором.\n\n<i>Причина:</i>\n{reason}",
            "en": "Your application was rejected by an administrator.\n\n<i>Reason:</i>\n{reason}",
        }[lang].format(reason=html.escape(reason_raw) if reason_to_save else "—")

        with contextlib.suppress(Exception):
            await message.bot.send_photo(
                chat_id=app.user_id,
                photo=_resolve_photo_source(DENY_BANNER[lang]),
                caption=caption,
                parse_mode=ParseMode.HTML,
            )

    await state.clear()
    await message.answer("Отправлено пользователю ✅")

# ---- HANDLERS: USER ACCEPT RULES ----
@router.callback_query(JoinCB.filter(F.action == "accept_rules"))
async def on_rules_accepted(
    cb: CallbackQuery,
    callback_data: JoinCB,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Если пользователь уже состоит в чате — помечаем заявку как done,
    создаём профиль/roster, отзы́ваем активную ссылку и не создаём новую.
    Иначе — обычная выдача персональной ссылки.
    """
    app_id = int(callback_data.app_id or 0)

    # статус бота в чате (как раньше)
    try:
        me = await cb.bot.get_me()
        cm = await cb.bot.get_chat_member(settings.TARGET_CHAT_ID, me.id)
    except TelegramBadRequest:
        await cb.message.answer("❌ Не вижу целевой чат. Проверьте TARGET_CHAT_ID и что бот добавлен в чат.")
        await cb.answer()
        return

    if cm.status != "administrator":
        await cb.message.answer("❌ Бот не администратор в целевом чате. Выдайте право «Приглашать по ссылке».")
        await cb.answer()
        return
    if isinstance(cm, ChatMemberAdministrator):
        if hasattr(cm, "can_invite_users") and not cm.can_invite_users:
            await cb.message.answer("❌ У бота нет права «Приглашать по ссылке». Включите и повторите.")
            await cb.answer()
            return

    async with session_maker() as session:
        repo = Repo(session)
        app = await repo.get_application(app_id)
        if not app or app.user_id != cb.from_user.id:
            await cb.answer("Заявка не найдена или не принадлежит вам.", show_alert=True)
            return

        # Уже в чате? -> done, без ссылки
        if await _is_already_in_target_chat(cb.bot, app.user_id):
            await repo.set_application_status(app_id, status="done")
            await repo.ensure_profile(user_id=app.user_id, username=app.username, slug=app.slug)
            # Убеждаемся, что карма инициализирована правильно
            await repo._ensure_karma_column()
            karma = await repo.get_karma(app.user_id)
            if karma != 10:  # Если карма не равна значению по умолчанию
                await repo.set_karma(app.user_id, 10)
            with contextlib.suppress(Exception):
                await repo.add_to_roster(app.slug)
            await _revoke_active_invite(cb.bot, repo, app.user_id)

            lang = get_lang(app.user_id) or "ru"
            msg = {
                "ru": "Вы уже состоите в чате — заявка отмечена выполненной ✅\nОткройте /menu.",
                "en": "You are already in the chat — application marked done ✅\nOpen /menu.",
            }[lang]
            await cb.message.answer(msg)
            await cb.answer()
            return

        # обычная логика: задаём персональную ссылку
        if await repo.has_active_invite(cb.from_user.id):
            await cb.message.answer("У вас уже есть активная персональная ссылка. Проверьте предыдущие сообщения.")
            await cb.answer()
            return

        expire_dt = datetime.now(timezone.utc) + timedelta(hours=24)
        try:
            link: ChatInviteLink = await cb.bot.create_chat_invite_link(
                chat_id=settings.TARGET_CHAT_ID,
                name=f"PLS for {cb.from_user.id}",
                member_limit=1,
                expire_date=expire_dt,
                creates_join_request=False,
            )
        except TelegramBadRequest as e:
            hint = "Проверьте права бота на управление ссылками и корректность TARGET_CHAT_ID."
            await cb.message.answer(f"❌ Не удалось создать пригласительную ссылку.\n{e}\n\n{hint}")
            await cb.answer()
            return

        await repo.add_invite(
            user_id=cb.from_user.id,
            chat_id=settings.TARGET_CHAT_ID,
            invite_link=link.invite_link,
            expires_at=expire_dt.strftime("%Y-%m-%d %H:%M:%S"),
        )
        await repo.set_application_status(app_id, status="done")

    # карточка со ссылкой
    lang = get_lang(cb.from_user.id) or "ru"
    caption = {
        "ru": (
            "Отлично! Вот ваша персональная ссылка-приглашение "
            "(действует 24 часа и только для вас):\n"
            f"{html.escape(link.invite_link)}\n\n"
            "После вступления проверка произойдёт автоматически."
        ),
        "en": (
            "Great! Here is your personal invite link "
            "(valid for 24 hours and only for you):\n"
            f"{html.escape(link.invite_link)}\n\n"
            "After joining, verification will happen automatically."
        ),
    }[lang]

    with contextlib.suppress(Exception):
        await cb.message.answer_photo(
            photo=_resolve_photo_source(LINK_BANNER),
            caption=caption,
            parse_mode=ParseMode.HTML,
        )

    await cb.answer()

# ---- СЛУШАЕМ ФАКТИЧЕСКОЕ ВСТУПЛЕНИЕ В ЧАТ ----
@router.chat_member()
async def on_member_joined_target_chat(
    ev: ChatMemberUpdated,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Когда пользователь реально вступил в целевой чат — шлём ему главное меню (user)."""
    # интересует только целевой чат
    if int(ev.chat.id) != int(settings.TARGET_CHAT_ID):
        return

    user = ev.new_chat_member.user
    if user.is_bot:
        return

    new_status = ev.new_chat_member.status
    if new_status not in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
        return  # не событие «вступил»

    # гарантируем профиль и подтягиваем slug из последней заявки (если была)
    async with session_maker() as s:
        repo = Repo(s)
        last_app = await repo.get_last_application_for_user(user.id)
        slug = getattr(last_app, "slug", None) if last_app else None
        await repo.ensure_profile(user_id=user.id, username=user.username, slug=slug)
        # Убеждаемся, что карма инициализирована правильно
        await repo._ensure_karma_column()
        karma = await repo.get_karma(user.id)
        if karma != 10:  # Если карма не равна значению по умолчанию
            await repo.set_karma(user.id, 10)

    lang = (get_lang(user.id) or "ru").lower()
    with contextlib.suppress(TelegramBadRequest):
        await ev.bot.send_photo(
            chat_id=user.id,
            photo=_resolve_photo_source(AFTER_LANG_BANNER),
            caption=_MENU_T["user_caption"]["en" if lang == "en" else "ru"],
            parse_mode=ParseMode.HTML,
            reply_markup=_user_menu_kb_join("en" if lang == "en" else "ru"),
        )
