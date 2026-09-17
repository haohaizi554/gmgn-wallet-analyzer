from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

ILLEGAL_XML_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
INVISIBLE_CHARS = {
    "\u00a0",
    "\u115f",
    "\u1160",
    "\u180e",
    "\u200b",
    "\u200c",
    "\u200d",
    "\u200e",
    "\u200f",
    "\u2028",
    "\u2029",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
    "\u2060",
    "\u2061",
    "\u2062",
    "\u2063",
    "\u2064",
    "\u2066",
    "\u2067",
    "\u2068",
    "\u2069",
    "\u3000",
    "\u3164",
    "\ufeff",
    "\uffa0",
}
FORMULA_PREFIX = {"=", "+", "-", "@", "\t", "\r"}
_SAFE_SIGNED_VALUE = re.compile(
    r"""
    ^[+-]
    (?:
        \$?\d[\d,]*(?:\.\d+)?   # -35.91 / -$35.9180 / -1,234.56
        |
        \d+:\d{2}:\d{2}         # -00:01:40 / -7920:04:12
    )
    $
    """,
    re.VERBOSE,
)


PLACEHOLDER_LABELS = {"未知", "无", "N/A", "n/a", "null", "None"}


def visible_text(value: Any) -> str:
    text = ILLEGAL_XML_RE.sub("", str(value or ""))
    cleaned = "".join(ch for ch in text if ch not in INVISIBLE_CHARS)
    cleaned = cleaned.strip()
    if cleaned in PLACEHOLDER_LABELS:
        return ""
    return cleaned


def token_display_labels(*candidates: Any, fallback: str = "未知") -> tuple[str, str]:
    visibles = [visible_text(item) for item in candidates]
    visibles = [item for item in visibles if item]
    symbol = visibles[0] if visibles else (visible_text(fallback) or "未知")
    name = visibles[1] if len(visibles) > 1 else symbol
    return symbol, name


def excel_cell(value: Any) -> Any:
    if value is None:
        return "无法验证"
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return value
    text = ILLEGAL_XML_RE.sub("", str(value))
    if visible_text(text) == "":
        return "未知"
    if text.startswith("'") and len(text) > 1:
        inner = text[1:]
        if _is_excel_safe_signed_value(inner):
            return inner
        if inner[:1] in FORMULA_PREFIX and not _is_excel_safe_signed_value(inner):
            return text
    if text[:1] in FORMULA_PREFIX and not _is_excel_safe_signed_value(text):
        return f"'{text}"
    return text


def _is_excel_safe_signed_value(text: str) -> bool:
    return bool(_SAFE_SIGNED_VALUE.match(text.replace(" ", "")))
