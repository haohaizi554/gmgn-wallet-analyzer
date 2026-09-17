from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from app.providers.moralis.models import SwapLeg, TokenMetadata, WalletPortfolio, WalletSwap
from app.utils.money import to_decimal


def parse_iso_ts(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        ts = int(value)
        return ts // 1000 if ts > 10_000_000_000 else ts
    text = str(value).strip()
    if not text:
        return 0
    try:
        if text.isdigit():
            ts = int(text)
            return ts // 1000 if ts > 10_000_000_000 else ts
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return 0


def _leg(data: Any) -> SwapLeg:
    item = data if isinstance(data, dict) else {}
    return SwapLeg(
        address=str(item.get("address") or "").strip(),
        name=str(item.get("name") or "").strip(),
        symbol=str(item.get("symbol") or "").strip(),
        amount=to_decimal(item.get("amount")),
        usd_price=to_decimal(item.get("usdPrice")),
        usd_amount=to_decimal(item.get("usdAmount")),
        token_type=str(item.get("tokenType") or ""),
    )


def parse_wallet_swap(item: dict[str, Any], wallet: str = "") -> Optional[WalletSwap]:
    if not isinstance(item, dict):
        return None
    tx = str(item.get("transactionHash") or item.get("transaction_hash") or "").strip()
    if not tx:
        return None
    bought = _leg(item.get("bought"))
    sold = _leg(item.get("sold"))
    parsed = WalletSwap(
        transaction_hash=tx,
        transaction_type=str(item.get("transactionType") or item.get("transaction_type") or "").lower(),
        block_timestamp=parse_iso_ts(item.get("blockTimestamp") or item.get("block_timestamp")),
        wallet_address=str(item.get("walletAddress") or wallet or "").strip(),
        pair_address=str(item.get("pairAddress") or ""),
        pair_label=str(item.get("pairLabel") or ""),
        exchange_address=str(item.get("exchangeAddress") or ""),
        exchange_name=str(item.get("exchangeName") or ""),
        bought=bought,
        sold=sold,
        total_value_usd=to_decimal(item.get("totalValueUsd") or item.get("usdAmount") or item.get("total_value_usd")),
        raw=item,
    )
    from app.resolvers.historical_price import enrich_swap_usd

    return enrich_swap_usd(parsed)


def parse_swaps_page(payload: Any, wallet: str = "") -> tuple[list[WalletSwap], Optional[str]]:
    data = payload if isinstance(payload, dict) else {}
    rows = data.get("result") if isinstance(data.get("result"), list) else []
    swaps: list[WalletSwap] = []
    for item in rows:
        parsed = parse_wallet_swap(item, wallet)
        if parsed:
            swaps.append(parsed)
    cursor = data.get("cursor")
    if cursor in (None, "", "null"):
        cursor = None
    return swaps, str(cursor) if cursor else None


def parse_token_metadata(item: Any) -> Optional[TokenMetadata]:
    if not isinstance(item, dict):
        return None
    mint = str(item.get("mint") or item.get("address") or "").strip()
    if not mint:
        return None
    metaplex = item.get("metaplex") if isinstance(item.get("metaplex"), dict) else {}
    decimals_raw = item.get("decimals")
    decimals = None
    try:
        if decimals_raw not in (None, ""):
            decimals = int(float(str(decimals_raw)))
    except (TypeError, ValueError):
        decimals = None
    return TokenMetadata(
        mint=mint,
        name=str(item.get("name") or "").strip(),
        symbol=str(item.get("symbol") or "").strip(),
        decimals=decimals,
        total_supply=to_decimal(item.get("totalSupply")),
        total_supply_formatted=to_decimal(item.get("totalSupplyFormatted")),
        circulating_supply=to_decimal(item.get("circulatingSupply")),
        fully_diluted_value=to_decimal(item.get("fullyDilutedValue")),
        market_cap=to_decimal(item.get("marketCap")),
        metadata_uri=str(metaplex.get("metadataUri") or ""),
        update_authority=str(metaplex.get("updateAuthority") or ""),
        is_mutable=metaplex.get("isMutable") if isinstance(metaplex.get("isMutable"), bool) else None,
        is_verified_contract=item.get("isVerifiedContract") if isinstance(item.get("isVerifiedContract"), bool) else None,
        possible_spam=item.get("possibleSpam") if isinstance(item.get("possibleSpam"), bool) else None,
        raw=item,
    )


def parse_metadata_batch(payload: Any) -> list[TokenMetadata]:
    rows = payload if isinstance(payload, list) else []
    out: list[TokenMetadata] = []
    for item in rows:
        parsed = parse_token_metadata(item)
        if parsed:
            out.append(parsed)
    return out


def parse_portfolio(payload: Any) -> WalletPortfolio:
    data = payload if isinstance(payload, dict) else {}
    native = data.get("nativeBalance") if isinstance(data.get("nativeBalance"), dict) else {}
    tokens: dict[str, Decimal] = {}
    for item in data.get("tokens") or []:
        if not isinstance(item, dict):
            continue
        mint = str(item.get("mint") or "").strip()
        amount = to_decimal(item.get("amount"))
        if mint and amount is not None:
            tokens[mint] = amount
    lamports = native.get("lamports")
    try:
        lamports_i = int(str(lamports)) if lamports not in (None, "") else None
    except (TypeError, ValueError):
        lamports_i = None
    return WalletPortfolio(
        native_sol=to_decimal(native.get("solana")),
        native_lamports=lamports_i,
        tokens=tokens,
        raw=data,
    )
