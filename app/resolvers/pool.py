from __future__ import annotations

from decimal import Decimal
from typing import Optional

from app.providers.dexscreener.parsers import DexPair


def select_primary_pool(pairs: list[DexPair], mint: str = "") -> Optional[DexPair]:
    scored: list[tuple[Decimal, int, DexPair]] = []
    for pair in pairs:
        if mint and pair.base_address != mint and pair.quote_address != mint:
            continue
        liq = pair.liquidity_usd or Decimal("0")
        complete = 0
        if pair.pair_address:
            complete += 1
        if pair.price_usd is not None:
            complete += 1
        if pair.dex_id:
            complete += 1
        if pair.liquidity_usd is not None:
            complete += 1
        if complete < 2:
            continue
        scored.append((liq, complete, pair))
    if not scored:
        usable = [p for p in pairs if p.pair_address]
        return usable[0] if usable else (pairs[0] if pairs else None)
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return scored[0][2]
