from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.domain.enums import EventType, FieldStatus
from app.domain.models import TradeRecord
from app.utils.money import to_decimal


@dataclass
class CostLot:
    amount: Decimal
    cost_usd: Optional[Decimal]
    timestamp: int
    tx_hash: str
    known_cost: bool


@dataclass
class FifoResult:
    trades: list[TradeRecord]
    realized_profit: Optional[Decimal]
    missing_cost_count: int
    missing_cost_sell_count: int
    missing_cost_token_amount: Decimal
    missing_cost_usd: Optional[Decimal]
    current_balance: Decimal
    last_sell_ts: Optional[int]


def apply_fifo(trades: list[TradeRecord]) -> FifoResult:
    ordered = sorted(trades, key=lambda t: (t.timestamp, t.tx_hash, t.event_type.value, t.activity_fingerprint))
    lots: deque[CostLot] = deque()
    missing_sells = 0
    missing_amount = Decimal("0")
    missing_usd = Decimal("0")
    has_missing_usd = False
    realized: Optional[Decimal] = Decimal("0")
    last_sell = None
    has_verified_sell = False

    for trade in ordered:
        amount = to_decimal(trade.token_amount) or Decimal("0")
        if trade.event_type in (EventType.BUY, EventType.ADD):
            lots.append(
                CostLot(
                    amount=amount,
                    cost_usd=trade.cost_usd,
                    timestamp=trade.timestamp,
                    tx_hash=trade.tx_hash,
                    known_cost=trade.cost_usd is not None,
                )
            )
            trade.single_pnl_display = "未实现"
            trade.missing_cost = False
            continue
        if trade.event_type == EventType.TRANSFER_IN:
            lots.append(
                CostLot(
                    amount=amount,
                    cost_usd=None,
                    timestamp=trade.timestamp,
                    tx_hash=trade.tx_hash,
                    known_cost=False,
                )
            )
            trade.single_pnl_display = "不适用（转入）"
            trade.missing_cost = True
            continue
        if trade.event_type in (EventType.SELL, EventType.REMOVE, EventType.TRANSFER_OUT):
            remaining = amount
            matched_cost = Decimal("0")
            unverifiable = False
            unknown_matched = Decimal("0")
            while remaining > 0 and lots:
                lot = lots[0]
                take = min(lot.amount, remaining)
                if lot.known_cost and lot.cost_usd is not None and lot.amount > 0:
                    matched_cost += lot.cost_usd * take / lot.amount
                    lot.cost_usd -= lot.cost_usd * take / lot.amount
                else:
                    unverifiable = True
                    unknown_matched += take
                lot.amount -= take
                remaining -= take
                if lot.amount <= 0:
                    lots.popleft()
            if remaining > 0:
                unverifiable = True
            if trade.event_type == EventType.SELL:
                last_sell = trade.timestamp
                gap = remaining + unknown_matched
                if unverifiable or trade.cost_usd is None:
                    if gap > 0 or trade.cost_usd is None:
                        missing_sells += 1
                        missing_amount += gap if gap > 0 else amount
                        if trade.price_usd is not None and gap > 0:
                            missing_usd += trade.price_usd * gap
                            has_missing_usd = True
                        elif trade.cost_usd is not None and amount > 0 and gap > 0:
                            missing_usd += trade.cost_usd * gap / amount
                            has_missing_usd = True
                    trade.single_pnl_display = "无法验证历史成本" if unverifiable else "GMGN 未提供"
                    trade.missing_cost = True
                else:
                    pnl = trade.cost_usd - matched_cost
                    trade.single_pnl_display = format(pnl, "f")
                    trade.missing_cost = False
                    realized = (realized or Decimal("0")) + pnl
                    has_verified_sell = True
            elif trade.event_type == EventType.TRANSFER_OUT:
                trade.single_pnl_display = "不适用（转出）"
                trade.missing_cost = unverifiable
            else:
                trade.single_pnl_display = "未实现"
            continue
        trade.single_pnl_display = "未实现"

    balance = sum((lot.amount for lot in lots), Decimal("0"))
    return FifoResult(
        trades=ordered,
        realized_profit=realized if has_verified_sell else None,
        missing_cost_count=missing_sells,
        missing_cost_sell_count=missing_sells,
        missing_cost_token_amount=missing_amount,
        missing_cost_usd=missing_usd if has_missing_usd else None,
        current_balance=balance,
        last_sell_ts=last_sell,
    )
