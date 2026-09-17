from __future__ import annotations

from math import ceil
from typing import Optional

# Official https://www.helius.dev/docs/billing/credits — do not invent costs.
KNOWN_METHOD_CREDITS: dict[str, int] = {
    "rpc": 1,
    "getHealth": 1,
    "getTransaction": 1,
    "getSignaturesForAddress": 1,
    "getTokenAccountsByOwner": 1,
    "getTokenSupply": 1,
    "getAccountInfo": 1,
    "getTokenAccountBalance": 1,
    "getBlockTime": 1,
    "getAsset": 10,
    "getAssetBatch": 10,
    "getTokenAccounts": 10,
    "enhanced_tx": 100,
    "wallet_history": 100,
    "wallet_transfers": 100,
    "wallet_balances": 100,
    "wallet_balance_at": 100,
    "getTransfersByAddress": 10,
}


def credits_for(method: str, *, returned: int | None = None, details: str = "") -> Optional[int]:
    key = (method or "").strip()
    if key == "getTransactionsForAddress":
        if details == "signatures":
            return 10
        count = max(0, int(returned or 0))
        if count <= 0:
            return 10
        return max(10, 10 * ceil(count / 100))
    if key in KNOWN_METHOD_CREDITS:
        return KNOWN_METHOD_CREDITS[key]
    return None
