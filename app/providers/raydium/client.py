from __future__ import annotations

from typing import Any

from app.domain.enums import ProviderCapability, ProviderHealth
from app.providers.base import DataProvider, IndependentRateLimiter
from app.providers.cache import ProviderCache
from app.providers.exceptions import ProviderError
from app.providers.http import HttpProviderMixin
from app.providers.market_quotes import MarketQuote
from app.utils.money import to_decimal

SOL_MINT = "So11111111111111111111111111111111111111112"
BATCH_SIZE = 40
QUOTE_TTL = 180


class RaydiumProvider(HttpProviderMixin, DataProvider):
    name = "raydium"
    optional = True
    capabilities = {
        ProviderCapability.TOKEN_MARKET,
    }

    def __init__(self, base_url: str = "https://api-v3.raydium.io", cache: ProviderCache | None = None, session=None):
        super().__init__()
        self.base_url = (base_url or "https://api-v3.raydium.io").rstrip("/")
        self.cache = cache
        self._shared_session = session
        self.limiter = IndependentRateLimiter(rate=2.0, capacity=4.0, min_spacing=0.3)
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
        for i in range(0, len(unique), BATCH_SIZE):
            chunk = unique[i : i + BATCH_SIZE]
            url = f"{self.base_url}/mint/price"
            try:
                payload = self.http_request("GET", url, params={"mints": ",".join(chunk)}, provider=self)
            except ProviderError:
                continue
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                continue
            for mint, value in data.items():
                price = to_decimal(value)
                if price in (None, 0):
                    continue
                out.append(
                    MarketQuote(
                        mint=str(mint),
                        price_usd=price,
                        dex_id="raydium",
                        source="raydium",
                        raw={"price": str(price)},
                    )
                )
        return out

    def get_sol_usd(self):
        quotes = self.get_token_quotes([SOL_MINT])
        for quote in quotes:
            if quote.price_usd not in (None, 0):
                return quote.price_usd
        return None

    def test_connection(self) -> dict[str, Any]:
        quotes = self.get_token_quotes([SOL_MINT])
        return {"ok": bool(quotes), "tokens": len(quotes)}
