"""
Простейшее хранилище выбранного языка пользователем.

Используется хендлерами из разных модулей, чтобы:
- помнить язык между экранами;
- выбирать корректные баннеры/тексты (ru|en).

По умолчанию — 'ru'.
"""

from typing import Dict

_DEFAULT_LANG = "ru"
_lang_by_user: Dict[int, str] = {}


def set_lang(user_id: int, lang: str) -> None:
    """
    Сохранить язык пользователя.

    :param user_id: Telegram user id
    :param lang: 'ru' | 'en'
    """
    lang = (lang or "").lower()
    _lang_by_user[user_id] = "en" if lang == "en" else "ru"


def get_lang(user_id: int) -> str:
    """
    Получить язык пользователя (или 'ru', если ещё не задан).

    :param user_id: Telegram user id
    :return: 'ru' | 'en'
    """
    return _lang_by_user.get(user_id, _DEFAULT_LANG)
