from __future__ import annotations

from typing import Any

from app.domain.enums import ProviderCapability, ProviderHealth
from app.providers.base import DataProvider, IndependentRateLimiter
from app.providers.cache import ProviderCache
from app.providers.exceptions import ProviderError
from app.providers.http import HttpProviderMixin
from app.providers.market_quotes import MarketQuote, created_at_from, decimal_or_none, merge_quote_lists
from app.utils.money import to_decimal

BATCH_SIZE = 20
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
            out = merge_quote_lists(out, self._fetch_multi_or_singles(chunk))
        missing = [mint for mint in unique if not _has_price(out, mint)]
        if missing:
            out = merge_quote_lists(out, self._fetch_pools(missing))
        if self.cache:
            for quote in out:
                if quote.raw:
                    self.cache.set(self.name, "TOKEN_MARKET", quote.mint, quote.raw, QUOTE_TTL)
        return out

    def _fetch_multi_or_singles(self, chunk: list[str]) -> list[MarketQuote]:
        joined = ",".join(chunk)
        url = f"{self.base_url}/networks/solana/tokens/multi/{joined}"
        try:
            payload = self.http_request("GET", url, headers={"Accept": "application/json"}, provider=self)
            return [parsed for item in _rows(payload) if (parsed := parse_token(item))]
        except ProviderError as exc:
            if exc.status == 429:
                raise
        return self._fetch_singles(chunk)

    def _fetch_singles(self, mints: list[str]) -> list[MarketQuote]:
        out: list[MarketQuote] = []
        for mint in mints:
            url = f"{self.base_url}/networks/solana/tokens/{mint}"
            try:
                payload = self.http_request("GET", url, headers={"Accept": "application/json"}, provider=self)
            except ProviderError as exc:
                if exc.status == 429:
                    raise
                continue
            parsed = parse_token(payload if isinstance(payload, dict) else {})
            if parsed is None:
                for item in _rows(payload):
                    parsed = parse_token(item)
                    if parsed:
                        break
            if parsed:
                out.append(parsed)
        return out

    def _fetch_pools(self, mints: list[str]) -> list[MarketQuote]:
        out: list[MarketQuote] = []
        for mint in mints:
            url = f"{self.base_url}/networks/solana/tokens/{mint}/pools"
            try:
                payload = self.http_request(
                    "GET",
                    url,
                    params={"page": 1},
                    headers={"Accept": "application/json"},
                    provider=self,
                )
            except ProviderError as exc:
                if exc.status == 429:
                    raise
                continue
            parsed = parse_pool_quote(mint, payload)
            if parsed:
                out.append(parsed)
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


def parse_pool_quote(mint: str, payload: Any) -> MarketQuote | None:
    best: MarketQuote | None = None
    best_liq = None
    for item in _rows(payload):
        attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else item
        price = to_decimal(attrs.get("base_token_price_usd") or attrs.get("quote_token_price_usd") or attrs.get("token_price_usd"))
        liq = decimal_or_none(attrs.get("reserve_in_usd") or attrs.get("base_token_price_native_currency"))
        mcap = decimal_or_none(attrs.get("market_cap_usd"))
        fdv = decimal_or_none(attrs.get("fdv_usd"))
        created = created_at_from(attrs.get("pool_created_at") or attrs.get("created_at"))
        quote = MarketQuote(
            mint=mint,
            price_usd=price,
            market_cap=mcap,
            fdv=fdv,
            liquidity_usd=liq,
            pair_created_at=created,
            dex_id=str(attrs.get("name") or "geckoterminal"),
            pair_address=str(attrs.get("address") or item.get("id") or ""),
            source="geckoterminal",
            raw=item,
        )
        if quote.price_usd in (None, 0) and quote.market_cap in (None, 0) and quote.fdv in (None, 0):
            continue
        score = liq or 0
        if best is None or score > (best_liq or 0):
            best = quote
            best_liq = score
    return best


def _has_price(quotes: list[MarketQuote], mint: str) -> bool:
    for quote in quotes:
        if quote.mint == mint and quote.price_usd not in (None, 0):
            return True
    return False
