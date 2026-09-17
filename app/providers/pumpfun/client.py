from __future__ import annotations

from typing import Any

from app.domain.enums import ProviderCapability, ProviderHealth
from app.providers.base import DataProvider, IndependentRateLimiter
from app.providers.cache import ProviderCache
from app.providers.http import HttpProviderMixin
from app.providers.market_quotes import MarketQuote, created_at_from, decimal_or_none
from app.utils.money import to_decimal

QUOTE_TTL = 180


class PumpFunProvider(HttpProviderMixin, DataProvider):
    name = "pumpfun"
    optional = True
    capabilities = {
        ProviderCapability.TOKEN_MARKET,
        ProviderCapability.LAUNCHPAD,
    }

    def __init__(self, base_url: str = "https://frontend-api.pump.fun", cache: ProviderCache | None = None, session=None):
        super().__init__()
        self.base_url = (base_url or "https://frontend-api.pump.fun").rstrip("/")
        self.cache = cache
        self._shared_session = session
        self.limiter = IndependentRateLimiter(rate=2.0, capacity=4.0, min_spacing=0.4)
        self.health = ProviderHealth.HEALTHY
        self.health_detail = "无需 API Key"
        self.enabled = True

    def get_token_quotes(self, mints: list[str]) -> list[MarketQuote]:
        out: list[MarketQuote] = []
        for mint in mints:
            if not mint:
                continue
            if self.cache:
                hit = self.cache.get(self.name, "TOKEN_MARKET", mint)
                if hit:
                    self.metrics.cache_hit += 1
                    parsed = parse_coin(hit)
                    if parsed:
                        out.append(parsed)
                    continue
            url = f"{self.base_url}/coins/{mint}"
            try:
                payload = self.http_request("GET", url, provider=self)
            except Exception:
                continue
            parsed = parse_coin(payload)
            if parsed is None:
                continue
            out.append(parsed)
            if self.cache:
                self.cache.set(self.name, "TOKEN_MARKET", mint, parsed.raw, QUOTE_TTL)
        return out

    def test_connection(self) -> dict[str, Any]:
        return {"ok": True, "detail": "optional"}


def parse_coin(item: Any) -> MarketQuote | None:
    if not isinstance(item, dict):
        return None
    mint = str(item.get("mint") or item.get("tokenAddress") or "").strip()
    if not mint:
        return None
    mcap = decimal_or_none(item.get("usd_market_cap") or item.get("market_cap"))
    created = created_at_from(item.get("created_timestamp") or item.get("createdAt"))
    return MarketQuote(
        mint=mint,
        price_usd=to_decimal(item.get("price_usd") or item.get("usd_price")),
        market_cap=mcap,
        fdv=mcap,
        pair_created_at=created,
        dex_id="pumpfun",
        symbol=str(item.get("symbol") or "").strip(),
        name=str(item.get("name") or "").strip(),
        source="pumpfun",
        raw=item,
    )
