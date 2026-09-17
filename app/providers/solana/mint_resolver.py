from __future__ import annotations

from typing import Optional

from app.providers.cache import ProviderCache
from app.providers.solana.rpc_client import SolanaRpcProvider
from app.providers.solana.transaction_parser import parse_verified_transaction

CREATION_TTL = 10 * 365 * 24 * 3600
INIT_HINTS = ("initializeMint", "initializeMint2", "InitializeMint", "create")


class MintCreationFinder:
    def __init__(self, rpc: SolanaRpcProvider, cache: ProviderCache | None = None) -> None:
        self.rpc = rpc
        self.cache = cache

    def find(self, mint: str, max_pages: int = 3) -> Optional[dict]:
        if self.cache:
            hit = self.cache.get("solana_rpc", "TOKEN_CREATION", mint)
            if hit:
                return hit
        before = None
        oldest = None
        for _ in range(max_pages):
            sigs = self.rpc.get_signatures_for_address(mint, limit=1000, before=before)
            if not sigs:
                break
            oldest = sigs[-1]
            if len(sigs) < 1000:
                break
            before = sigs[-1].get("signature")
        if not oldest:
            return None
        signature = str(oldest.get("signature") or "")
        raw = self.rpc.get_transaction(signature) if signature else None
        verified = parse_verified_transaction(raw, "", mint, signature)
        payload = {
            "mint": mint,
            "creation_signature": signature,
            "creation_time": verified.block_time or oldest.get("blockTime"),
            "slot": verified.slot or oldest.get("slot"),
            "source": "solana_rpc",
            "verified": bool(verified.found and verified.success),
        }
        if self.cache:
            self.cache.set("solana_rpc", "TOKEN_CREATION", mint, payload, CREATION_TTL)
        return payload
