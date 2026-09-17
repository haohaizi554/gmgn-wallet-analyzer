from __future__ import annotations

from decimal import Decimal
from typing import Optional

from app.domain.enums import DataSource, ResolutionStatus
from app.domain.evidence import ResolvedField, resolved, unresolved
from app.providers.moralis.models import WalletSwap
from app.utils.money import to_decimal

STABLE_SYMBOLS = {"USDC", "USDT"}
SOL_SYMBOLS = {"SOL", "WSOL"}
SOL_MINTS = {
    "SOL",
    "So11111111111111111111111111111111111111112",
    "So11111111111111111111111111111111111111111",
}


def _is_sol_quote(quote) -> bool:
    symbol = (getattr(quote, "symbol", "") or "").upper()
    address = str(getattr(quote, "address", "") or "").strip()
    return symbol in SOL_SYMBOLS or address in SOL_MINTS


def enrich_swap_usd(swap: WalletSwap, sol_usd: Optional[Decimal] = None) -> WalletSwap:
    """Prefer swap-native USD; derive from stable quote; SOL quote uses SOL/USD as estimated."""
    kind = (swap.transaction_type or "").lower()
    token = swap.bought if kind in {"buy", "transfer_in", "transferin"} else swap.sold
    quote = swap.sold if kind in {"buy", "transfer_in", "transferin"} else swap.bought
    usd = token.usd_amount if token.usd_amount is not None else swap.total_value_usd
    if usd is None and token.usd_price is not None and token.amount is not None:
        usd = abs(token.usd_price * token.amount)
    quote_sym = (quote.symbol or "").upper()
    if usd is None and quote_sym in STABLE_SYMBOLS and quote.amount is not None:
        usd = abs(quote.amount)
        token.usd_amount = usd
        if token.amount:
            token.usd_price = usd / abs(token.amount)
        swap.total_value_usd = usd
    elif usd is None and _is_sol_quote(quote) and quote.amount is not None:
        px = to_decimal(sol_usd)
        if px not in (None, 0):
            usd = abs(quote.amount) * px
            token.usd_amount = usd
            if token.amount:
                token.usd_price = usd / abs(token.amount)
            swap.total_value_usd = usd
            raw = dict(swap.raw or {})
            raw["_usd_from_sol"] = True
            raw["_sol_usd"] = str(px)
            swap.raw = raw
    elif usd is not None:
        if token.usd_amount is None:
            token.usd_amount = abs(usd)
        if swap.total_value_usd is None:
            swap.total_value_usd = abs(usd)
    return swap


def resolve_cost_usd(swap: WalletSwap) -> Optional[ResolvedField]:
    enrich_swap_usd(swap)
    token = swap.bought if (swap.transaction_type or "").lower() == "buy" else swap.sold
    quote = swap.sold if (swap.transaction_type or "").lower() == "buy" else swap.bought
    if token.usd_amount is not None:
        status = ResolutionStatus.DIRECT
        if (quote.symbol or "").upper() in STABLE_SYMBOLS:
            status = ResolutionStatus.DERIVED
        if (swap.raw or {}).get("_usd_from_sol"):
            status = ResolutionStatus.ESTIMATED
        src = getattr(swap, "source", DataSource.MORALIS) or DataSource.MORALIS
        note = "SOL × SOL/USD 估算" if status == ResolutionStatus.ESTIMATED else "swap USD / stable quote"
        return resolved(abs(token.usd_amount), status, src, note=note, estimated=status == ResolutionStatus.ESTIMATED, field_name="cost_usd")
    if _is_sol_quote(quote):
        return unresolved(DataSource.LOCAL_CALCULATION, "无法验证历史美元成本", "cost_usd")
    return unresolved(DataSource.LOCAL_CALCULATION, "无法验证历史美元成本", "cost_usd")
