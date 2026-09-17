from __future__ import annotations

from decimal import Decimal
from typing import Optional

from app.domain.enums import DataSource, ResolutionStatus
from app.domain.evidence import ResolvedField, resolved, unresolved


def resolve_entry_market_cap(
    first_buy_price: Optional[Decimal],
    historical_supply: Optional[Decimal],
    current_supply: Optional[Decimal],
    supply_unchanged_proven: bool = False,
) -> ResolvedField:
    if first_buy_price is None:
        return unresolved(DataSource.LOCAL_CALCULATION, "无可验证历史市值", "entry_market_cap")
    if historical_supply is not None and historical_supply > 0:
        value = first_buy_price * historical_supply
        status = ResolutionStatus.VERIFIED if supply_unchanged_proven else ResolutionStatus.DERIVED
        return resolved(value, status, DataSource.LOCAL_CALCULATION, note="first_buy_price × historical_supply", field_name="entry_market_cap")
    if current_supply is not None and current_supply > 0:
        value = first_buy_price * current_supply
        return resolved(
            value,
            ResolutionStatus.ESTIMATED,
            DataSource.LOCAL_CALCULATION,
            note="使用当前供应量估算历史入场市值",
            estimated=True,
            field_name="entry_market_cap",
        )
    return unresolved(DataSource.LOCAL_CALCULATION, "历史供应量不可验证", "entry_market_cap")
