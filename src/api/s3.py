"""
Загрузка файлов в S3-совместимое хранилище (Timeweb).

Аватарка сжимается до 256×256 WebP, загружается в бакет
и становится доступна по публичному URL.
"""

import io
import logging
from typing import Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from PIL import Image

from bot.config import settings

logger = logging.getLogger(__name__)

_AVATAR_SIZE = (256, 256)
_AVATAR_QUALITY = 85
_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB


def _get_s3_client():
    """Создать boto3-клиент для Timeweb S3."""
    if not all([settings.S3_ENDPOINT_URL, settings.S3_ACCESS_KEY, settings.S3_SECRET_KEY]):
        raise RuntimeError("S3 не настроен: проверьте S3_ENDPOINT_URL, S3_ACCESS_KEY, S3_SECRET_KEY в .env")

    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        config=BotoConfig(signature_version="s3v4"),
    )


def _process_avatar(raw_bytes: bytes) -> bytes:
    """
    Принимает сырые байты изображения.
    Конвертирует в RGB, ресайзит до 256×256 (crop по центру), сохраняет как WebP.
    """
    img = Image.open(io.BytesIO(raw_bytes))
    img = img.convert("RGB")

    # Center-crop в квадрат
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))

    # Ресайз
    img = img.resize(_AVATAR_SIZE, Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=_AVATAR_QUALITY)
    buf.seek(0)
    return buf.read()


def validate_avatar(content_type: Optional[str], size: int) -> Optional[str]:
    """
    Проверяет content-type и размер.
    Возвращает текст ошибки или None, если всё ок.
    """
    if content_type and content_type not in _ALLOWED_CONTENT_TYPES:
        return f"Недопустимый формат: {content_type}. Разрешены JPEG, PNG, WebP, GIF."
    if size > _MAX_FILE_SIZE:
        return f"Файл слишком большой ({size // 1024} KB). Максимум 2 MB."
    return None


def upload_avatar(raw_bytes: bytes, user_id: int) -> str:
    """
    Обрабатывает и загружает аватарку в S3.
    Возвращает публичный URL.
    """
    processed = _process_avatar(raw_bytes)
    key = f"avatars/{user_id}.webp"

    client = _get_s3_client()
    client.put_object(
        Bucket=settings.S3_BUCKET_NAME,
        Key=key,
        Body=processed,
        ContentType="image/webp",
        ACL="public-read",
    )

    # Timeweb S3: публичный URL = {endpoint}/{bucket}/{key}
    url = f"{settings.S3_ENDPOINT_URL}/{settings.S3_BUCKET_NAME}/{key}"
    logger.info("Avatar uploaded for user %s: %s", user_id, url)
    return url
