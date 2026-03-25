from __future__ import annotations

"""
Старт и основная навигация + A2T с прогрессом и логированием.
"""

import contextlib
import tempfile
import os
import subprocess
import wave
import audioop
import time
from pathlib import Path
from typing import Optional, Union, Tuple

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup
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
from aiogram.exceptions import TelegramBadRequest

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy import text as sql_text

from bot.config import settings
from bot.keyboards.common import JoinCB, CabCB, SettingsCB
from bot.services.i18n import set_lang, get_lang
from bot.utils.repo import Repo, now_str

router = Router(name="start")

START_BANNER = "./data/pls_start_banner_600x400.png"
AFTER_LANG_BANNER = "./data/pls_afterchangelanguage_banner.png"
JOIN_BANNER = {
    "ru": "./data/pls_join_ru_banner_600x400.png",
    "en": "./data/pls_join_en_banner_600x400.png",
}
INFO_BANNER = "./data/pls_info_banner_600x400.png"
RULES_BANNER = {"ru": "./data/pls_rules_ru_600x400.png", "en": "./data/pls_rules_en_600x400.png"}
HELP_BANNER = "./data/pls_help_600x400.png"
A2T_BANNER = "./data/pls_a2t_600x400.png"
GPT_BANNER = "./data/pls_with_gpt_600x400.png"
SET_BANNER = "./data/pls_settings_600x400.png"


class A2TStates(StatesGroup):
    choose_lang = State()
    wait_audio = State()


class StartCB(CallbackData, prefix="start"):
    """
    action:
      lang, info, back,
      rules, help, a2t, a2t_lang, gpt, settings
    value: опционально – язык ('ru'|'en'|'auto') или lang для back
    """

    action: str
    value: Optional[str] = None


_T = {
    "greet": {
        "ru": (
            "Приветствуем в официальном боте <b>Клуба Любителей Слив</b> — "
            "места, где добро превращается в знания.\n\n"
            "Чтобы продолжить, выберите язык интерфейса:"
        ),
        "en": (
            "Welcome to the official bot of the <b>Plum Lovers Club</b> — "
            "a place where kindness turns into knowledge.\n\n"
            "Choose your interface language:"
        ),
    },
    "menu_guest": {
        "ru": (
            "<b>Привет!</b>\n"
            "Ты в официальном боте <b>Клуба Любителей Сливов</b>. "
            "Здесь добро превращается в знания — делимся конспектами, разборами и поддержкой.\n\n"
            "Что выбираем сегодня? 👇\n"
        ),
        "en": (
            "<b>Hi!</b>\n"
            "You’re in the official bot of the <b>Plum Lovers Club</b>. "
            "Kindness turns into knowledge here — we share notes, breakdowns, and support.\n\n"
            "What shall we choose today? 👇\n"
        ),
    },
    "menu_user": {
        "ru": (
            "<b>Привет!</b>\n"
            "Ты в официальном боте <b>Клуба Любителей Сливов</b>. "
            "Здесь добро превращается в знания — делимся конспектами, разборами и поддержкой.\n\n"
            "Что выбираем сегодня? 👇\n"
        ),
        "en": (
            "<b>Hi!</b>\n"
            "You’re in the official bot of the <b>Plum Lovers Club</b>. "
            "Kindness turns into knowledge here — we share notes, breakdowns, and support.\n\n"
            "What shall we choose today? 👇\n"
        ),
    },
    "guest_hint": {
        "ru": "\n<i>Подсказка: если ты впервые здесь — начни с 🧭 Правила.\nМы не пираты — мы архивисты энтузиазма.</i>",
        "en": "\n<i>Tip: if you’re new here — start with 🧭 Rules.\nWe’re not pirates — we’re archivists of enthusiasm.</i>",
    },
    "btn_rules": {"ru": "🧭 Правила", "en": "🧭 Rules"},
    "btn_help": {"ru": "❓ Помощь", "en": "❓ Help"},
    "btn_join": {"ru": "👉 Вступить в КЛС", "en": "👉 Join the club"},
    "btn_info": {"ru": "📗 КЛС инфо", "en": "📗 Club info"},
    "btn_profile": {"ru": "👤 Личный кабинет", "en": "👤 Profile"},
    "btn_a2t": {"ru": "🔊 Аудио в текст", "en": "🔊 Audio to text"},
    "btn_gpt": {"ru": "⚡ Chat GPT 5", "en": "⚡ Chat GPT 5"},
    "btn_settings": {"ru": "⚙️ Настройки", "en": "⚙️ Settings"},
    "btn_back": {"ru": "⬅️ Назад", "en": "⬅️ Back"},
    "btn_features": {"ru": "🗂 Функции", "en": "🗂 Features"},
    "btn_link_platform": {"ru": "🔗 Подключить платформу", "en": "🔗 Connect platform"},
    # Помощь гостям
    "help_text": {
        "ru": (
            "<b>Нужна регистрация</b>\n"
            "Чтобы открыть полный доступ к функционалу бота (материалы, задания, статистика и сохранённые), "
            "пройди короткую регистрацию. Это нужно, чтобы подтвердить участника КЛС и сохранить твой прогресс."
        ),
        "en": (
            "<b>Registration required</b>\n"
            "To unlock the full functionality (materials, tasks, stats and saved items), please complete a short "
            "registration. This confirms your PLC membership and saves your progress."
        ),
    },
    "btn_help_join": {"ru": "✅ Вступить в клуб", "en": "✅ Join the club"},
    # A2T
    "a2t_prompt": {
        "ru": "Выбери язык аудио, затем отправь файл:",
        "en": "Choose the audio language, then send a file:",
    },
    "a2t_ru": {"ru": "🇷🇺 Русский", "en": "🇷🇺 Russian"},
    "a2t_en": {"ru": "🇬🇧 Английский", "en": "🇬🇧 English"},
    "a2t_auto": {"ru": "🌐 Авто", "en": "🌐 Auto"},
    "a2t_send_audio": {
        "ru": "Отправь аудио-файл или голосовое сообщением одним сообщением.",
        "en": "Send an audio file or a voice message in one message.",
    },
    "a2t_done_title": {
        "ru": "<b><i>Проведена транскрибация аудио в текст (@plum_lovers_bot):</i></b>\n",
        "en": "<b><i>Audio transcribed to text (@plum_lovers_bot):</i></b>\n",
    },
}


def _resolve_photo_source(src: str) -> Union[str, FSInputFile]:
    s = (src or "").strip().strip('"').strip("'")
    if s.startswith("file_id:"):
        return s.split("file_id:", 1)[1].strip()
    if s.startswith(("http://", "https://")):
        return s
    p = Path(s).expanduser()
    if p.exists() and p.is_file():
        return FSInputFile(p)
    return s


# --- универсальный фолбэк при отсутствии баннеров/ошибке Telegram ---
async def _answer_photo_or_text(
    message: Message, media: InputMediaPhoto, reply_markup: Optional[InlineKeyboardMarkup]
) -> None:
    """
    Пытаемся отправить фото. Если файла нет или Telegram не принимает — отправляем просто текст.
    """
    try:
        await message.answer_photo(
            media.media,
            caption=media.caption,
            parse_mode=media.parse_mode,
            reply_markup=reply_markup,
        )
    except Exception:
        caption = media.caption or ""
        await message.answer(
            caption, parse_mode=media.parse_mode or ParseMode.HTML, reply_markup=reply_markup
        )


async def _is_registered_and_ensure_profile(
    repo: Repo, user_id: int, username: Optional[str]
) -> bool:
    if await repo.profile_exists(user_id):
        return True
    app = await repo.get_last_application_for_user(user_id)
    if app and (app.status or "").lower() == "done":
        await repo.ensure_profile(
            user_id=user_id, username=username, slug=getattr(app, "slug", None)
        )
        return True
    return False


async def _flags_for_menu(
    session_maker: async_sessionmaker[AsyncSession], user_id: int, username: Optional[str]
) -> tuple[bool, bool]:
    async with session_maker() as s:
        repo = Repo(s)
        is_reg = await _is_registered_and_ensure_profile(repo, user_id, username)
    return (not is_reg, is_reg)


def _lang_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Русский 🇷🇺", callback_data=StartCB(action="lang", value="ru").pack())
    kb.button(text="English 🇬🇧", callback_data=StartCB(action="lang", value="en").pack())
    kb.adjust(2)
    return kb.as_markup()


def _guest_menu_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=_T["btn_rules"][lang], callback_data=StartCB(action="rules", value=lang).pack())
    kb.button(text=_T["btn_help"][lang], callback_data=StartCB(action="help", value=lang).pack())
    kb.button(text=_T["btn_join"][lang], callback_data=JoinCB(action="start").pack())
    kb.button(text=_T["btn_info"][lang], callback_data=StartCB(action="info", value=lang).pack())
    kb.adjust(2, 2)
    return kb.as_markup()


def _user_menu_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=_T["btn_profile"][lang], callback_data=CabCB(action="open").pack())
    kb.button(text=_T["btn_rules"][lang], callback_data=StartCB(action="rules", value=lang).pack())
    kb.button(text=_T["btn_features"][lang], callback_data=StartCB(action="features", value=lang).pack())
    kb.button(text=_T["btn_help"][lang], callback_data=StartCB(action="help", value=lang).pack())
    kb.button(text=_T["btn_link_platform"][lang], callback_data=StartCB(action="link_platform", value=lang).pack())
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def _features_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=_T["btn_a2t"][lang], callback_data=StartCB(action="a2t", value=lang).pack())
    kb.button(text=_T["btn_gpt"][lang], callback_data=StartCB(action="gpt", value=lang).pack())
    kb.button(text=_T["btn_settings"][lang], callback_data=SettingsCB(action="open", value=lang).pack())
    kb.button(text=_T["btn_back"][lang], callback_data=StartCB(action="back", value=lang).pack())
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def _back_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_T["btn_back"][lang],
                    callback_data=StartCB(action="back", value=lang).pack(),
                )
            ]
        ]
    )


def _help_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=_T["btn_help_join"][lang], callback_data=JoinCB(action="start").pack())
    kb.button(text=_T["btn_back"][lang], callback_data=StartCB(action="back", value=lang).pack())
    kb.adjust(1, 1)
    return kb.as_markup()


def _a2t_lang_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=_T["a2t_ru"][lang], callback_data=StartCB(action="a2t_lang", value="ru").pack())
    kb.button(text=_T["a2t_en"][lang], callback_data=StartCB(action="a2t_lang", value="en").pack())
    kb.button(
        text=_T["a2t_auto"][lang], callback_data=StartCB(action="a2t_lang", value="auto").pack()
    )
    kb.button(text=_T["btn_back"][lang], callback_data=StartCB(action="back", value=lang).pack())
    kb.adjust(3, 1)
    return kb.as_markup()


def _render_guest_menu(lang: str) -> tuple[InputMediaPhoto, InlineKeyboardMarkup]:
    media = InputMediaPhoto(
        media=_resolve_photo_source(AFTER_LANG_BANNER),
        caption=_T["menu_guest"][lang] + _T["guest_hint"][lang],
        parse_mode=ParseMode.HTML,
    )
    return media, _guest_menu_kb(lang)


def _render_user_menu(lang: str) -> tuple[InputMediaPhoto, InlineKeyboardMarkup]:
    media = InputMediaPhoto(
        media=_resolve_photo_source(AFTER_LANG_BANNER),
        caption=_T["menu_user"][lang],
        parse_mode=ParseMode.HTML,
    )
    return media, _user_menu_kb(lang)


def _have_exe(name: str) -> bool:
    from shutil import which

    return which(name) is not None


def _ffmpeg_convert_to_wav(src_path: str, dst_path: str, *, rate: int = 16000) -> bool:
    if not _have_exe("ffmpeg"):
        return False
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            src_path,
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-acodec",
            "pcm_s16le",
            dst_path,
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return os.path.exists(dst_path) and os.path.getsize(dst_path) > 44
    except Exception:
        return False


def _rms_is_silent(wav_path: str) -> bool:
    try:
        with wave.open(wav_path, "rb") as wf:
            raw = wf.readframes(wf.getnframes())
            return audioop.rms(raw, wf.getsampwidth()) < 150
    except Exception:
        return False


async def _a2t_db_ensure(s: AsyncSession) -> None:
    await s.execute(
        sql_text("""
        CREATE TABLE IF NOT EXISTS a2t_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            lang TEXT,
            status TEXT,
            backend TEXT,
            file_path TEXT,
            audio_seconds REAL,
            created_at TEXT,
            finished_at TEXT,
            duration_ms INTEGER,
            text_len INTEGER,
            error TEXT
        )
    """)
    )
    await s.commit()


async def _a2t_db_insert(s: AsyncSession, *, user_id: int, lang: str, file_path: str) -> int:
    await _a2t_db_ensure(s)
    await s.execute(
        sql_text("""
        INSERT INTO a2t_jobs (user_id, lang, status, file_path, created_at)
        VALUES (:uid, :lang, 'downloaded', :path, :ts)
    """),
        {"uid": user_id, "lang": lang, "path": file_path, "ts": now_str()},
    )
    rid = await s.execute(sql_text("SELECT last_insert_rowid()"))
    job_id = int(rid.scalar())
    await s.commit()
    return job_id


async def _a2t_db_update(s: AsyncSession, job_id: int, **fields) -> None:
    if not fields:
        return
    sets = ", ".join([f"{k} = :{k}" for k in fields.keys()])
    params = dict(fields)
    params["id"] = job_id
    await s.execute(sql_text(f"UPDATE a2t_jobs SET {sets} WHERE id = :id"), params)
    await s.commit()


async def _transcribe_audio(
    file_path: str, lang_code: str | None
) -> Tuple[str, Optional[str], Optional[float]]:
    """
    Возвращает: (text, backend, audio_seconds)
    """
    fd_wav, normalized_wav = tempfile.mkstemp(prefix="pls_a2t_norm_", suffix=".wav")
    os.close(fd_wav)
    converted = _ffmpeg_convert_to_wav(file_path, normalized_wav, rate=16000)
    src_for_stt = normalized_wav if converted else file_path

    audio_seconds: Optional[float] = None
    try:
        with wave.open(src_for_stt, "rb") as wf:
            audio_seconds = wf.getnframes() / float(max(wf.getframerate(), 1))
            if audio_seconds < 1.2:
                with contextlib.suppress(Exception):
                    os.remove(normalized_wav)
                return "", None, audio_seconds
    except Exception:
        pass

    if src_for_stt.endswith(".wav") and _rms_is_silent(src_for_stt):
        with contextlib.suppress(Exception):
            os.remove(normalized_wav)
        return "", None, audio_seconds

    lang = None if (lang_code in (None, "", "auto")) else lang_code

    try:
        from faster_whisper import WhisperModel  # type: ignore

        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(
            src_for_stt,
            language=lang,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
        )
        text = " ".join((seg.text or "").strip() for seg in segments if (seg.text or "").strip())
        if text.strip():
            with contextlib.suppress(Exception):
                os.remove(normalized_wav)
            return text.strip(), "faster-whisper(tiny)", audio_seconds
    except Exception:
        pass

    try:
        import whisper  # type: ignore

        model = whisper.load_model("tiny")
        result = model.transcribe(src_for_stt, language=lang)
        txt = (result.get("text") or "").strip()
        if txt:
            with contextlib.suppress(Exception):
                os.remove(normalized_wav)
            return txt, "openai-whisper(tiny)", audio_seconds
    except Exception:
        pass

    try:
        import vosk  # type: ignore
        import json

        model_path = os.environ.get("VOSK_MODEL")
        if model_path and os.path.isdir(model_path):
            model = vosk.Model(model_path)
            rec = vosk.KaldiRecognizer(model, 16000)
            with wave.open(
                src_for_stt if src_for_stt.endswith(".wav") else normalized_wav, "rb"
            ) as wf:
                while True:
                    data = wf.readframes(4000)
                    if not data:
                        break
                    rec.AcceptWaveform(data)
                out = json.loads(rec.FinalResult())
                txt = (out.get("text") or "").strip()
                if txt:
                    with contextlib.suppress(Exception):
                        os.remove(normalized_wav)
                    return txt, "vosk", audio_seconds
    except Exception:
        pass

    try:
        import speech_recognition as sr  # type: ignore

        r = sr.Recognizer()
        with sr.AudioFile(
            src_for_stt if src_for_stt.endswith(".wav") else normalized_wav
        ) as source:
            audio = r.record(source)
        txt = r.recognize_sphinx(
            audio, language="ru-RU" if (lang or "").startswith("ru") else "en-US"
        )
        txt = (txt or "").strip()
        if txt:
            with contextlib.suppress(Exception):
                os.remove(normalized_wav)
            return txt, "pocketsphinx", audio_seconds
    except Exception:
        pass

    with contextlib.suppress(Exception):
        os.remove(normalized_wav)
    return "", None, audio_seconds


@router.message(Command("start"))
@router.message(Command("menu"))
async def cmd_menu(message: Message, session_maker: async_sessionmaker[AsyncSession]) -> None:
    lang = (get_lang(message.from_user.id) or "ru").lower()
    if lang not in ("ru", "en"):
        lang = "ru"
    show_join, show_profile = await _flags_for_menu(
        session_maker, message.from_user.id, message.from_user.username
    )
    media, kb = (
        _render_user_menu(lang) if (show_profile and not show_join) else _render_guest_menu(lang)
    )
    await _answer_photo_or_text(message, media, kb)  # ← безопасная отправка


@router.callback_query(StartCB.filter(F.action == "lang"))
async def on_lang_selected(
    cb: CallbackQuery, callback_data: StartCB, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    lang = (callback_data.value or "ru").lower()
    set_lang(cb.from_user.id, "en" if lang == "en" else "ru")

    lang = (get_lang(cb.from_user.id) or "ru").lower()
    show_join, show_profile = await _flags_for_menu(
        session_maker, cb.from_user.id, cb.from_user.username
    )
    media, kb = (
        _render_user_menu(lang) if (show_profile and not show_join) else _render_guest_menu(lang)
    )
    try:
        await cb.message.edit_media(media=media, reply_markup=kb)
    except Exception:
        await _answer_photo_or_text(cb.message, media, kb)
        with contextlib.suppress(Exception):
            await cb.message.delete()
    with contextlib.suppress(TelegramBadRequest):
        await cb.answer()


@router.callback_query(StartCB.filter(F.action == "info"))
async def on_info(
    cb: CallbackQuery, callback_data: StartCB, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    lang = (callback_data.value or get_lang(cb.from_user.id) or "ru").lower()
    caption = {
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
    }[lang]

    media = InputMediaPhoto(
        media=_resolve_photo_source(INFO_BANNER), caption=caption, parse_mode=ParseMode.HTML
    )
    try:
        await cb.message.edit_media(media=media, reply_markup=_back_kb(lang))
    except Exception:
        await _answer_photo_or_text(cb.message, media, _back_kb(lang))
        with contextlib.suppress(Exception):
            await cb.message.delete()
    with contextlib.suppress(TelegramBadRequest):
        await cb.answer()


@router.callback_query(StartCB.filter(F.action == "rules"))
async def on_rules(cb: CallbackQuery, callback_data: StartCB) -> None:
    lang = (callback_data.value or get_lang(cb.from_user.id) or "ru").lower()
    media = InputMediaPhoto(
        media=_resolve_photo_source(RULES_BANNER["en" if lang == "en" else "ru"]),
        caption="https://telegra.ph/Svod-Svyashchennyh-pravil-Kluba-Lyubitelej-Sliv-10-25",
    )
    try:
        await cb.message.edit_media(media=media, reply_markup=_back_kb(lang))
    except Exception:
        # безопасный фолбэк — просто ссылку на правила текстом
        await cb.message.answer(media.caption or "", reply_markup=_back_kb(lang))
        with contextlib.suppress(Exception):
            await cb.message.delete()
    with contextlib.suppress(TelegramBadRequest):
        await cb.answer()


@router.callback_query(StartCB.filter(F.action == "help"))
async def on_help(cb: CallbackQuery, callback_data: StartCB) -> None:
    lang = (callback_data.value or get_lang(cb.from_user.id) or "ru").lower()
    media = InputMediaPhoto(
        media=_resolve_photo_source(HELP_BANNER),
        caption=_T["help_text"][lang],
        parse_mode=ParseMode.HTML,
    )
    try:
        await cb.message.edit_media(media=media, reply_markup=_help_kb(lang))
    except Exception:
        await _answer_photo_or_text(cb.message, media, _help_kb(lang))
        with contextlib.suppress(Exception):
            await cb.message.delete()
    with contextlib.suppress(TelegramBadRequest):
        await cb.answer()


@router.callback_query(StartCB.filter(F.action == "a2t"))
async def on_a2t(cb: CallbackQuery, callback_data: StartCB, state: FSMContext) -> None:
    lang = (callback_data.value or get_lang(cb.from_user.id) or "ru").lower()
    await state.set_state(A2TStates.choose_lang)
    media = InputMediaPhoto(
        media=_resolve_photo_source(A2T_BANNER),
        caption=_T["a2t_prompt"][lang],
        parse_mode=ParseMode.HTML,
    )
    try:
        await cb.message.edit_media(media=media, reply_markup=_a2t_lang_kb(lang))
    except Exception:
        await _answer_photo_or_text(cb.message, media, _a2t_lang_kb(lang))
        with contextlib.suppress(Exception):
            await cb.message.delete()
    with contextlib.suppress(TelegramBadRequest):
        await cb.answer()


@router.callback_query(StartCB.filter(F.action == "a2t_lang"))
async def on_a2t_lang(cb: CallbackQuery, callback_data: StartCB, state: FSMContext) -> None:
    ui_lang = (get_lang(cb.from_user.id) or "ru").lower()
    a2t_lang = callback_data.value or "auto"
    await state.update_data(a2t_lang=a2t_lang)
    await state.set_state(A2TStates.wait_audio)
    try:
        await cb.message.edit_caption(
            caption=_T["a2t_send_audio"][ui_lang],
            parse_mode=ParseMode.HTML,
            reply_markup=_back_kb(ui_lang),
        )
    except Exception:
        await cb.message.answer(_T["a2t_send_audio"][ui_lang], parse_mode=ParseMode.HTML)
    with contextlib.suppress(TelegramBadRequest):
        await cb.answer()


@router.message(A2TStates.wait_audio, F.voice | F.audio)
async def on_a2t_audio(
    message: Message, state: FSMContext, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    ui_lang = (get_lang(message.from_user.id) or "ru").lower()
    data = await state.get_data()
    lang_code = data.get("a2t_lang") or "auto"

    status = await message.answer("📥 <b>Загружаю файл…</b>", parse_mode=ParseMode.HTML)

    fd, tmp_path = tempfile.mkstemp(prefix="pls_a2t_", suffix=".ogg")
    os.close(fd)
    job_id = None
    backend = None
    audio_sec = None
    t0 = time.monotonic()

    try:
        if message.voice:
            await message.bot.download(message.voice, destination=tmp_path)
        else:
            await message.bot.download(message.audio, destination=tmp_path)

        await status.edit_text("📦 <b>Сохраняю задачу в БД…</b>", parse_mode=ParseMode.HTML)
        async with session_maker() as s:
            job_id = await _a2t_db_insert(
                s, user_id=message.from_user.id, lang=lang_code, file_path=tmp_path
            )

        await status.edit_text(
            f"🔄 <b>Конвертирую в WAV 16k…</b>\n<code>job #{job_id}</code>",
            parse_mode=ParseMode.HTML,
        )

        await status.edit_text(
            f"🧠 <b>Распознаю…</b>\n<code>job #{job_id}</code>", parse_mode=ParseMode.HTML
        )
        text, backend, audio_sec = await _transcribe_audio(tmp_path, lang_code)

        if not text:
            await status.edit_text(
                f"⚠️ <b>Не удалось распознать.</b>\n<code>job #{job_id}</code>",
                parse_mode=ParseMode.HTML,
            )
            async with session_maker() as s:
                await _a2t_db_update(
                    s,
                    job_id,
                    status="failed",
                    backend=backend,
                    finished_at=now_str(),
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    audio_seconds=audio_sec,
                    text_len=0,
                    error="empty_result",
                )
            await message.answer(
                _T["a2t_done_title"][ui_lang]
                + {"ru": "Не удалось распознать аудио.", "en": "Failed to transcribe audio."}[
                    ui_lang
                ],
                parse_mode=ParseMode.HTML,
            )
        else:
            dt_ms = int((time.monotonic() - t0) * 1000)
            await status.edit_text(
                f"✅ <b>Готово</b> — {len(text)} симв.\n"
                f"🧩 Бэкенд: <code>{backend}</code>\n"
                f"⏱️ Время: <code>{dt_ms} ms</code>, Аудио: <code>{(audio_sec or 0):.1f} s</code>\n"
                f"<code>job #{job_id}</code>",
                parse_mode=ParseMode.HTML,
            )
            async with session_maker() as s:
                await _a2t_db_update(
                    s,
                    job_id,
                    status="done",
                    backend=backend,
                    finished_at=now_str(),
                    duration_ms=dt_ms,
                    audio_seconds=audio_sec,
                    text_len=len(text),
                    error=None,
                )
            await message.answer(_T["a2t_done_title"][ui_lang] + text, parse_mode=ParseMode.HTML)

    finally:
        with contextlib.suppress(Exception):
            os.remove(tmp_path)

    await state.clear()
    show_join, show_profile = await _flags_for_menu(
        session_maker, message.from_user.id, message.from_user.username
    )
    media, kb = (
        _render_user_menu(ui_lang)
        if (show_profile and not show_join)
        else _render_guest_menu(ui_lang)
    )
    await _answer_photo_or_text(message, media, kb)  # ← безопасная отправка


@router.callback_query(StartCB.filter(F.action.in_({"gpt"})))
async def on_placeholders(cb: CallbackQuery, callback_data: StartCB) -> None:
    lang = (callback_data.value or get_lang(cb.from_user.id) or "ru").lower()

    banner = GPT_BANNER

    caption = {
        "ru": "⚡ <b>Раздел «Chat GPT 5» в разработке</b>.\nСкоро тут будет магия 🤖✨",
        "en": "⚡ <b>“Chat GPT 5” section is under construction</b>.\nMagic coming soon 🤖✨",
    }[lang]

    media = InputMediaPhoto(
        media=_resolve_photo_source(banner),
        caption=caption,
        parse_mode=ParseMode.HTML,
    )

    try:
        await cb.message.edit_media(media=media, reply_markup=_back_kb(lang))
    except Exception:
        await _answer_photo_or_text(cb.message, media, _back_kb(lang))
        with contextlib.suppress(Exception):
            await cb.message.delete()
    with contextlib.suppress(TelegramBadRequest):
        await cb.answer()


@router.callback_query(StartCB.filter(F.action == "features"))
async def on_features(cb: CallbackQuery, callback_data: StartCB) -> None:
    lang = (callback_data.value or get_lang(cb.from_user.id) or "ru").lower()
    caption = {
        "ru": "🗂 <b>Функции</b>\n\nВыбери нужный инструмент:",
        "en": "🗂 <b>Features</b>\n\nChoose a tool:",
    }[lang]
    media = InputMediaPhoto(
        media=_resolve_photo_source(SET_BANNER),
        caption=caption,
        parse_mode=ParseMode.HTML,
    )
    try:
        await cb.message.edit_media(media=media, reply_markup=_features_kb(lang))
    except Exception:
        await _answer_photo_or_text(cb.message, media, _features_kb(lang))
        with contextlib.suppress(Exception):
            await cb.message.delete()
    with contextlib.suppress(TelegramBadRequest):
        await cb.answer()


@router.callback_query(StartCB.filter(F.action == "link_platform"))
async def on_link_platform(
    cb: CallbackQuery, callback_data: StartCB, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    import uuid
    from datetime import datetime, timezone

    lang = (callback_data.value or get_lang(cb.from_user.id) or "ru").lower()

    async with session_maker() as s:
        # Проверяем, не подключена ли уже платформа
        already = await s.execute(
            sql_text("SELECT login FROM web_credentials WHERE tg_user_id = :uid"),
            {"uid": cb.from_user.id},
        )
        already_row = already.fetchone()

    if already_row:
        caption_ru = (
            "🔗 <b>Платформа уже подключена</b>\n\n"
            f"Твой логин: <code>{already_row.login}</code>\n\n"
            "Забыл пароль? Нажми /resetpassword\n"
            "Или открой платформу заново:"
        )
        caption_en = (
            "🔗 <b>Platform already connected</b>\n\n"
            f"Your login: <code>{already_row.login}</code>\n\n"
            "Forgot password? Use /resetpassword\n"
            "Or open the platform:"
        )
        caption = caption_ru if lang == "ru" else caption_en
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Открыть платформу" if lang == "ru" else "🌐 Open platform",
                                  url="https://plumgang.ru")],
            [InlineKeyboardButton(text=_T["btn_back"][lang],
                                  callback_data=StartCB(action="back", value=lang).pack())],
        ])
        media = InputMediaPhoto(
            media=_resolve_photo_source(SET_BANNER), caption=caption, parse_mode=ParseMode.HTML,
        )
        try:
            await cb.message.edit_media(media=media, reply_markup=kb)
        except Exception:
            await _answer_photo_or_text(cb.message, media, kb)
            with contextlib.suppress(Exception):
                await cb.message.delete()
        with contextlib.suppress(TelegramBadRequest):
            await cb.answer()
        return

    # Генерируем UUID-токен
    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    async with session_maker() as s:
        await s.execute(
            sql_text("""
            CREATE TABLE IF NOT EXISTS platform_link_tokens (
                code TEXT PRIMARY KEY,
                tg_user_id INTEGER NOT NULL,
                tg_username TEXT,
                created_at TEXT NOT NULL,
                used INTEGER DEFAULT 0
            )
        """)
        )
        # Удаляем старые коды этого пользователя
        await s.execute(
            sql_text("DELETE FROM platform_link_tokens WHERE tg_user_id = :uid"),
            {"uid": cb.from_user.id},
        )
        await s.execute(
            sql_text(
                "INSERT INTO platform_link_tokens (code, tg_user_id, tg_username, created_at) "
                "VALUES (:code, :uid, :uname, :ts)"
            ),
            {
                "code": token,
                "uid": cb.from_user.id,
                "uname": cb.from_user.username or "",
                "ts": now,
            },
        )
        await s.commit()

    link_url = f"https://plumgang.ru/auth?token={token}"

    caption_ru = (
        f"🔗 <b>Подключение платформы</b>\n\n"
        f"Нажми кнопку ниже, чтобы войти на платформу.\n"
        f"Логин и пароль будут созданы автоматически.\n\n"
        f"⏱ Ссылка действует <b>15 минут</b>."
    )
    caption_en = (
        f"🔗 <b>Connect Platform</b>\n\n"
        f"Press the button below to log in.\n"
        f"Login and password will be created automatically.\n\n"
        f"⏱ Link valid for <b>15 minutes</b>."
    )
    caption = caption_ru if lang == "ru" else caption_en

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Войти на платформу" if lang == "ru" else "🌐 Open platform",
                              url=link_url)],
        [InlineKeyboardButton(text=_T["btn_back"][lang],
                              callback_data=StartCB(action="back", value=lang).pack())],
    ])

    media = InputMediaPhoto(
        media=_resolve_photo_source(SET_BANNER),
        caption=caption,
        parse_mode=ParseMode.HTML,
    )
    try:
        await cb.message.edit_media(media=media, reply_markup=kb)
    except Exception:
        await _answer_photo_or_text(cb.message, media, kb)
        with contextlib.suppress(Exception):
            await cb.message.delete()
    with contextlib.suppress(TelegramBadRequest):
        await cb.answer()


@router.message(Command("resetpassword"))
async def cmd_reset_password(message: Message, session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Сброс пароля платформы — вызывает API для генерации нового пароля."""
    import aiohttp

    lang = (get_lang(message.from_user.id) or "ru").lower()

    try:
        async with aiohttp.ClientSession() as http_session:
            async with http_session.post(
                "http://localhost:8080/api/auth/bot-reset-password",
                json={"tg_user_id": message.from_user.id},
            ) as resp:
                if resp.status == 404:
                    no_account = {
                        "ru": "❌ У тебя нет аккаунта на платформе. Сначала подключи через кнопку «Подключить платформу».",
                        "en": "❌ You don't have a platform account. Connect first via «Connect platform» button.",
                    }
                    await message.answer(no_account[lang])
                    return

                data = await resp.json()
                login = data["login"]
                new_password = data["password"]
    except Exception as e:
        await message.answer(f"❌ Ошибка сброса пароля: {e}")
        return

    msg = {
        "ru": (
            f"🔑 <b>Пароль сброшен!</b>\n\n"
            f"Логин: <code>{login}</code>\n"
            f"Новый пароль: <code>{new_password}</code>\n\n"
            f"Используй эти данные для входа на <b>plumgang.ru</b>"
        ),
        "en": (
            f"🔑 <b>Password reset!</b>\n\n"
            f"Login: <code>{login}</code>\n"
            f"New password: <code>{new_password}</code>\n\n"
            f"Use these to log in at <b>plumgang.ru</b>"
        ),
    }
    await message.answer(msg[lang], parse_mode=ParseMode.HTML)


@router.callback_query(StartCB.filter(F.action == "back"))
async def on_back(
    cb: CallbackQuery,
    callback_data: StartCB,
    session_maker: async_sessionmaker[AsyncSession],
    state: FSMContext,
) -> None:
    await state.clear()
    lang = (callback_data.value or get_lang(cb.from_user.id) or "ru").lower()
    show_join, show_profile = await _flags_for_menu(
        session_maker, cb.from_user.id, cb.from_user.username
    )
    media, kb = (
        _render_user_menu(lang) if (show_profile and not show_join) else _render_guest_menu(lang)
    )
    try:
        await cb.message.edit_media(media=media, reply_markup=kb)
    except Exception:
        await _answer_photo_or_text(cb.message, media, kb)
        with contextlib.suppress(Exception):
            await cb.message.delete()
    with contextlib.suppress(TelegramBadRequest):
        await cb.answer()


@router.message(F.photo, F.from_user.id.in_(settings.ADMIN_USER_IDS))
async def grab_file_id(message: Message) -> None:
    file_id = message.photo[-1].file_id
    await message.answer(f"file_id: `{file_id}`", parse_mode="Markdown")
