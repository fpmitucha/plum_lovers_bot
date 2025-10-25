"""
Набор конструкторов инлайн-клавиатур.

Сосредоточивает callback_data и визуальные элементы в одном месте.
"""

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData


class JoinCB(CallbackData, prefix="join"):
    """
    CallbackData для вступления.
    """
    action: str  # "start" | "accept_rules"
    app_id: int | None = None


class AdminCB(CallbackData, prefix="adm"):
    """
    CallbackData для действий администратора по заявке.
    """
    action: str  # "approve" | "deny"
    app_id: int


def start_menu_kb() -> InlineKeyboardBuilder:
    """
    Клавиатура главного экрана с кнопкой «Вступить в PLS».

    :return: Builder с одной кнопкой.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="Вступить в PLS", callback_data=JoinCB(action="start").pack())
    kb.adjust(1)
    return kb


def rules_accept_kb(app_id: int) -> InlineKeyboardBuilder:
    """
    Клавиатура под правилами с кнопкой «Принимаю правила».

    :param app_id: идентификатор заявки, чтобы связать ответ.
    :return: Builder.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="Принимаю правила", callback_data=JoinCB(action="accept_rules", app_id=app_id).pack())
    kb.adjust(1)
    return kb


def admin_review_kb(app_id: int) -> InlineKeyboardBuilder:
    """
    Клавиатура для админа под заявкой: Approve / Deny.

    :param app_id: идентификатор заявки.
    :return: Builder.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Approve", callback_data=AdminCB(action="approve", app_id=app_id).pack())
    kb.button(text="⛔️ Deny", callback_data=AdminCB(action="deny", app_id=app_id).pack())
    kb.adjust(2)
    return kb
