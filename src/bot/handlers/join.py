"""
Диалог «вступления в PLS» для пользователя.

Шаги:
1) «Вступить в PLS» — просим ввести slug в формате.
2) Валидируем slug.
3) Проверяем:
   - чёрный список,
   - уже в реестре (roster),
   - есть активный инвайт,
   - есть активная заявка.
4) Если всё чисто — создаём заявку, уведомляем админов.
5) Админ: Approve -> пользователю уходит карточка с правилами и баннером.
6) Админ: Deny -> админ вводит причину, пользователю уходит карточка отказа с причиной и баннером.
7) Пользователь жмёт «Принимаю правила» — создаём персональный инвайт (1 чел., 24ч)
   и отправляем карточку со ссылкой и баннером.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Union

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    CallbackQuery,
    ChatInviteLink,
    ChatMemberAdministrator,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.types.input_file import FSInputFile

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import settings
from bot.keyboards.common import AdminCB, JoinCB, admin_review_kb
from bot.services.i18n import get_lang
from bot.utils.parsing import normalize_slug, parse_slug
from bot.utils.repo import Repo, now_str

router = Router(name="join")

# ---- БАННЕРЫ ДЛЯ СООБЩЕНИЙ ПОЛЬЗОВАТЕЛЮ ----
APPROVE_BANNER = {
    "ru": "./data/pls_approve_ru_banner_600x400.png",
    "en": "./data/pls_approve_en_banner_600x400.png",
}
DENY_BANNER = {
    "ru": "./data/pls_deny_ru_banner_600x400.png",
    "en": "./data/pls_deny_en_banner_600x400.png",
}
LINK_BANNER = "./data/pls_link_banner_600x400.png"


# ---- FSM ----
class JoinStates(StatesGroup):
    """Состояния пользователя в процессе вступления."""
    waiting_slug = State()


class AdminStates(StatesGroup):
    """Состояния админа при отклонении заявки (ожидание причины)."""
    waiting_deny_reason = State()


# ---- УТИЛИТЫ ----
def _resolve_photo_source(src: str) -> Union[str, FSInputFile]:
    """
    Преобразовать путь/URL/file_id к виду, который понимает Telegram.

    :param src: локальный путь | http(s) URL | 'file_id:AAAA...'
    :return: str или FSInputFile
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

    # Вернём как есть — вдруг это корректный file_id без префикса
    return s


# ---- HANDLERS: USER FLOW ----
@router.callback_query(JoinCB.filter(F.action == "start"))
async def on_join_click(cb: CallbackQuery, state: FSMContext) -> None:
    """
    Нажатие «Вступить в PLS» из любых старых экранов.
    В новых экранах (стартовое меню) вы уже динамически меняете сообщение,
    но этот хэндлер оставляем на всякий случай: он просто переводит в ожидание slug.
    """
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
    Принять и проверить slug, выполнить блокирующие проверки и создать заявку.
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

    raw = (message.text or "").strip()
    try:
        normalized = normalize_slug(raw)
        parse_slug(normalized)
    except Exception as e:
        await message.answer(f"Формат не принят: {e}\nПопробуйте ещё раз.")
        return

    async with session_maker() as session:
        repo = Repo(session)

        # 1) Чёрный список
        if await repo.blacklist_contains(message.from_user.id):
            await state.clear()
            await message.answer(
                "❌ Ваш аккаунт находится в чёрном списке. Вступление невозможно.\n"
                "Если считаете это ошибкой — свяжитесь с администратором."
            )
            return

        # 2) Уже в реестре
        if await repo.roster_contains(normalized):
            await state.clear()
            await message.answer(
                "Вы уже числитесь в группе по нашей базе. Пожалуйста, пользуйтесь одним аккаунтом."
            )
            return

        # 3) Активная персональная ссылка уже есть
        if hasattr(repo, "get_active_invite"):
            active_inv = await repo.get_active_invite(message.from_user.id)
            if active_inv:
                await state.clear()
                await message.answer(
                    "У вас уже есть активная персональная ссылка на вступление. "
                    "Проверьте предыдущие сообщения — она всё ещё действительна."
                )
                return
        elif hasattr(repo, "has_active_invite") and await repo.has_active_invite(message.from_user.id):
            await state.clear()
            await message.answer(
                "У вас уже есть активная персональная ссылка на вступление. "
                "Проверьте предыдущие сообщения — она всё ещё действительна."
            )
            return

        # 4) Активная заявка
        if hasattr(repo, "has_active_application") and await repo.has_active_application(message.from_user.id):
            await state.clear()
            await message.answer("У вас уже есть активная заявка. Дождитесь решения администратора.")
            return

        # Создаём новую заявку
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
        # Сообщение пользователю: отправлено на рассмотрение
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
    Админ одобрил заявку — меняем статус и отправляем пользователю карточку с правилами + баннер.
    """
    app_id = int(callback_data.app_id or 0)
    async with session_maker() as session:
        repo = Repo(session)
        app = await repo.get_application(app_id)
        if not app:
            await cb.answer("Заявка не найдена.", show_alert=True)
            return

        await repo.set_application_status(app_id, status="approved")

    # Текст + баннер по языку пользователя
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

    try:
        await cb.bot.send_photo(
            chat_id=app.user_id,
            photo=_resolve_photo_source(APPROVE_BANNER[lang]),
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    except Exception:
        # Фолбэк без картинки
        await cb.bot.send_message(chat_id=app.user_id, text=caption, parse_mode=ParseMode.HTML, reply_markup=kb)

    await cb.answer("Отправлено пользователю.")


@router.callback_query(AdminCB.filter(F.action == "deny"))
async def on_admin_deny_click(
    cb: CallbackQuery,
    callback_data: AdminCB,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Старт отказа: просим администратора прислать причину одним сообщением.
    Сохраняем ID заявки в FSM.
    """
    app_id = int(callback_data.app_id or 0)

    # Убедимся, что заявка существует, чтобы не собирать причину впустую
    async with session_maker() as session:
        repo = Repo(session)
        app = await repo.get_application(app_id)
        if not app:
            await cb.answer("Заявка не найдена.", show_alert=True)
            return

    await state.set_state(AdminStates.waiting_deny_reason)
    await state.update_data(app_id=app_id)

    await cb.message.answer(
        "✋ Отказ по заявке.\n"
        "Пожалуйста, отправьте одним сообщением <b>причину отказа</b> для пользователя.\n"
        "Если хотите отправить без причины — пришлите дефис «-».",
        parse_mode=ParseMode.HTML,
    )
    await cb.answer()


@router.message(AdminStates.waiting_deny_reason)
async def on_admin_deny_reason(
    message: Message,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Приём причины отказа от администратора.
    Меняем статус заявки на 'rejected', уведомляем пользователя карточкой с баннером.
    """
    data = await state.get_data()
    app_id = int(data.get("app_id") or 0)
    reason_raw = (message.text or "").strip()

    # Нормализация причины: дефис/пусто -> None
    reason_to_save = None if reason_raw in {"", "-", "—"} else reason_raw

    async with session_maker() as session:
        repo = Repo(session)
        app = await repo.get_application(app_id)
        if not app:
            await message.answer("Заявка не найдена. Отмена.")
            await state.clear()
            return

        await repo.set_application_status(app_id, status="rejected", reason=reason_to_save)

        # Сообщение пользователю
        lang = get_lang(app.user_id) or "ru"
        caption = {
            "ru": (
                "Ваша заявка была отклонена администратором.\n\n"
                "<i>Причина:</i>\n{reason}"
            ),
            "en": (
                "Your application was rejected by an administrator.\n\n"
                "<i>Reason:</i>\n{reason}"
            ),
        }[lang].format(reason=html.escape(reason_raw) if reason_to_save else "—")

        try:
            await message.bot.send_photo(
                chat_id=app.user_id,
                photo=_resolve_photo_source(DENY_BANNER[lang]),
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            await message.bot.send_message(
                chat_id=app.user_id, text=caption, parse_mode=ParseMode.HTML
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
    Пользователь нажал «Принимаю правила».
    Проверяем права бота и создаём персональный инвайт (1 пользователь, 24 часа).
    После успешного создания отправляем карточку со ссылкой и баннером.
    """
    app_id = int(callback_data.app_id or 0)

    # Проверка статуса бота в целевом чате
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

        # Не выдаём новый инвайт, если уже есть активный
        if hasattr(repo, "has_active_invite") and await repo.has_active_invite(cb.from_user.id):
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

    # Карточка со ссылкой
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

    try:
        await cb.message.answer_photo(
            photo=_resolve_photo_source(LINK_BANNER),
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await cb.message.answer(caption, parse_mode=ParseMode.HTML)

    await cb.answer()
