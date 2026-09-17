from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from app.domain.enums import DataSource
from app.providers.result import HistoryCoverage


@dataclass
class QuoteLeg:
    mint: str = ""
    symbol: str = ""
    amount: Optional[Decimal] = None


@dataclass
class NormalizedSwap:
    signature: str
    timestamp: int
    base_mint: str
    base_symbol: str
    base_amount: Decimal
    quote_mint: str
    quote_symbol: str
    quote_amount: Decimal
    direction: str
    usd_amount: Optional[Decimal] = None
    usd_price: Optional[Decimal] = None
    source: DataSource = DataSource.MORALIS


@dataclass
class SwapLeg:
    address: str = ""
    name: str = ""
    symbol: str = ""
    amount: Optional[Decimal] = None
    usd_price: Optional[Decimal] = None
    usd_amount: Optional[Decimal] = None
    token_type: str = ""


@dataclass
class WalletSwap:
    transaction_hash: str
    transaction_type: str
    block_timestamp: int
    wallet_address: str
    pair_address: str = ""
    pair_label: str = ""
    exchange_address: str = ""
    exchange_name: str = ""
    bought: SwapLeg = field(default_factory=SwapLeg)
    sold: SwapLeg = field(default_factory=SwapLeg)
    total_value_usd: Optional[Decimal] = None
    source: DataSource = DataSource.MORALIS
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def token_address(self) -> str:
        side = self.transaction_type.lower()
        if side == "buy":
            return self.bought.address
        if side == "sell":
            return self.sold.address
        return self.bought.address or self.sold.address


@dataclass
class TokenSwapIndex:
    token_address: str
    buys: list[WalletSwap] = field(default_factory=list)
    sells: list[WalletSwap] = field(default_factory=list)
    transfers_in: list[WalletSwap] = field(default_factory=list)
    transfers_out: list[WalletSwap] = field(default_factory=list)
    earliest_buy: Optional[WalletSwap] = None
    latest_buy: Optional[WalletSwap] = None
    total_buy_usd: Optional[Decimal] = None
    total_sell_usd: Optional[Decimal] = None


@dataclass
class WalletSwapIndex:
    wallet: str
    by_token: dict[str, TokenSwapIndex] = field(default_factory=dict)
    swaps: list[WalletSwap] = field(default_factory=list)
    pages: int = 0
    coverage: HistoryCoverage | None = None
    provider: str = ""
    success: bool = True
    complete: bool = False
    fallback_used: bool = False
    from_cache: bool = False


@dataclass
class TokenMetadata:
    mint: str
    name: str = ""
    symbol: str = ""
    decimals: Optional[int] = None
    total_supply: Optional[Decimal] = None
    total_supply_formatted: Optional[Decimal] = None
    circulating_supply: Optional[Decimal] = None
    fully_diluted_value: Optional[Decimal] = None
    market_cap: Optional[Decimal] = None
    metadata_uri: str = ""
    update_authority: str = ""
    is_mutable: Optional[bool] = None
    is_verified_contract: Optional[bool] = None
    possible_spam: Optional[bool] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class WalletPortfolio:
    native_sol: Optional[Decimal] = None
    native_lamports: Optional[int] = None
    tokens: dict[str, Decimal] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
