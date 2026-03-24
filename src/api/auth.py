"""
Верификация Telegram initData по стандарту:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

Telegram подписывает initData HMAC-SHA256.
Ключ = HMAC-SHA256("WebAppData", bot_token).
Подпись = HMAC-SHA256(sorted_data_string, key).
"""

import hashlib
import hmac
import json
from urllib.parse import unquote, parse_qsl

from fastapi import Header, HTTPException, status

from bot.config import settings


def _compute_secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def verify_init_data(raw: str) -> dict:
    """
    Принимает строку initData из Telegram WebApp,
    проверяет подпись и возвращает словарь с данными, включая 'user'.

    Выбрасывает ValueError при неверной подписи.
    """
    params = dict(parse_qsl(raw, keep_blank_values=True))
    received_hash = params.pop("hash", None)
    if not received_hash:
        raise ValueError("hash отсутствует в initData")

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(params.items())
    )

    secret_key = _compute_secret_key(settings.TELEGRAM_BOT_TOKEN)
    expected_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError("Неверная подпись initData")

    # Парсим вложенный JSON user-объекта
    user_raw = params.get("user")
    if user_raw:
        params["user"] = json.loads(unquote(user_raw))

    return params


def get_telegram_user(
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
) -> dict:
    """
    FastAPI Dependency.
    Читает заголовок X-Telegram-Init-Data, верифицирует и возвращает user-dict.
    """
    try:
        data = verify_init_data(x_telegram_init_data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    user = data.get("user")
    if not user or "id" not in user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user отсутствует в initData",
        )
    return user
