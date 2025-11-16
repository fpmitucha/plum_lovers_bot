"""
Набор CallbackData и конструкторов простых клавиатур.
Держим все callback-схемы в одном месте, чтобы избежать циклических импортов.
"""

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData


class StartCB(CallbackData, prefix="start"):
    """
    CallbackData для стартового меню.
    action: "lang" | "info" | "back"
    value:  опциональный код языка ('ru'|'en')
    """

    action: str
    value: str | None = None


class JoinCB(CallbackData, prefix="join"):
    """CallbackData для вступления в клуб."""

    action: str  # "start" | "accept_rules"
    app_id: int | None = None


class AdminCB(CallbackData, prefix="adm"):
    """CallbackData для админских действий по заявке."""

    action: str  # "approve" | "deny"
    app_id: int


class CabCB(CallbackData, prefix="cab"):
    """CallbackData для личного кабинета."""

    action: str  # "open" | "back"


class SettingsCB(CallbackData, prefix="settings"):
    """CallbackData для настроек"""

    action: str
    value: str | None = None


def admin_review_kb(app_id: int) -> InlineKeyboardBuilder:
    """Клавиатура под карточкой заявки (Approve / Deny)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Approve", callback_data=AdminCB(action="approve", app_id=app_id).pack())
    kb.button(text="⛔️ Deny", callback_data=AdminCB(action="deny", app_id=app_id).pack())
    kb.adjust(2)
    return kb
