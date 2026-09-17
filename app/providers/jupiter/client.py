from __future__ import annotations

from typing import Any

from app.domain.enums import ProviderCapability, ProviderHealth
from app.providers.base import DataProvider, IndependentRateLimiter
from app.providers.cache import ProviderCache
from app.providers.http import HttpProviderMixin
from app.providers.market_quotes import MarketQuote, created_at_from, decimal_or_none
from app.utils.money import to_decimal

SOL_MINT = "So11111111111111111111111111111111111111112"
BATCH_SIZE = 20
QUOTE_TTL = 180


class JupiterProvider(HttpProviderMixin, DataProvider):
    name = "jupiter"
    optional = True
    capabilities = {
        ProviderCapability.TOKEN_MARKET,
        ProviderCapability.TOKEN_POOLS,
        ProviderCapability.TOKEN_METADATA,
    }

    def __init__(self, base_url: str = "https://lite-api.jup.ag", cache: ProviderCache | None = None, session=None):
        super().__init__()
        self.base_url = (base_url or "https://lite-api.jup.ag").rstrip("/")
        self.cache = cache
        self._shared_session = session
        self.limiter = IndependentRateLimiter(rate=2.0, capacity=4.0, min_spacing=0.3)
        self.health = ProviderHealth.HEALTHY
        self.health_detail = "无需 API Key（lite-api）"
        self.enabled = True

    def get_token_quotes(self, mints: list[str]) -> list[MarketQuote]:
        unique: list[str] = []
        seen: set[str] = set()
        for mint in mints:
            if mint and mint not in seen:
                seen.add(mint)
                unique.append(mint)
        out: list[MarketQuote] = []
        pending: list[str] = []
        if self.cache:
            for mint in unique:
                hit = self.cache.get(self.name, "TOKEN_MARKET", mint)
                if hit:
                    self.metrics.cache_hit += 1
                    parsed = parse_token(hit)
                    if parsed:
                        out.append(parsed)
                else:
                    pending.append(mint)
        else:
            pending = unique
        for i in range(0, len(pending), BATCH_SIZE):
            chunk = pending[i : i + BATCH_SIZE]
            url = f"{self.base_url}/tokens/v2/search"
            payload = self.http_request("GET", url, params={"query": ",".join(chunk)}, provider=self)
            rows = payload if isinstance(payload, list) else []
            by_mint: dict[str, dict[str, Any]] = {}
            for item in rows:
                parsed = parse_token(item)
                if parsed is None:
                    continue
                out.append(parsed)
                by_mint[parsed.mint] = parsed.raw
            if self.cache:
                for mint in chunk:
                    if mint in by_mint:
                        self.cache.set(self.name, "TOKEN_MARKET", mint, by_mint[mint], QUOTE_TTL)
        return out

    def get_sol_usd(self):
        quotes = self.get_token_quotes([SOL_MINT])
        for quote in quotes:
            if quote.mint == SOL_MINT and quote.price_usd not in (None, 0):
                return quote.price_usd
        return None

    def test_connection(self) -> dict[str, Any]:
        quotes = self.get_token_quotes([SOL_MINT])
        return {"ok": bool(quotes), "tokens": len(quotes)}


def parse_token(item: Any) -> MarketQuote | None:
    if not isinstance(item, dict):
        return None
    mint = str(item.get("id") or item.get("address") or "").strip()
    if not mint:
        return None
    first_pool = item.get("firstPool") if isinstance(item.get("firstPool"), dict) else {}
    mcap = decimal_or_none(item.get("mcap"))
    fdv = decimal_or_none(item.get("fdv"))
    price = to_decimal(item.get("usdPrice"))
    supply = to_decimal(item.get("circSupply")) or to_decimal(item.get("totalSupply"))
    if mcap in (None, 0) and price not in (None, 0) and supply not in (None, 0):
        mcap = price * supply
    if fdv in (None, 0) and price not in (None, 0):
        total = to_decimal(item.get("totalSupply"))
        if total not in (None, 0):
            fdv = price * total
    return MarketQuote(
        mint=mint,
        price_usd=price,
        market_cap=mcap,
        fdv=fdv,
        liquidity_usd=decimal_or_none(item.get("liquidity")),
        pair_created_at=created_at_from(first_pool.get("createdAt") or item.get("firstPoolCreatedAt")),
        dex_id="jupiter",
        pair_address=str(first_pool.get("id") or ""),
        symbol=str(item.get("symbol") or "").strip(),
        name=str(item.get("name") or "").strip(),
        source="jupiter",
        raw=item,
    )
