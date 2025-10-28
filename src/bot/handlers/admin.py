from __future__ import annotations
"""
Админская панель КЛС.

Доступ: только администраторам. Управление списком админов — только Главному админу.

Функционал:
- Просмотр реестра (roster) постранично по 20, лекс. по slug.
- Поиск по любому фрагменту slug, с возможностью редактировать/удалять.
- Ручное добавление в реестр (по slug).
- Удаление записи из реестра.
- Редактирование slug записи.
- Просмотр чёрного списка (по 20/стр).
- Управление администраторами (только главный): добавление/удаление, просмотр.

Команда входа: /admin
"""
import contextlib
from typing import Optional

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import text

from bot.config import settings
from bot.utils.repo import Repo
from bot.utils.parsing import parse_slug, normalize_slug

router = Router(name="admin_menu")

# Главный админ
MAIN_ADMIN_ID = 8421106062
# Размер страницы
PAGE_SIZE = 20

# Фильтр «не команда» — игнорируем всё, что начинается с «/»
NO_COMMAND = (~F.text.regexp(r"^\s*/")) & (~F.caption.regexp(r"^\s*/"))

class AdmCB(CallbackData, prefix="adm2"):
    """
    CallbackData для админского меню.

    action:
      - menu
      - roster_page (value = номер страницы, с 0)
      - roster_edit (value = id записи)
      - roster_del  (value = id записи)
      - roster_add  (value игнорируется) -> просим slug
      - search      (value игнорируется) -> просим запрос
      - search_page (value = номер страницы) (использует сохранённый state)
      - bl_page     (value = номер страницы) — чёрный список
      - admins      (только главный)
      - admin_add   -> просим user_id
      - admin_del   -> просим user_id
    """
    action: str
    value: Optional[str] = None


class AdminStates(StatesGroup):
    """FSM состояния админской панели."""
    waiting_roster_slug = State()
    waiting_search_query = State()
    waiting_edit_slug = State()  # контекст: roster_id
    waiting_admin_user_id = State()
    waiting_admin_del_user_id = State()


# -------------------- УТИЛИТЫ --------------------

async def _get_all_admin_ids(repo: Repo) -> set[int]:
    """
    Собрать множество админов: из настроек, из БД и главного админа.
    """
    ids = set(getattr(settings, "ADMIN_USER_IDS", []) or [])
    ids.add(MAIN_ADMIN_ID)
    for a in await repo.list_admins():
        ids.add(a.user_id)
    return ids


def _is_admin_cached(admin_ids: set[int], user_id: int) -> bool:
    """
    Быстрая проверка наличия прав админа по уже собранному множеству.
    """
    return (user_id in admin_ids) or (user_id == MAIN_ADMIN_ID)


def _menu_kb(can_manage_admins: bool) -> InlineKeyboardBuilder:
    """
    Клавиатура корневого меню (возвращаем BUILDER).
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="📚 Реестр (20/стр)", callback_data=AdmCB(action="roster_page", value="0").pack())
    kb.button(text="🔎 Поиск/правка", callback_data=AdmCB(action="search").pack())
    kb.button(text="➕ Добавить в реестр", callback_data=AdmCB(action="roster_add").pack())
    kb.button(text="🚫 Чёрный список", callback_data=AdmCB(action="bl_page", value="0").pack())
    if can_manage_admins:
        kb.button(text="👥 Администраторы", callback_data=AdmCB(action="admins").pack())
    kb.adjust(1)
    return kb


def _roster_nav_kb_builder(page: int, has_prev: bool, has_next: bool) -> InlineKeyboardBuilder:
    """
    Построитель навигации (возвращает BUILDER, а не markup).
    """
    kb = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    if has_prev:
        row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=AdmCB(action="roster_page", value=str(page - 1)).pack()))
    if has_next:
        row.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=AdmCB(action="roster_page", value=str(page + 1)).pack()))
    row.append(InlineKeyboardButton(text="🏠 Меню", callback_data=AdmCB(action="menu").pack()))
    kb.row(*row)
    return kb


def _bl_nav_kb_builder(page: int, has_prev: bool, has_next: bool) -> InlineKeyboardBuilder:
    """Навигация для чёрного списка."""
    kb = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    if has_prev:
        row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=AdmCB(action="bl_page", value=str(page - 1)).pack()))
    if has_next:
        row.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=AdmCB(action="bl_page", value=str(page + 1)).pack()))
    row.append(InlineKeyboardButton(text="🏠 Меню", callback_data=AdmCB(action="menu").pack()))
    kb.row(*row)
    return kb


def _admins_kb_builder() -> InlineKeyboardBuilder:
    """
    Клавиатура управления администраторами (BUILDER).
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить админа", callback_data=AdmCB(action="admin_add").pack())
    kb.button(text="🗑 Удалить админа", callback_data=AdmCB(action="admin_del").pack())
    kb.button(text="🏠 Меню", callback_data=AdmCB(action="menu").pack())
    kb.adjust(1)
    return kb


def _format_roster_line(n: int, slug: str) -> str:
    """
    Красиво форматируем строку реестра, если slug распарсился.
    """
    try:
        p = parse_slug(slug)
        return (f"{n}) <code>{slug}</code>\n"
                f"   first={p.first}, last={p.last}, uni={p.university}, prog={p.program}, "
                f"group={p.group}, course={p.course}, year={p.startyear}")
    except Exception:
        return f"{n}) <code>{slug}</code>"


def _format_roster_page(page: int, total: int, slugs: list[tuple[int, str]]) -> str:
    """
    Сформировать текст страницы реестра.
    """
    if not slugs:
        return "Пусто."
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    lines = [f"📚 Реестр — страница {page + 1}/{pages}\n"]
    for n, slug in slugs:
        lines.append(_format_roster_line(n, slug))
    return "\n".join(lines)


def _format_blacklist_page(page: int, total: int, rows: list) -> str:
    """Текст страницы чёрного списка."""
    if total == 0:
        return "🚫 Чёрный список пуст."
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    lines = [f"🚫 Чёрный список — страница {page + 1}/{pages}\n"]
    base_index = page * PAGE_SIZE
    for i, r in enumerate(rows, start=1):
        n = base_index + i
        reason = (r.reason or "—").strip()
        created = (r.created_at or "").strip()
        extra = f"  • added: {created}" if created else ""
        lines.append(f"{n}) <code>{r.user_id}</code> — {reason}{extra}")
    return "\n".join(lines)


async def _safe_edit_or_answer(msg: Message, *, text: str, kb: InlineKeyboardBuilder) -> Message:
    """
    Безопасно обновить контент: попытаться отредактировать сообщение бота,
    а если Telegram не разрешает — отправить новое.
    """
    try:
        await msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())
        return msg
    except TelegramBadRequest:
        new_msg = await msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())
        return new_msg


# -------------------- ОБРАБОТЧИКИ --------------------

@router.message(Command("admin"))
async def cmd_admin(message: Message, session_maker: async_sessionmaker[AsyncSession]) -> None:
    """
    Вход в админ-меню. Доступ только админам.
    """
    async with session_maker() as session:
        repo = Repo(session)
        admins = await _get_all_admin_ids(repo)
    if not _is_admin_cached(admins, message.from_user.id):
        await message.answer("Доступ запрещён.")
        return

    kb = _menu_kb(can_manage_admins=(message.from_user.id == MAIN_ADMIN_ID))
    await message.answer("Админская панель. Выберите действие:", reply_markup=kb.as_markup())


@router.callback_query(AdmCB.filter(F.action == "menu"))
async def cb_menu(cb: CallbackQuery, session_maker: async_sessionmaker[AsyncSession]) -> None:
    """
    Вернуться в корневое меню админки (проверка прав).
    """
    async with session_maker() as session:
        repo = Repo(session)
        admins = await _get_all_admin_ids(repo)
    if not _is_admin_cached(admins, cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return

    kb = _menu_kb(can_manage_admins=(cb.from_user.id == MAIN_ADMIN_ID))
    await cb.message.edit_text("Админская панель. Выберите действие:", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(AdmCB.filter(F.action == "roster_page"))
async def cb_roster_page(
    cb: CallbackQuery,
    callback_data: AdmCB,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Постраничный просмотр реестра (лексикографически по slug).
    """
    page = int(callback_data.value or 0)
    async with session_maker() as session:
        repo = Repo(session)
        admins = await _get_all_admin_ids(repo)
        if not _is_admin_cached(admins, cb.from_user.id):
            await cb.answer("Нет доступа", show_alert=True)
            return

        total = await repo.roster_count()
        rows = await repo.roster_page(page=page, page_size=PAGE_SIZE)

    base_index = page * PAGE_SIZE
    slugs = [(base_index + i + 1, r.slug) for i, r in enumerate(rows)]
    text = _format_roster_page(page, total, slugs)

    has_prev = page > 0
    has_next = (page + 1) * PAGE_SIZE < total

    # Клавиатура: под каждой записью компактные кнопки, плюс навигация.
    kb = InlineKeyboardBuilder()
    for r in rows:
        kb.row(
            InlineKeyboardButton(text="✏️", callback_data=AdmCB(action="roster_edit", value=str(r.id)).pack()),
            InlineKeyboardButton(text="🗑", callback_data=AdmCB(action="roster_del", value=str(r.id)).pack()),
            InlineKeyboardButton(text="·", callback_data="noop"),
        )

    # Навигация (BUILDER!) и прикрепляем к kb
    nav = _roster_nav_kb_builder(page, has_prev, has_next)
    kb.attach(nav)

    await cb.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(AdmCB.filter(F.action == "roster_add"))
async def cb_roster_add(cb: CallbackQuery, state: FSMContext, session_maker: async_sessionmaker[AsyncSession]) -> None:
    """
    Запросить у админа slug для ручного добавления.
    """
    async with session_maker() as session:
        repo = Repo(session)
        admins = await _get_all_admin_ids(repo)
    if not _is_admin_cached(admins, cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_roster_slug)
    await cb.message.edit_text(
        "Введите slug для добавления в реестр:\n"
        "<code>first-last-university-program-group-course-startyear</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=None,
    )
    await cb.answer()


@router.message(AdminStates.waiting_roster_slug, NO_COMMAND, (F.text | F.caption))
async def on_roster_slug(
    message: Message,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Принять slug и добавить в реестр (проверка формата).
    """
    async with session_maker() as session:
        repo = Repo(session)
        admins = await _get_all_admin_ids(repo)
    if not _is_admin_cached(admins, message.from_user.id):
        await state.clear()
        await message.answer("Нет доступа.")
        return

    raw = (message.text or "").strip()
    try:
        slug = normalize_slug(raw)
        parse_slug(slug)
    except Exception as e:
        await message.answer(f"Формат не принят: {e}\nПопробуйте ещё раз или /admin для выхода.")
        return

    async with session_maker() as session:
        repo = Repo(session)
        await repo.roster_add(slug)

    await state.clear()
    await message.answer("✅ Добавлено.\n\nНажмите /admin чтобы вернуться в меню.")


@router.callback_query(AdmCB.filter(F.action == "roster_edit"))
async def cb_roster_edit(
    cb: CallbackQuery,
    callback_data: AdmCB,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Запросить новый slug для выбранной записи.
    """
    async with session_maker() as session:
        repo = Repo(session)
        admins = await _get_all_admin_ids(repo)
    if not _is_admin_cached(admins, cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return

    rid = int(callback_data.value or 0)
    async with session_maker() as session:
        repo = Repo(session)
        row = await repo.roster_get(rid)
    if not row:
        await cb.answer("Запись не найдена", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_edit_slug)
    await state.update_data(roster_id=rid)
    await cb.message.edit_text(
        f"Текущий slug:\n<code>{row.slug}</code>\n\nОтправьте новый slug:",
        parse_mode=ParseMode.HTML,
    )
    await cb.answer()


@router.message(AdminStates.waiting_edit_slug, NO_COMMAND, (F.text | F.caption))
async def on_roster_edit_slug(
    message: Message,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Принять новый slug и сохранить.
    """
    async with session_maker() as session:
        repo = Repo(session)
        admins = await _get_all_admin_ids(repo)
    if not _is_admin_cached(admins, message.from_user.id):
        await state.clear()
        await message.answer("Нет доступа.")
        return

    data = await state.get_data()
    rid = int(data.get("roster_id") or 0)

    raw = (message.text or "").strip()
    try:
        slug = normalize_slug(raw)
        parse_slug(slug)
    except Exception as e:
        await message.answer(f"Формат не принят: {e}\nПопробуйте ещё раз.")
        return

    async with session_maker() as session:
        repo = Repo(session)
        await repo.roster_update_slug(rid, slug)

    await state.clear()
    await message.answer("✅ Изменено. /admin")


@router.callback_query(AdmCB.filter(F.action == "roster_del"))
async def cb_roster_del(
    cb: CallbackQuery,
    callback_data: AdmCB,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Удалить запись из реестра.
    """
    async with session_maker() as session:
        repo = Repo(session)
        admins = await _get_all_admin_ids(repo)
    if not _is_admin_cached(admins, cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return

    rid = int(callback_data.value or 0)
    async with session_maker() as session:
        repo = Repo(session)
        await repo.roster_delete(rid)
    await cb.answer("Удалено")
    await cb.message.answer("🗑 Удалено. /admin")


# -------------------- Поиск --------------------

@router.callback_query(AdmCB.filter(F.action == "search"))
async def cb_search(cb: CallbackQuery, state: FSMContext, session_maker: async_sessionmaker[AsyncSession]) -> None:
    """
    Запросить поисковую строку по slug (любой фрагмент).
    """
    async with session_maker() as session:
        repo = Repo(session)
        admins = await _get_all_admin_ids(repo)
    if not _is_admin_cached(admins, cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_search_query)
    await state.update_data(search_page=0)
    await cb.message.edit_text(
        "Введите поисковый запрос (фрагмент slug). Пример: <code>harward cse 77</code>",
        parse_mode=ParseMode.HTML,
    )
    await cb.answer()


async def _render_search_results(
    message: Message,
    query: str,
    page: int,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Отрисовать результаты поиска. Безопасно: если редактировать нельзя — отправим новое сообщение.
    """
    async with session_maker() as session:
        repo = Repo(session)
        total, rows = await repo.roster_search(query, page=page, page_size=PAGE_SIZE)

    base_index = page * PAGE_SIZE
    slugs = [(base_index + i + 1, r.slug) for i, r in enumerate(rows)]
    text = f"🔎 Результаты по запросу: <b>{query}</b>\n\n" + _format_roster_page(page, total, slugs)

    has_prev = page > 0
    has_next = (page + 1) * PAGE_SIZE < total

    kb = InlineKeyboardBuilder()
    for r in rows:
        kb.row(
            InlineKeyboardButton(text="✏️", callback_data=AdmCB(action="roster_edit", value=str(r.id)).pack()),
            InlineKeyboardButton(text="🗑", callback_data=AdmCB(action="roster_del", value=str(r.id)).pack()),
            InlineKeyboardButton(text="·", callback_data="noop"),
        )

    nav = InlineKeyboardBuilder()
    if has_prev:
        nav.button(text="⬅️ Назад", callback_data=AdmCB(action="search_page", value=str(page - 1)).pack())
    if has_next:
        nav.button(text="Вперёд ➡️", callback_data=AdmCB(action="search_page", value=str(page + 1)).pack())
    nav.button(text="🏠 Меню", callback_data=AdmCB(action="menu").pack())
    kb.attach(nav)

    await _safe_edit_or_answer(message, text=text, kb=kb)


@router.message(AdminStates.waiting_search_query, NO_COMMAND, (F.text | F.caption))
async def on_search_query(
    message: Message,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Принять строку поиска и показать первую страницу результатов.
    """
    async with session_maker() as session:
        repo = Repo(session)
        admins = await _get_all_admin_ids(repo)
    if not _is_admin_cached(admins, message.from_user.id):
        await state.clear()
        await message.answer("Нет доступа.")
        return

    q = (message.text or "").strip()
    if not q:
        await message.answer("Пустой запрос. Введите что-нибудь или /admin для выхода.")
        return
    await state.update_data(search_query=q, search_page=0)
    await _render_search_results(message, q, 0, session_maker)


@router.callback_query(AdmCB.filter(F.action == "search_page"))
async def cb_search_page(
    cb: CallbackQuery,
    state: FSMContext,
    callback_data: AdmCB,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Пагинация по результатам поиска.
    """
    async with session_maker() as session:
        repo = Repo(session)
        admins = await _get_all_admin_ids(repo)
    if not _is_admin_cached(admins, cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return

    data = await state.get_data()
    q = (data.get("search_query") or "").strip()
    page = int(callback_data.value or 0)
    await state.update_data(search_page=page)
    await _render_search_results(cb.message, q, page, session_maker)
    await cb.answer()


# -------------------- ЧЁРНЫЙ СПИСОК --------------------

@router.callback_query(AdmCB.filter(F.action == "bl_page"))
async def cb_blacklist_page(
    cb: CallbackQuery,
    callback_data: AdmCB,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Просмотр чёрного списка (по 20/стр).
    """
    page = int(callback_data.value or 0)
    async with session_maker() as session:
        repo = Repo(session)
        admins = await _get_all_admin_ids(repo)
        if not _is_admin_cached(admins, cb.from_user.id):
            await cb.answer("Нет доступа", show_alert=True)
            return

        total = await repo.blacklist_count()
        rows = await repo.blacklist_page(page=page, page_size=PAGE_SIZE)

    text = _format_blacklist_page(page, total, rows)
    has_prev = page > 0
    has_next = (page + 1) * PAGE_SIZE < total

    kb = _bl_nav_kb_builder(page, has_prev, has_next)
    await cb.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())
    await cb.answer()


# -------------------- Управление администраторами (только главный) --------------------

@router.callback_query(AdmCB.filter(F.action == "admins"))
async def cb_admins(
    cb: CallbackQuery,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Показать список админов и действия (только главный).
    """
    if cb.from_user.id != MAIN_ADMIN_ID:
        await cb.answer("Недостаточно прав", show_alert=True)
        return

    async with session_maker() as session:
        repo = Repo(session)
        rows = await repo.list_admins()

    static = set(getattr(settings, "ADMIN_USER_IDS", []) or [])
    static.add(MAIN_ADMIN_ID)
    db_ids = [r.user_id for r in rows]

    lines = ["👥 Администраторы:\n", f"— Главный: <code>{MAIN_ADMIN_ID}</code>"]
    statics = sorted(static - {MAIN_ADMIN_ID})
    if statics:
        lines.append("— Из настроек: " + ", ".join(f"<code>{i}</code>" for i in statics))
    if db_ids:
        lines.append("— Из БД: " + ", ".join(f"<code>{i}</code>" for i in sorted(db_ids)))
    text = "\n".join(lines)

    kb = _admins_kb_builder()
    await cb.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(AdmCB.filter(F.action == "admin_add"))
async def cb_admin_add(cb: CallbackQuery, state: FSMContext) -> None:
    """
    Запрос user_id для добавления админа (только главный).
    """
    if cb.from_user.id != MAIN_ADMIN_ID:
        await cb.answer("Недостаточно прав", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_admin_user_id)
    await cb.message.edit_text("Введите user_id для добавления в администраторы:", reply_markup=None)
    await cb.answer()


@router.message(AdminStates.waiting_admin_user_id, NO_COMMAND, (F.text | F.caption))
async def on_admin_add_user_id(
    message: Message,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Принять user_id и добавить в таблицу админов.
    """
    if message.from_user.id != MAIN_ADMIN_ID:
        await state.clear()
        await message.answer("Недостаточно прав.")
        return

    try:
        uid = int((message.text or "").strip())
    except ValueError:
        await message.answer("Ожидается целое число user_id. Попробуйте ещё раз.")
        return

    async with session_maker() as session:
        repo = Repo(session)
        await repo.add_admin(uid)

    await state.clear()
    await message.answer(f"✅ Пользователь {uid} добавлен в администраторы. /admin")


@router.callback_query(AdmCB.filter(F.action == "admin_del"))
async def cb_admin_del(cb: CallbackQuery, state: FSMContext) -> None:
    """
    Запрос user_id для удаления админа (только главный).
    """
    if cb.from_user.id != MAIN_ADMIN_ID:
        await cb.answer("Недостаточно прав", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_admin_del_user_id)
    await cb.message.edit_text("Введите user_id для удаления из администраторов:", reply_markup=None)
    await cb.answer()


@router.message(AdminStates.waiting_admin_del_user_id, NO_COMMAND, (F.text | F.caption))
async def on_admin_del_user_id(
    message: Message,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """
    Принять user_id и удалить из администраторов.
    """
    if message.from_user.id != MAIN_ADMIN_ID:
        await state.clear()
        await message.answer("Недостаточно прав.")
        return

    try:
        uid = int((message.text or "").strip())
    except ValueError:
        await message.answer("Ожидается целое число user_id. Попробуйте ещё раз.")
        return

    if uid == MAIN_ADMIN_ID:
        await message.answer("Нельзя удалить главного администратора.")
        return

    async with session_maker() as session:
        repo = Repo(session)
        await repo.remove_admin(uid)

    await state.clear()
    await message.answer(f"🗑 Пользователь {uid} удалён из администраторов. /admin")


# ---------- Команды во время админских состояний: сброс состояния + проброс /stats ----------

@router.message(
    AdminStates.waiting_roster_slug, F.text.regexp(r"^\s*/")
)
@router.message(
    AdminStates.waiting_search_query, F.text.regexp(r"^\s*/")
)
@router.message(
    AdminStates.waiting_edit_slug, F.text.regexp(r"^\s*/")
)
@router.message(
    AdminStates.waiting_admin_user_id, F.text.regexp(r"^\s*/")
)
@router.message(
    AdminStates.waiting_admin_del_user_id, F.text.regexp(r"^\s*/")
)
async def admin_states_any_command(
    message: Message,
    state: FSMContext,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    # Сбрасываем состояние, чтобы не «съедать» команды
    await state.clear()
    
    # Извлекаем команду из текста (первое слово без "/" и без "@bot_name")
    text = (message.text or "").strip()
    cmd = text.split()[0].lstrip("/").split("@")[0].lower() if text else ""

    if cmd == "stats":
        # Пробрасываем в хендлер кармы
        from bot.handlers.karma_auto import cmd_stats
        await cmd_stats(message, session_maker)  # type: ignore[arg-type]
        return

    # По другим командам просто сообщим, что ввод прерван
    await message.answer("⏹️ Ввод прерван. Команда обработана. Если не сработало — отправьте её ещё раз.")

async def _close_admin_request_message(cb: CallbackQuery, notice: str | None = None) -> None:
    """Спрятать карточку заявки в чате, где нажал админ."""
    deleted = False
    try:
        await cb.message.delete()
        deleted = True
    except Exception:
        pass

    if not deleted:
        with contextlib.suppress(Exception):
            if notice:
                await cb.message.edit_text(notice, reply_markup=None)
            else:
                await cb.message.edit_reply_markup(reply_markup=None)

    with contextlib.suppress(Exception):
        await cb.answer()

