from __future__ import annotations
"""
Админ-панель управления кармой.

Функции:
- /karma <user_id> — открыть панель
- Кнопки: +1/+5/+10 и −1/−5/−10, 🔄 Обновить, ✖ Закрыть
- /karma_add <user_id> <delta>
- /karma_set <user_id> <value>

Защита:
- Только для ADMIN_USER_IDS
- Без ошибки "message is not modified" при одинаковом тексте/клавиатуре
"""

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from bot.config import settings
from bot.utils.repo import Repo

router = Router(name="admin_karma")


# ----- helpers -----
def _is_admin(user_id: int) -> bool:
    return int(user_id) in set(getattr(settings, "ADMIN_USER_IDS", []) or [])


class AdminKarmaCB(CallbackData, prefix="adm_karma"):
    """
    action: open | delta | refresh | close
    value:  str(int) для delta (+1, -5, ...), либо user_id для open
    uid:    user_id, к которому применяется действие
    """
    action: str
    value: str | None = None
    uid: int | None = None


async def _panel_caption(session: AsyncSession, uid: int) -> str:
    repo = Repo(session)
    profile = await repo.get_profile(uid)
    karma = await repo.get_karma(uid)
    tag = f"@{getattr(profile, 'username', None)}" if (profile and getattr(profile, "username", None)) else f"id:{uid}"
    return (
        "🧩 <b>Админ: карма</b>\n\n"
        f"<b>User ID:</b> <code>{uid}</code>\n"
        f"<b>Тег:</b> {tag}\n"
        f"<b>Карма:</b> <b>{karma}</b>\n\n"
        "Выберите изменение:"
    )


def _panel_kb(uid: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="−10", callback_data=AdminKarmaCB(action="delta", value="-10", uid=uid).pack()),
        InlineKeyboardButton(text="−5",  callback_data=AdminKarmaCB(action="delta", value="-5",  uid=uid).pack()),
        InlineKeyboardButton(text="−1",  callback_data=AdminKarmaCB(action="delta", value="-1",  uid=uid).pack()),
        InlineKeyboardButton(text="+1",  callback_data=AdminKarmaCB(action="delta", value="+1",  uid=uid).pack()),
        InlineKeyboardButton(text="+5",  callback_data=AdminKarmaCB(action="delta", value="+5",  uid=uid).pack()),
        InlineKeyboardButton(text="+10", callback_data=AdminKarmaCB(action="delta", value="+10", uid=uid).pack()),
    )
    kb.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data=AdminKarmaCB(action="refresh", uid=uid).pack()),
        InlineKeyboardButton(text="✖ Закрыть",  callback_data=AdminKarmaCB(action="close",   uid=uid).pack()),
    )
    return kb.as_markup()


async def _safe_edit_text(message: Message, text: str, *, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Надёжное обновление текста, избегая BadRequest: message is not modified."""
    try:
        same_text = (message.text or "") == text
        if same_text:
            try:
                await message.edit_reply_markup(reply_markup=reply_markup)
            except TelegramBadRequest:
                pass
            return
        await message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        raise


async def _render_panel(message_or_cb: Message | CallbackQuery, uid: int,
                        session_maker: async_sessionmaker[AsyncSession], *, edit: bool = False) -> None:
    async with session_maker() as session:
        caption = await _panel_caption(session, uid)
        kb = _panel_kb(uid)

    if isinstance(message_or_cb, CallbackQuery):
        msg = message_or_cb.message
        if edit:
            await _safe_edit_text(msg, caption, reply_markup=kb)
        else:
            await msg.answer(caption, parse_mode=ParseMode.HTML, reply_markup=kb)
        try:
            await message_or_cb.answer()
        except Exception:
            pass
    else:
        await message_or_cb.answer(caption, parse_mode=ParseMode.HTML, reply_markup=kb)


# ----- handlers -----
@router.message(Command("karma"))
async def cmd_karma(message: Message, session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Открыть панель: /karma <user_id>"""
    if not _is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Формат: <code>/karma &lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        uid = int(parts[1])
    except Exception:
        await message.answer("user_id должен быть числом.")
        return
    await _render_panel(message, uid, session_maker, edit=False)


@router.callback_query(AdminKarmaCB.filter(F.action == "open"))
async def on_open(cb: CallbackQuery, callback_data: AdminKarmaCB,
                  session_maker: async_sessionmaker[AsyncSession]) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer("Недостаточно прав", show_alert=True)
        return
    uid = int((callback_data.uid or callback_data.value or 0))
    if uid <= 0:
        await cb.answer("Неверный user_id", show_alert=True)
        return
    await _render_panel(cb, uid, session_maker, edit=False)


@router.callback_query(AdminKarmaCB.filter(F.action == "delta"))
async def on_delta(cb: CallbackQuery, callback_data: AdminKarmaCB,
                   session_maker: async_sessionmaker[AsyncSession]) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer("Недостаточно прав", show_alert=True)
        return
    try:
        uid = int(callback_data.uid or 0)
        # на всякий случай нормализуем символ минуса
        delta = int((callback_data.value or "0").replace("−", "-"))
    except Exception:
        await cb.answer("Неверные параметры", show_alert=True)
        return

    async with session_maker() as session:
        repo = Repo(session)
        new_val = await repo.add_karma(uid, delta)

    try:
        await cb.answer(f"Δ {delta:+d} → {new_val}", show_alert=False)
    except Exception:
        pass

    await _render_panel(cb, uid, session_maker, edit=True)


@router.callback_query(AdminKarmaCB.filter(F.action == "refresh"))
async def on_refresh(cb: CallbackQuery, callback_data: AdminKarmaCB,
                     session_maker: async_sessionmaker[AsyncSession]) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer("Недостаточно прав", show_alert=True)
        return
    uid = int(callback_data.uid or 0)
    await _render_panel(cb, uid, session_maker, edit=True)


@router.callback_query(AdminKarmaCB.filter(F.action == "close"))
async def on_close(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer("Недостаточно прав", show_alert=True)
        return
    try:
        await cb.message.delete()
    except Exception:
        pass
    try:
        await cb.answer()
    except Exception:
        pass


# удобные команды
@router.message(Command("karma_add"))
async def cmd_karma_add(message: Message, session_maker: async_sessionmaker[AsyncSession]):
    # /karma_add <user_id> <delta>
    if not _is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    try:
        _, uid_s, delta_s = (message.text or "").split(maxsplit=2)
        uid = int(uid_s)
        delta = int(delta_s)
    except Exception:
        await message.answer("Формат: <code>/karma_add &lt;user_id&gt; &lt;delta&gt;</code>", parse_mode=ParseMode.HTML)
        return

    async with session_maker() as session:
        repo = Repo(session)
        new_val = await repo.add_karma(uid, delta)

    await message.answer(f"OK. Карма пользователя {uid}: <b>{new_val}</b> (Δ {delta:+d})",
                         parse_mode=ParseMode.HTML)
    # чтобы сразу было видно обновление — выведем (или переоткроем) панель
    await _render_panel(message, uid, session_maker, edit=False)


@router.message(Command("karma_set"))
async def cmd_karma_set(message: Message, session_maker: async_sessionmaker[AsyncSession]):
    # /karma_set <user_id> <value>
    if not _is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    try:
        _, uid_s, val_s = (message.text or "").split(maxsplit=2)
        uid = int(uid_s)
        value = int(val_s)
    except Exception:
        await message.answer("Формат: <code>/karma_set &lt;user_id&gt; &lt;value&gt;</code>", parse_mode=ParseMode.HTML)
        return

    async with session_maker() as session:
        repo = Repo(session)
        new_val = await repo.set_karma(uid, value)

    await message.answer(f"Установлено. Карма пользователя {uid}: <b>{new_val}</b>",
                         parse_mode=ParseMode.HTML)
    await _render_panel(message, uid, session_maker, edit=False)
