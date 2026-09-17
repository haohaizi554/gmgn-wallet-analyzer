from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional


@dataclass
class BalanceChange:
    mint: str
    amount: Optional[Decimal]
    decimals: Optional[int] = None


@dataclass
class HistoryTx:
    signature: str
    timestamp: int = 0
    slot: Optional[int] = None
    fee_sol: Optional[Decimal] = None
    fee_payer: str = ""
    error: Any = None
    tx_type: str = ""
    balance_changes: list[BalanceChange] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenEvents:
    mint: str
    swaps: list[HistoryTx] = field(default_factory=list)
    transfers_in: list[HistoryTx] = field(default_factory=list)
    transfers_out: list[HistoryTx] = field(default_factory=list)
    earliest_activity: Optional[HistoryTx] = None
    earliest_buy: Optional[HistoryTx] = None
    latest_activity: Optional[HistoryTx] = None


@dataclass
class WalletHistoryIndex:
    wallet: str
    transactions: list[HistoryTx] = field(default_factory=list)
    token_events: dict[str, TokenEvents] = field(default_factory=dict)
    pages: int = 0
    source: str = "helius"
    bottom_complete: bool = False
