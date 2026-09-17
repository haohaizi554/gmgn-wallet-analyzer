from __future__ import annotations

from typing import Any

from app.domain.enums import ProviderCapability, ProviderHealth
from app.providers.base import DataProvider, IndependentRateLimiter
from app.providers.cache import ProviderCache
from app.providers.exceptions import ProviderError
from app.providers.http import HttpProviderMixin
from app.providers.market_quotes import MarketQuote, decimal_or_none
from app.utils.money import to_decimal

SOL_MINT = "So11111111111111111111111111111111111111112"
BATCH_SIZE = 50
QUOTE_TTL = 180


class DefiLlamaProvider(HttpProviderMixin, DataProvider):
    name = "defillama"
    optional = True
    capabilities = {
        ProviderCapability.TOKEN_MARKET,
    }

    def __init__(self, base_url: str = "https://coins.llama.fi", cache: ProviderCache | None = None, session=None):
        super().__init__()
        self.base_url = (base_url or "https://coins.llama.fi").rstrip("/")
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
            ids = ",".join(f"solana:{mint}" for mint in chunk)
            url = f"{self.base_url}/prices/current/{ids}"
            try:
                payload = self.http_request("GET", url, provider=self)
            except ProviderError:
                continue
            coins = payload.get("coins") if isinstance(payload, dict) else None
            if not isinstance(coins, dict):
                continue
            for key, item in coins.items():
                mint = str(key).split(":", 1)[-1]
                parsed = parse_coin(mint, item)
                if parsed:
                    out.append(parsed)
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


def parse_coin(mint: str, item: Any) -> MarketQuote | None:
    if not mint or not isinstance(item, dict):
        return None
    price = to_decimal(item.get("price"))
    if price in (None, 0):
        return None
    return MarketQuote(
        mint=mint,
        price_usd=price,
        symbol=str(item.get("symbol") or "").strip(),
        dex_id="defillama",
        source="defillama",
        raw=item,
        liquidity_usd=decimal_or_none(item.get("confidence")),
    )
