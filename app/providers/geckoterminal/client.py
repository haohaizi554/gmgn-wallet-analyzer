from __future__ import annotations

from typing import Any

from app.domain.enums import ProviderCapability, ProviderHealth
from app.providers.base import DataProvider, IndependentRateLimiter
from app.providers.cache import ProviderCache
from app.providers.http import HttpProviderMixin
from app.providers.market_quotes import MarketQuote, decimal_or_none
from app.utils.money import to_decimal

BATCH_SIZE = 30
QUOTE_TTL = 180


class GeckoTerminalProvider(HttpProviderMixin, DataProvider):
    name = "geckoterminal"
    optional = True
    capabilities = {
        ProviderCapability.TOKEN_MARKET,
        ProviderCapability.TOKEN_POOLS,
    }

    def __init__(self, base_url: str = "https://api.geckoterminal.com/api/v2", cache: ProviderCache | None = None, session=None):
        super().__init__()
        self.base_url = (base_url or "https://api.geckoterminal.com/api/v2").rstrip("/")
        self.cache = cache
        self._shared_session = session
        self.limiter = IndependentRateLimiter(rate=1.5, capacity=3.0, min_spacing=0.7)
        self.health = ProviderHealth.HEALTHY
        self.health_detail = "无需 API Key"
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
            joined = ",".join(chunk)
            url = f"{self.base_url}/networks/solana/tokens/multi/{joined}"
            payload = self.http_request("GET", url, headers={"Accept": "application/json"}, provider=self)
            rows = _rows(payload)
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

    def test_connection(self) -> dict[str, Any]:
        quotes = self.get_token_quotes(["So11111111111111111111111111111111111111112"])
        return {"ok": bool(quotes), "tokens": len(quotes)}


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
    return []


def parse_token(item: Any) -> MarketQuote | None:
    if not isinstance(item, dict):
        return None
    attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else item
    mint = str(attrs.get("address") or item.get("id") or "").replace("solana_", "").strip()
    if not mint:
        return None
    price = to_decimal(attrs.get("price_usd"))
    mcap = decimal_or_none(attrs.get("market_cap_usd"))
    fdv = decimal_or_none(attrs.get("fdv_usd"))
    return MarketQuote(
        mint=mint,
        price_usd=price,
        market_cap=mcap,
        fdv=fdv,
        liquidity_usd=decimal_or_none(attrs.get("total_reserve_in_usd")),
        dex_id="geckoterminal",
        symbol=str(attrs.get("symbol") or "").strip(),
        name=str(attrs.get("name") or "").strip(),
        source="geckoterminal",
        raw=item,
    )
