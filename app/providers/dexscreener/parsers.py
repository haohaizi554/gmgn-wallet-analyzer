from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from app.utils.money import to_decimal


@dataclass
class DexPair:
    chain_id: str = ""
    dex_id: str = ""
    pair_address: str = ""
    base_address: str = ""
    base_symbol: str = ""
    quote_address: str = ""
    quote_symbol: str = ""
    price_native: Optional[Decimal] = None
    price_usd: Optional[Decimal] = None
    liquidity_usd: Optional[Decimal] = None
    liquidity_base: Optional[Decimal] = None
    liquidity_quote: Optional[Decimal] = None
    fdv: Optional[Decimal] = None
    market_cap: Optional[Decimal] = None
    pair_created_at: Optional[int] = None
    labels: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def parse_pair(item: Any) -> Optional[DexPair]:
    if not isinstance(item, dict):
        return None
    base = item.get("baseToken") if isinstance(item.get("baseToken"), dict) else {}
    quote = item.get("quoteToken") if isinstance(item.get("quoteToken"), dict) else {}
    liq = item.get("liquidity") if isinstance(item.get("liquidity"), dict) else {}
    created = item.get("pairCreatedAt")
    created_ts = None
    try:
        if created not in (None, ""):
            created_ts = int(created)
            if created_ts > 10_000_000_000:
                created_ts //= 1000
    except (TypeError, ValueError):
        created_ts = None
    labels = item.get("labels") if isinstance(item.get("labels"), list) else []
    return DexPair(
        chain_id=str(item.get("chainId") or ""),
        dex_id=str(item.get("dexId") or ""),
        pair_address=str(item.get("pairAddress") or ""),
        base_address=str(base.get("address") or ""),
        base_symbol=str(base.get("symbol") or ""),
        quote_address=str(quote.get("address") or ""),
        quote_symbol=str(quote.get("symbol") or ""),
        price_native=to_decimal(item.get("priceNative")),
        price_usd=to_decimal(item.get("priceUsd")),
        liquidity_usd=to_decimal(liq.get("usd")),
        liquidity_base=to_decimal(liq.get("base")),
        liquidity_quote=to_decimal(liq.get("quote")),
        fdv=to_decimal(item.get("fdv")),
        market_cap=to_decimal(item.get("marketCap")),
        pair_created_at=created_ts,
        labels=[str(x) for x in labels],
        raw=item,
    )


def parse_pairs(payload: Any) -> list[DexPair]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("pairs") or payload.get("data") or []
    else:
        rows = []
    out: list[DexPair] = []
    for item in rows:
        parsed = parse_pair(item)
        if parsed:
            out.append(parsed)
    return out
