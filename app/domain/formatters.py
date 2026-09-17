from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from app.domain.enums import FieldStatus
from app.utils.money import format_amount, format_percent, format_usd, format_usd_compact, to_decimal
from app.utils.time_utils import format_datetime
from app.utils.validators import short_address


STATUS_TEXT = {
    FieldStatus.NOT_APPLICABLE: "不适用",
    FieldStatus.UNKNOWN: "未知",
    FieldStatus.API_MISSING: "GMGN 未提供",
    FieldStatus.ERROR: "接口暂不可用",
    FieldStatus.ESTIMATED: "估算值",
    FieldStatus.KNOWN: "已知",
}


def status_label(status: FieldStatus, reason: str = "") -> str:
    if reason:
        return reason
    return STATUS_TEXT.get(status, "未知")


def safe_export_value(
    value: Any,
    status: Optional[FieldStatus] = None,
    *,
    estimated: bool = False,
    reason: str = "",
    kind: str = "text",
) -> Any:
    """Excel / JSON 导出值。禁止 None、空字符串，禁止把缺失数据变成 0。"""
    resolved_status = status or FieldStatus.KNOWN
    if resolved_status in (
        FieldStatus.NOT_APPLICABLE,
        FieldStatus.UNKNOWN,
        FieldStatus.API_MISSING,
        FieldStatus.ERROR,
    ):
        text = status_label(resolved_status, reason)
        return text if text else "未知"

    if value is None or value == "":
        text = status_label(FieldStatus.API_MISSING, reason)
        return text if text else "GMGN 未提供"

    if kind == "usd":
        return format_usd(value, estimated=estimated or resolved_status == FieldStatus.ESTIMATED)
    if kind == "usd_compact":
        return format_usd_compact(value, estimated=estimated or resolved_status == FieldStatus.ESTIMATED)
    if kind == "amount":
        return format_amount(value)
    if kind == "percent":
        return format_percent(value, estimated=estimated)
    if kind == "datetime":
        return format_datetime(value)
    if kind == "address":
        text = str(value).strip()
        return text if text else "未知地址"
    if kind == "int":
        parsed = to_decimal(value)
        if parsed is None:
            return status_label(FieldStatus.API_MISSING, reason)
        return int(parsed)
    if kind == "number":
        parsed = to_decimal(value)
        if parsed is None:
            return status_label(FieldStatus.API_MISSING, reason)
        return float(parsed)
    if isinstance(value, Decimal):
        text = format(value.normalize(), "f")
        return f"{text}（估）" if estimated else text
    text = str(value).strip()
    if not text:
        return reason or "GMGN 未提供"
    if estimated and "（估）" not in text:
        return f"{text}（估）"
    return text


def format_duration_zh(seconds: Optional[int]) -> str:
    if seconds is None:
        return "无法计算"
    value = int(seconds)
    if value < 0:
        return "时间异常"
    if value < 60:
        return f"{value}秒"
    if value < 3600:
        return f"{value // 60}分钟"
    if value < 86400:
        hours = value // 3600
        minutes = (value % 3600) // 60
        return f"{hours}小时" if minutes == 0 else f"{hours}小时{minutes}分钟"
    days = value // 86400
    hours = (value % 86400) // 3600
    return f"{days}天" if hours == 0 else f"{days}天{hours}小时"


def format_hms_unbounded(seconds: Optional[int]) -> str:
    if seconds is None:
        return "无法计算"
    sign = "-" if seconds < 0 else ""
    value = abs(int(seconds))
    hours = value // 3600
    minutes = (value % 3600) // 60
    secs = value % 60
    return f"{sign}{hours:02d}:{minutes:02d}:{secs:02d}"


def display_address(address: str) -> str:
    return short_address(address)
