from __future__ import annotations

from typing import Any

from app.domain.enums import DataSource
from app.providers.moralis.models import SwapLeg, WalletSwap
from app.utils.money import to_decimal


def swap_fingerprint(swap: WalletSwap) -> str:
    return f"{swap.transaction_hash}:{swap.transaction_type}:{swap.token_address}:{swap.block_timestamp}"


def swap_to_row(wallet: str, provider: str, swap: WalletSwap, event_index: int = 0) -> dict[str, Any]:
    token = swap.bought if (swap.transaction_type or "").lower() in {"buy", "transfer_in", "transferin"} else swap.sold
    quote = swap.sold if (swap.transaction_type or "").lower() in {"buy", "transfer_in", "transferin"} else swap.bought
    return {
        "wallet": wallet,
        "signature": swap.transaction_hash,
        "event_index": event_index,
        "timestamp": int(swap.block_timestamp or 0),
        "event_type": swap.transaction_type,
        "mint": swap.token_address,
        "token_amount": str(token.amount) if token.amount is not None else "",
        "quote_mint": quote.address,
        "quote_symbol": quote.symbol,
        "quote_amount": str(quote.amount) if quote.amount is not None else "",
        "usd_amount": str(swap.total_value_usd if swap.total_value_usd is not None else token.usd_amount or ""),
        "usd_price": str(token.usd_price or ""),
        "provider": provider,
        "fingerprint": swap_fingerprint(swap),
        "raw_reference": swap.transaction_hash,
        "_bought": {
            "address": swap.bought.address,
            "symbol": swap.bought.symbol,
            "name": swap.bought.name,
            "amount": str(swap.bought.amount) if swap.bought.amount is not None else "",
            "usd_amount": str(swap.bought.usd_amount) if swap.bought.usd_amount is not None else "",
            "usd_price": str(swap.bought.usd_price) if swap.bought.usd_price is not None else "",
        },
        "_sold": {
            "address": swap.sold.address,
            "symbol": swap.sold.symbol,
            "name": swap.sold.name,
            "amount": str(swap.sold.amount) if swap.sold.amount is not None else "",
            "usd_amount": str(swap.sold.usd_amount) if swap.sold.usd_amount is not None else "",
            "usd_price": str(swap.sold.usd_price) if swap.sold.usd_price is not None else "",
        },
        "_source": getattr(swap.source, "value", None) or str(swap.source or provider),
        "_total_usd": str(swap.total_value_usd) if swap.total_value_usd is not None else "",
        "_fee_sol": str((swap.raw or {}).get("_fee_sol") or ""),
        "_usd_from_sol": bool((swap.raw or {}).get("_usd_from_sol")),
        "_sol_usd": str((swap.raw or {}).get("_sol_usd") or ""),
    }


def _leg(payload: dict[str, Any] | None) -> SwapLeg:
    item = payload or {}
    return SwapLeg(
        address=str(item.get("address") or ""),
        symbol=str(item.get("symbol") or ""),
        name=str(item.get("name") or ""),
        amount=to_decimal(item.get("amount")) if item.get("amount") not in (None, "") else None,
        usd_amount=to_decimal(item.get("usd_amount")) if item.get("usd_amount") not in (None, "") else None,
        usd_price=to_decimal(item.get("usd_price")) if item.get("usd_price") not in (None, "") else None,
    )


def row_to_swap(row: dict[str, Any]) -> WalletSwap:
    extra = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    bought = _leg(extra.get("_bought") or {
        "address": row.get("mint"),
        "amount": row.get("token_amount"),
    })
    sold = _leg(extra.get("_sold") or {
        "address": row.get("quote_mint"),
        "symbol": row.get("quote_symbol"),
        "amount": row.get("quote_amount"),
    })
    src_raw = extra.get("_source") or row.get("provider") or "moralis"
    try:
        src = DataSource(str(src_raw))
    except ValueError:
        src = DataSource.MORALIS
    usd = to_decimal(extra.get("_total_usd") or row.get("usd_amount"))
    kind = str(row.get("event_type") or extra.get("event_type") or "buy")
    if kind.lower() not in {"buy", "sell", "transfer_in", "transfer_out"}:
        kind = "buy"
    return WalletSwap(
        transaction_hash=str(row.get("signature") or ""),
        transaction_type=kind,
        block_timestamp=int(row.get("timestamp") or 0),
        wallet_address=str(row.get("wallet") or ""),
        bought=bought,
        sold=sold,
        total_value_usd=usd,
        source=src,
        raw={
            "cached": True,
            "fingerprint": row.get("fingerprint"),
            "_fee_sol": extra.get("_fee_sol") or "",
            "_usd_from_sol": bool(extra.get("_usd_from_sol")),
            "_sol_usd": extra.get("_sol_usd") or "",
        },
    )


def merge_swaps(new_swaps: list[WalletSwap], cached: list[WalletSwap]) -> list[WalletSwap]:
    seen: set[str] = set()
    out: list[WalletSwap] = []
    for item in list(new_swaps) + list(cached):
        key = swap_fingerprint(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    out.sort(key=lambda s: (s.block_timestamp or 0, s.transaction_hash), reverse=True)
    return out


def merge_history_state(prev: dict[str, Any] | None, signatures_ts: list[tuple[str, int]], bottom_complete: bool) -> dict[str, Any]:
    if not signatures_ts and not prev:
        return {
            "oldest_signature": "",
            "oldest_block_time": 0,
            "newest_signature": "",
            "newest_block_time": 0,
            "bottom_complete": False,
        }
    newest = max(signatures_ts, key=lambda x: (x[1], x[0])) if signatures_ts else ("", 0)
    oldest = min(signatures_ts, key=lambda x: (x[1] or 10**18, x[0])) if signatures_ts else ("", 0)
    if not prev:
        return {
            "oldest_signature": oldest[0],
            "oldest_block_time": oldest[1],
            "newest_signature": newest[0],
            "newest_block_time": newest[1],
            "bottom_complete": bottom_complete,
        }
    prev_oldest_ts = int(prev.get("oldest_block_time") or 0)
    prev_newest_ts = int(prev.get("newest_block_time") or 0)
    prev_oldest_sig = str(prev.get("oldest_signature") or "")
    prev_newest_sig = str(prev.get("newest_signature") or "")
    if prev_oldest_ts and (not oldest[1] or prev_oldest_ts <= oldest[1]):
        oldest_sig, oldest_ts = prev_oldest_sig, prev_oldest_ts
    else:
        oldest_sig, oldest_ts = oldest
    if prev_newest_ts and prev_newest_ts >= newest[1]:
        newest_sig, newest_ts = prev_newest_sig, prev_newest_ts
    else:
        newest_sig, newest_ts = newest
    return {
        "oldest_signature": oldest_sig,
        "oldest_block_time": oldest_ts,
        "newest_signature": newest_sig,
        "newest_block_time": newest_ts,
        "bottom_complete": bool(prev.get("bottom_complete")) or bottom_complete,
    }
