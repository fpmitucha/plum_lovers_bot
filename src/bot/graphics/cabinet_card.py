from __future__ import annotations
"""
Генерация карточки ЛК поверх шаблона.

1) Строки 1–2: лейбл слева (ТОП/TOP, КАРМА/KARMA), число справа — один общий размер
   для обеих строк; вертикальное выравнивание по центру.
2) Строка 3: @username слева; если не помещается — показываем id.

Координаты плашек заданы по референсу 1536×1024:
  1: (965, 481) — (1444, 586)
  2: (965, 619) — (1444, 725)
  3: (965, 757) — (1444, 865)
и масштабируются под фактический размер изображения.
"""

import os
import tempfile
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

# --- настройки ---
STROKE_W = 2
COLOR_STROKE = (244, 225, 199)
COLOR_LABEL = (45, 30, 20)
COLOR_VALUE = (124, 37, 29)  # бордовый для цифр

# --- шрифты ---
_FONT_CANDIDATES = (
    "./data/fonts/Inter-Bold.ttf",
    "./data/fonts/InterDisplay-Bold.ttf",
    "./data/fonts/PlusJakartaSans-Bold.ttf",
    "./data/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
)

def _load_font(size: int) -> ImageFont.ImageFont:
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size=size)
            except Exception:
                pass
    return ImageFont.load_default()

def _text_box(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
    l, t, r, b = draw.textbbox((0, 0), text, font=font, stroke_width=STROKE_W)
    return r - l, b - t

def _fit_size_pair(
    draw: ImageDraw.ImageDraw,
    label: str, value: str,
    w_label: int, w_value: int,
    max_h: int,
    start: int
) -> int:
    """Единый размер шрифта, чтобы label и value вписались в свои ширины и общую высоту."""
    lo, hi = 10, max(10, start)
    ok = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        f = _load_font(mid)
        lw, lh = _text_box(draw, label, f)
        vw, vh = _text_box(draw, value, f)
        if lw <= w_label and vw <= w_value and max(lh, vh) <= max_h:
            ok = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return ok

def _fit_size_single(draw: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int, start: int) -> int:
    lo, hi = 10, max(10, start)
    ok = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        f = _load_font(mid)
        w, h = _text_box(draw, text, f)
        if w <= max_w and h <= max_h:
            ok = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return ok

def _draw_label_value(
    draw: ImageDraw.ImageDraw,
    box_px: Tuple[int, int, int, int],
    label: str,
    value: str,
    force_size: Optional[int] = None,
) -> None:
    """Лейбл слева, число справа. Вертикальная центровка, учёт stroke, единый размер."""
    x1, y1, x2, y2 = box_px
    pad_x = max(18, int((x2 - x1) * 0.06))  # динамический внутренний отступ
    pad_y = max(6, int((y2 - y1) * 0.12))

    max_h = (y2 - y1) - 2 * pad_y
    total_w = (x2 - x1) - 2 * pad_x

    # 65% под подпись, 35% под число — чтобы с двузначными числами было комфортно
    w_label = int(total_w * 0.65)
    w_value = total_w - w_label

    if force_size is None:
        size = _fit_size_pair(draw, label, value, w_label, w_value, max_h, start=int(max_h * 1.5))
    else:
        size = force_size
    font = _load_font(size)

    cy = (y1 + y2) // 2

    # label — слева, якорь: left-middle
    lx = x1 + pad_x
    draw.text((lx, cy), label, font=font, fill=COLOR_LABEL,
              stroke_width=STROKE_W, stroke_fill=COLOR_STROKE, anchor="lm")

    # value — справа, якорь: right-middle
    rx = x2 - pad_x
    draw.text((rx, cy), value, font=font, fill=COLOR_VALUE,
              stroke_width=STROKE_W, stroke_fill=COLOR_STROKE, anchor="rm")

def _draw_single_left(draw: ImageDraw.ImageDraw, box_px: Tuple[int, int, int, int], text: str) -> None:
    """Один текст слева, вертикально по центру."""
    x1, y1, x2, y2 = box_px
    pad_x = max(18, int((x2 - x1) * 0.06))
    pad_y = max(6, int((y2 - y1) * 0.12))
    max_h = (y2 - y1) - 2 * pad_y
    max_w = (x2 - x1) - 2 * pad_x

    size = _fit_size_single(draw, text, max_w, max_h, start=int(max_h * 1.5))
    font = _load_font(size)

    cy = (y1 + y2) // 2
    x = x1 + pad_x
    draw.text((x, cy), text, font=font, fill=COLOR_LABEL,
              stroke_width=STROKE_W, stroke_fill=COLOR_STROKE, anchor="lm")

def render_cabinet_card(
    template_path: str,
    *,
    rank: int,
    karma: int,
    username: Optional[str],
    user_id: int,
    lang: str = "ru",
    out_path: Optional[str] = None,
) -> str:
    im = Image.open(template_path).convert("RGBA")
    W, H = im.size
    draw = ImageDraw.Draw(im)

    # масштабируем ваши пиксельные координаты с референса 1536×1024
    REF_W, REF_H = 1536, 1024
    def sbox(b: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        x1, y1, x2, y2 = b
        return (int(x1 * W / REF_W), int(y1 * H / REF_H),
                int(x2 * W / REF_W), int(y2 * H / REF_H))

    boxes_ref = [
        (965, 481, 1444, 586),  # 1
        (965, 619, 1444, 725),  # 2
        (965, 757, 1444, 865),  # 3
    ]
    b1, b2, b3 = (sbox(b) for b in boxes_ref)

    labels = {"ru": ("ТОП", "КАРМА"), "en": ("TOP", "KARMA")}
    lab1, lab2 = labels["en" if lang == "en" else "ru"]
    val1 = str(rank if rank else "—")
    val2 = str(karma)

    # --- Подбираем единый размер для 1 и 2 строки ---
    def _pair_size_for(box, label, value) -> int:
        x1, y1, x2, y2 = box
        pad_x = max(18, int((x2 - x1) * 0.06))
        pad_y = max(6, int((y2 - y1) * 0.12))
        max_h = (y2 - y1) - 2 * pad_y
        total_w = (x2 - x1) - 2 * pad_x
        w_label = int(total_w * 0.65)
        w_value = total_w - w_label
        return _fit_size_pair(draw, label, value, w_label, w_value, max_h, start=int(max_h * 1.5))

    sz1 = _pair_size_for(b1, lab1, val1)
    sz2 = _pair_size_for(b2, lab2, val2)
    common_size = min(sz1, sz2)

    _draw_label_value(draw, b1, lab1, val1, force_size=common_size)
    _draw_label_value(draw, b2, lab2, val2, force_size=common_size)

    # --- 3 строка: @username (или id), слева ---
    if username:
        candidate = f"@{username}"
    else:
        candidate = str(user_id)

    # если @username не помещается — ставим id
    x1, y1, x2, y2 = b3
    pad_x = max(18, int((x2 - x1) * 0.06))
    pad_y = max(6, int((y2 - y1) * 0.12))
    max_h = (y2 - y1) - 2 * pad_y
    max_w = (x2 - x1) - 2 * pad_x
    sz_try = _fit_size_single(draw, candidate, max_w, max_h, start=int(max_h * 1.5))
    if _text_box(draw, candidate, _load_font(sz_try))[0] <= max_w:
        text3 = candidate
    else:
        text3 = str(user_id)
    _draw_single_left(draw, b3, text3)

    # сохранение
    if not out_path:
        fd, out_path = tempfile.mkstemp(prefix="pls_card_", suffix=".png")
        os.close(fd)
    im.save(out_path, format="PNG")
    return out_path
