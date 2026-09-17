from __future__ import annotations

import hashlib
from typing import Any


def _s(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def activity_fingerprint(chain: str, wallet: str, item: dict[str, Any]) -> str:
    """Deterministic id for a GMGN activity row.

    Live wallet_activity JSON (2026-09) has no activity_id/log_index.
    Same tx_hash + token + event_type can still be two swaps (different amounts).
    """
    token = item.get("token") if isinstance(item.get("token"), dict) else {}
    official = item.get("activity_id") or item.get("id") or item.get("event_id")
    if official not in (None, ""):
        return f"gmgn:{_s(official)}"
    parts = [
        _s(chain),
        _s(wallet),
        _s(item.get("tx_hash") or item.get("transaction_hash") or item.get("hash")),
        _s(token.get("address") or token.get("token_address") or item.get("token_address") or item.get("base_address")),
        _s(item.get("event_type") or item.get("type") or item.get("side")),
        _s(item.get("timestamp") or item.get("block_unix_time")),
        _s(item.get("token_amount") or item.get("amount") or item.get("base_amount")),
        _s(item.get("cost_usd") or item.get("amount_usd")),
        _s(item.get("price_usd")),
        _s(item.get("gas_usd")),
        _s(item.get("quote_amount")),
        _s(item.get("from_address")),
        _s(item.get("to_address")),
        _s(item.get("is_open_or_close")),
        _s(item.get("event_index") or item.get("log_index") or item.get("swap_index") or item.get("instruction_index")),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
