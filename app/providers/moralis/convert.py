from __future__ import annotations

from app.domain.enums import EventType, FieldStatus
from app.domain.fingerprint import activity_fingerprint
from app.domain.models import TradeRecord
from app.providers.moralis.models import WalletSwap
from app.providers.solana.transaction_parser import WSOL_MINT


def swap_to_trade(swap: WalletSwap, chain: str = "sol") -> TradeRecord:
    kind = (swap.transaction_type or "").lower().replace(" ", "")
    is_buy = kind in {"buy", "transfer_in", "transferin"}
    token = swap.bought if is_buy else swap.sold
    quote = swap.sold if is_buy else swap.bought
    if kind == "buy":
        event = EventType.BUY
    elif kind == "sell":
        event = EventType.SELL
    elif kind in {"transfer_in", "transferin"}:
        event = EventType.TRANSFER_IN
    elif kind in {"transfer_out", "transferout"}:
        event = EventType.TRANSFER_OUT
    else:
        event = EventType.UNKNOWN
    cost_usd = token.usd_amount if token.usd_amount is not None else swap.total_value_usd
    if cost_usd is not None:
        cost_usd = abs(cost_usd)
    cost_sol = None
    quote_sym = (quote.symbol or "").upper()
    if quote.address == WSOL_MINT or quote_sym in {"SOL", "WSOL"}:
        cost_sol = quote.amount
    if cost_usd is None and quote_sym in {"USDC", "USDT"} and quote.amount is not None:
        cost_usd = abs(quote.amount)
        if token.amount:
            token.usd_price = cost_usd / abs(token.amount)
    raw = dict(swap.raw or {})
    trade = TradeRecord(
        wallet_address=swap.wallet_address,
        chain=chain,
        token_address=token.address or swap.token_address,
        token_symbol=token.symbol or "未知",
        token_name=token.name or token.symbol or "未知",
        tx_hash=swap.transaction_hash,
        timestamp=swap.block_timestamp,
        event_type=event,
        token_amount=token.amount,
        price_usd=token.usd_price,
        cost_usd=cost_usd,
        cost_sol=cost_sol,
        gas_usd=None,
        gas_sol=None,
        launchpad_platform=None,
        raw=raw,
        quote_symbol=quote.symbol,
        quote_mint=quote.address,
        actual_quote_asset=quote.symbol or quote.address or None,
        actual_quote_amount=quote.amount,
        amount_status=FieldStatus.KNOWN if token.amount is not None else FieldStatus.UNRESOLVED,
        cost_usd_status=FieldStatus.KNOWN if cost_usd is not None else FieldStatus.UNRESOLVED,
        cost_sol_status=FieldStatus.KNOWN if cost_sol is not None else FieldStatus.NOT_APPLICABLE,
        gas_usd_status=FieldStatus.UNRESOLVED,
        gas_sol_status=FieldStatus.UNRESOLVED,
    )
    trade.activity_fingerprint = activity_fingerprint(
        chain,
        swap.wallet_address,
        {
            "tx_hash": swap.transaction_hash,
            "event_type": event.value,
            "timestamp": swap.block_timestamp,
            "token_amount": str(token.amount or ""),
            "cost_usd": str(cost_usd or ""),
            "token": {"address": token.address},
            "source": getattr(swap.source, "value", None) or str(swap.source or "helius"),
        },
    )
    return trade
