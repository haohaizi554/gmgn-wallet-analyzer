from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from app.providers.dexscreener.parsers import DexPair
from app.resolvers.pool import select_primary_pool
from app.utils.money import to_decimal
from app.utils.time_utils import parse_timestamp


@dataclass
class MarketQuote:
    mint: str
    price_usd: Optional[Decimal] = None
    market_cap: Optional[Decimal] = None
    fdv: Optional[Decimal] = None
    liquidity_usd: Optional[Decimal] = None
    pair_created_at: Optional[int] = None
    dex_id: str = ""
    pair_address: str = ""
    symbol: str = ""
    name: str = ""
    source: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def quote_to_pair(quote: MarketQuote) -> DexPair:
    return DexPair(
        chain_id="solana",
        dex_id=quote.dex_id or quote.source,
        pair_address=quote.pair_address,
        base_address=quote.mint,
        base_symbol=quote.symbol,
        price_usd=quote.price_usd,
        liquidity_usd=quote.liquidity_usd,
        fdv=quote.fdv,
        market_cap=quote.market_cap,
        pair_created_at=quote.pair_created_at,
        source=quote.source,
        raw=quote.raw,
    )


def pair_needs_fill(pairs: list[DexPair], mint: str) -> bool:
    if not pairs:
        return True
    primary = select_primary_pool(pairs, mint)
    if primary is None:
        return True
    return (
        primary.price_usd in (None, 0)
        or primary.market_cap in (None, 0)
        or primary.fdv in (None, 0)
        or primary.pair_created_at in (None, 0)
    )


def merge_pair(existing: DexPair, extra: DexPair) -> DexPair:
    if existing.price_usd in (None, 0) and extra.price_usd not in (None, 0):
        existing.price_usd = extra.price_usd
    if existing.market_cap in (None, 0) and extra.market_cap not in (None, 0):
        existing.market_cap = extra.market_cap
    if existing.fdv in (None, 0) and extra.fdv not in (None, 0):
        existing.fdv = extra.fdv
    if existing.liquidity_usd in (None, 0) and extra.liquidity_usd not in (None, 0):
        existing.liquidity_usd = extra.liquidity_usd
    if not existing.pair_created_at and extra.pair_created_at:
        existing.pair_created_at = extra.pair_created_at
    if not existing.pair_address and extra.pair_address:
        existing.pair_address = extra.pair_address
    if not existing.dex_id and extra.dex_id:
        existing.dex_id = extra.dex_id
    if not existing.base_symbol and extra.base_symbol:
        existing.base_symbol = extra.base_symbol
    if extra.source and extra.source not in (existing.raw or {}).get("_filled_from", []):
        raw = dict(existing.raw or {})
        filled = list(raw.get("_filled_from") or [])
        filled.append(extra.source)
        raw["_filled_from"] = filled
        existing.raw = raw
    if existing.fdv in (None, 0) and existing.market_cap not in (None, 0):
        existing.fdv = existing.market_cap
    if existing.market_cap in (None, 0) and existing.fdv not in (None, 0):
        existing.market_cap = existing.fdv
    return existing


def merge_quote_fields(existing: MarketQuote, extra: MarketQuote) -> MarketQuote:
    if existing.price_usd in (None, 0) and extra.price_usd not in (None, 0):
        existing.price_usd = extra.price_usd
    if existing.market_cap in (None, 0) and extra.market_cap not in (None, 0):
        existing.market_cap = extra.market_cap
    if existing.fdv in (None, 0) and extra.fdv not in (None, 0):
        existing.fdv = extra.fdv
    if existing.liquidity_usd in (None, 0) and extra.liquidity_usd not in (None, 0):
        existing.liquidity_usd = extra.liquidity_usd
    if not existing.pair_created_at and extra.pair_created_at:
        existing.pair_created_at = extra.pair_created_at
    if not existing.pair_address and extra.pair_address:
        existing.pair_address = extra.pair_address
    if not existing.dex_id and extra.dex_id:
        existing.dex_id = extra.dex_id
    if not existing.symbol and extra.symbol:
        existing.symbol = extra.symbol
    if not existing.name and extra.name:
        existing.name = extra.name
    if extra.source and extra.source not in (existing.raw or {}).get("_filled_from", []):
        raw = dict(existing.raw or {})
        filled = list(raw.get("_filled_from") or [])
        filled.append(extra.source)
        raw["_filled_from"] = filled
        if extra.raw:
            raw[f"_{extra.source}_raw"] = extra.raw
        existing.raw = raw
    if existing.market_cap in (None, 0) and extra.market_cap not in (None, 0):
        existing.market_cap = extra.market_cap
    if existing.fdv in (None, 0) and existing.market_cap not in (None, 0):
        existing.fdv = existing.market_cap
    if existing.market_cap in (None, 0) and existing.fdv not in (None, 0):
        existing.market_cap = existing.fdv
    return existing


def merge_quote_lists(existing: list[MarketQuote], extra: list[MarketQuote]) -> list[MarketQuote]:
    by_mint: dict[str, MarketQuote] = {item.mint: item for item in existing if item.mint}
    for quote in extra:
        if not quote.mint:
            continue
        current = by_mint.get(quote.mint)
        if current is None:
            by_mint[quote.mint] = quote
            continue
        merge_quote_fields(current, quote)
    return list(by_mint.values())


def merge_quotes(grouped: dict[str, list[DexPair]], quotes: list[MarketQuote]) -> dict[str, list[DexPair]]:
    for quote in quotes:
        mint = quote.mint
        if not mint:
            continue
        extra = quote_to_pair(quote)
        current = list(grouped.get(mint) or [])
        if not current:
            grouped[mint] = [extra]
            continue
        primary = select_primary_pool(current, mint) or current[0]
        merge_pair(primary, extra)
        grouped[mint] = current
    return grouped


def created_at_from(value: Any) -> Optional[int]:
    return parse_timestamp(value)


def decimal_or_none(value: Any) -> Optional[Decimal]:
    parsed = to_decimal(value)
    if parsed is None or parsed == 0:
        return parsed
    return parsed
