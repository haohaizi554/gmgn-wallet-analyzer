from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from app.domain.enums import DataSource, EventType
from app.providers.helius.models import BalanceChange, HistoryTx
from app.providers.moralis.models import SwapLeg, WalletSwap
from app.utils.money import to_decimal

WSOL = "So11111111111111111111111111111111111111112"
SOL_ALIASES = {"SOL", "So11111111111111111111111111111111111111111", WSOL}
QUOTE_MINTS = SOL_ALIASES | {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}


def _mint(value: Any) -> str:
    text = str(value or "").strip()
    if text.upper() == "SOL" or text in SOL_ALIASES:
        return "SOL"
    return text


def parse_history_tx(item: Any) -> Optional[HistoryTx]:
    if not isinstance(item, dict):
        return None
    sig = str(item.get("signature") or item.get("transactionSignature") or "").strip()
    if not sig:
        return None
    changes: list[BalanceChange] = []
    for row in item.get("balanceChanges") or []:
        if not isinstance(row, dict):
            continue
        mint = _mint(row.get("mint"))
        if not mint:
            continue
        changes.append(
            BalanceChange(
                mint=mint,
                amount=to_decimal(row.get("amount")),
                decimals=int(row["decimals"]) if row.get("decimals") not in (None, "") else None,
            )
        )
    ts = item.get("timestamp") or 0
    try:
        ts_i = int(ts) if ts not in (None, "") else 0
    except (TypeError, ValueError):
        ts_i = 0
    fee = to_decimal(item.get("fee"))
    return HistoryTx(
        signature=sig,
        timestamp=ts_i,
        slot=item.get("slot"),
        fee_sol=fee,
        fee_payer=str(item.get("feePayer") or ""),
        error=item.get("error"),
        tx_type=str(item.get("type") or item.get("transactionType") or ""),
        balance_changes=changes,
        raw=item,
    )


def parse_history_page(payload: Any) -> tuple[list[HistoryTx], Optional[str], bool]:
    data = payload if isinstance(payload, dict) else {}
    rows = data.get("data") if isinstance(data.get("data"), list) else []
    txs = [parsed for item in rows if (parsed := parse_history_tx(item))]
    pagination = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}
    has_more = bool(pagination.get("hasMore"))
    cursor = pagination.get("nextCursor") or None
    if not has_more:
        cursor = None
    return txs, (str(cursor) if cursor else None), has_more


def classify_token_event(tx: HistoryTx, mint: str) -> str:
    token_delta = Decimal("0")
    quote_legs: dict[str, Decimal] = {}
    saw_token = False
    for change in tx.balance_changes:
        if change.amount is None:
            continue
        if change.mint == mint:
            token_delta += change.amount
            saw_token = True
        elif change.mint in QUOTE_MINTS or change.mint == "SOL":
            quote_legs[change.mint] = quote_legs.get(change.mint, Decimal("0")) + change.amount
    if not saw_token:
        return "none"
    quote_delta = Decimal("0")
    if quote_legs:
        quote_delta = max(quote_legs.values(), key=lambda v: abs(v))
    if token_delta > 0 and quote_delta < 0:
        return "buy"
    if token_delta < 0 and quote_delta > 0:
        return "sell"
    if token_delta > 0 and quote_delta > 0:
        return "unknown_swap"
    if token_delta < 0 and quote_delta < 0:
        return "unknown_swap"
    if token_delta > 0:
        return "transfer_in"
    if token_delta < 0:
        return "transfer_out"
    return "none"


QUOTE_SYMBOLS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    WSOL: "WSOL",
    "SOL": "SOL",
    "So11111111111111111111111111111111111111111": "SOL",
}


def _quote_leg_from_changes(tx: HistoryTx, token_mint: str) -> SwapLeg:
    quotes: dict[str, Decimal] = {}
    for change in tx.balance_changes:
        if change.amount is None:
            continue
        if change.mint == token_mint:
            continue
        if change.mint in QUOTE_MINTS or change.mint == "SOL":
            quotes[change.mint] = quotes.get(change.mint, Decimal("0")) + change.amount
    if not quotes:
        return SwapLeg()
    mint_q, amt = max(quotes.items(), key=lambda kv: abs(kv[1]))
    symbol = QUOTE_SYMBOLS.get(mint_q, mint_q[:4])
    address = WSOL if mint_q in SOL_ALIASES or mint_q == "SOL" else mint_q
    if mint_q == "SOL":
        address = WSOL
        symbol = "SOL"
    return SwapLeg(address=address, symbol=symbol, amount=abs(amt))


def history_to_swaps(wallet: str, txs: list[HistoryTx]) -> list[WalletSwap]:
    from app.resolvers.historical_price import enrich_swap_usd

    swaps: list[WalletSwap] = []
    for tx in txs:
        mints = {c.mint for c in tx.balance_changes if c.mint and c.mint not in QUOTE_MINTS and c.mint != "SOL"}
        for mint in mints:
            kind = classify_token_event(tx, mint)
            if kind not in {"buy", "sell", "transfer_in", "transfer_out"}:
                continue
            token_amt = sum((c.amount for c in tx.balance_changes if c.mint == mint and c.amount is not None), Decimal("0"))
            token_leg = SwapLeg(address=mint, amount=abs(token_amt) if token_amt is not None else None)
            quote_leg = _quote_leg_from_changes(tx, mint)
            if kind in {"buy", "transfer_in"}:
                bought, sold = token_leg, quote_leg
            else:
                bought, sold = quote_leg, token_leg
            swap = WalletSwap(
                transaction_hash=tx.signature,
                transaction_type=kind,
                block_timestamp=tx.timestamp,
                wallet_address=wallet,
                bought=bought,
                sold=sold,
                source=DataSource.HELIUS,
                raw=tx.raw,
            )
            swaps.append(enrich_swap_usd(swap))
    return swaps


def history_event_type(kind: str) -> EventType:
    return {
        "buy": EventType.BUY,
        "sell": EventType.SELL,
        "transfer_in": EventType.TRANSFER_IN,
        "transfer_out": EventType.TRANSFER_OUT,
    }.get(kind, EventType.UNKNOWN)
