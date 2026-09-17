from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.domain.enums import ProviderCapability, ProviderHealth
from app.providers.base import DataProvider, IndependentRateLimiter
from app.providers.cache import ProviderCache
from app.providers.dexscreener.parsers import DexPair, parse_pairs
from app.providers.http import HttpProviderMixin

BATCH_SIZE = 30
POOL_TTL = 1800
MARKET_TTL = 180


class DexScreenerProvider(HttpProviderMixin, DataProvider):
    name = "dexscreener"
    optional = False
    capabilities = {
        ProviderCapability.TOKEN_POOLS,
        ProviderCapability.TOKEN_MARKET,
    }

    def __init__(self, base_url: str = "https://api.dexscreener.com", cache: ProviderCache | None = None, session=None, chain_id: str = "solana"):
        super().__init__()
        self.base_url = (base_url or "https://api.dexscreener.com").rstrip("/")
        self.cache = cache
        self.chain_id = chain_id
        self._shared_session = session
        self.limiter = IndependentRateLimiter(rate=4.0, capacity=8.0, min_spacing=0.2)
        self.health = ProviderHealth.HEALTHY
        self.health_detail = "无需 API Key"
        self.enabled = True

    def get_token_pairs(self, token_address: str) -> list[DexPair]:
        url = f"{self.base_url}/token-pairs/v1/{self.chain_id}/{token_address}"
        payload = self.http_request("GET", url, provider=self)
        return parse_pairs(payload)

    def get_tokens_batch(self, mints: list[str]) -> dict[str, list[DexPair]]:
        unique: list[str] = []
        seen: set[str] = set()
        for mint in mints:
            if mint and mint not in seen:
                seen.add(mint)
                unique.append(mint)
        grouped: dict[str, list[DexPair]] = defaultdict(list)
        pending: list[str] = []
        if self.cache:
            for mint in unique:
                hit = self.cache.get(self.name, "TOKEN_POOLS", mint)
                if hit:
                    self.metrics.cache_hit += 1
                    grouped[mint].extend(parse_pairs(hit))
                else:
                    pending.append(mint)
        else:
            pending = unique
        for i in range(0, len(pending), BATCH_SIZE):
            chunk = pending[i : i + BATCH_SIZE]
            joined = ",".join(chunk)
            url = f"{self.base_url}/tokens/v1/{self.chain_id}/{joined}"
            payload = self.http_request("GET", url, provider=self)
            pairs = parse_pairs(payload)
            by_mint: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for pair in pairs:
                for mint in (pair.base_address, pair.quote_address):
                    if mint in seen:
                        grouped[mint].append(pair)
                        by_mint[mint].append(pair.raw)
            if self.cache:
                for mint in chunk:
                    self.cache.set(self.name, "TOKEN_POOLS", mint, by_mint.get(mint, []), POOL_TTL)
        return dict(grouped)

    def test_connection(self) -> dict[str, Any]:
        pairs = self.get_token_pairs("So11111111111111111111111111111111111111112")
        return {"ok": True, "pairs": len(pairs)}
