from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional


ZERO = Decimal("0")


def to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def require_decimal(value: Any, default: Optional[Decimal] = None) -> Optional[Decimal]:
    parsed = to_decimal(value)
    if parsed is None:
        return default
    return parsed


def quantize(value: Decimal, digits: int = 8) -> Decimal:
    q = Decimal("1").scaleb(-digits)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def format_usd(value: Optional[Decimal | float | int | str], estimated: bool = False) -> str:
    parsed = to_decimal(value)
    if parsed is None:
        return "GMGN 未提供"
    abs_value = abs(parsed)
    sign = "-" if parsed < 0 else ""
    if abs_value == 0:
        text = "$0.0000"
    elif abs_value < Decimal("0.01"):
        body = f"{abs_value:.8f}".rstrip("0").rstrip(".")
        text = f"{sign}${body}"
    else:
        text = f"{sign}${abs_value:,.4f}"
    return text


def format_usd_compact(value: Optional[Decimal | float | int | str], estimated: bool = False) -> str:
    parsed = to_decimal(value)
    if parsed is None:
        return "GMGN 未提供"
    abs_value = abs(parsed)
    sign = "-" if parsed < 0 else ""
    if abs_value >= Decimal("1000000000"):
        text = f"{sign}${abs_value / Decimal('1000000000'):.2f}B"
    elif abs_value >= Decimal("1000000"):
        text = f"{sign}${abs_value / Decimal('1000000'):.2f}M"
    elif abs_value >= Decimal("1000"):
        text = f"{sign}${abs_value / Decimal('1000'):.2f}K"
    elif abs_value >= Decimal("1"):
        text = f"{sign}${abs_value:,.2f}"
    elif abs_value >= Decimal("0.0001"):
        text = f"{sign}${abs_value:.4f}"
    else:
        body = f"{abs_value:.8f}".rstrip("0").rstrip(".")
        text = f"{sign}${body or '0'}"
    return text


def format_amount(value: Optional[Decimal | float | int | str], digits: int = 6) -> str:
    parsed = to_decimal(value)
    if parsed is None:
        return "GMGN 未提供"
    quantized = quantize(parsed, digits)
    return format(quantized.normalize(), "f")


def format_percent(value: Optional[Decimal | float | int | str], estimated: bool = False) -> str:
    parsed = to_decimal(value)
    if parsed is None:
        return "GMGN 未提供"
    # GMGN total_profit_pnl / pnl 多为倍数：1.5 = +150%
    percent = parsed * Decimal("100")
    return f"{percent:.2f}%"


def sol_from_usd(cost_usd: Optional[Decimal], sol_usd: Optional[Decimal]) -> Optional[Decimal]:
    if cost_usd is None or sol_usd is None or sol_usd <= 0:
        return None
    return cost_usd / sol_usd
