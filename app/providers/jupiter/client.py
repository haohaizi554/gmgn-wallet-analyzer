from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.domain.enums import ProviderCapability, ProviderHealth
from app.providers.base import DataProvider, IndependentRateLimiter
from app.providers.cache import ProviderCache
from app.providers.http import HttpProviderMixin
from app.providers.exceptions import ProviderError
from app.providers.market_quotes import MarketQuote, created_at_from, decimal_or_none, merge_quote_lists
from app.utils.money import to_decimal

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SEARCH_BATCH = 8
PRICE_BATCH = 50
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
        for i in range(0, len(pending), SEARCH_BATCH):
            chunk = pending[i : i + SEARCH_BATCH]
            url = f"{self.base_url}/tokens/v2/search"
            try:
                payload = self.http_request("GET", url, params={"query": ",".join(chunk)}, provider=self)
            except ProviderError:
                payload = []
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
        missing_price = [mint for mint in unique if not _quote_has_price(out, mint)]
        if missing_price:
            out = merge_quote_lists(out, self.get_price_quotes(missing_price))
        return out

    def get_price_quotes(self, mints: list[str]) -> list[MarketQuote]:
        unique: list[str] = []
        seen: set[str] = set()
        for mint in mints:
            if mint and mint not in seen:
                seen.add(mint)
                unique.append(mint)
        out: list[MarketQuote] = []
        for i in range(0, len(unique), PRICE_BATCH):
            chunk = unique[i : i + PRICE_BATCH]
            url = f"{self.base_url}/price/v3"
            try:
                payload = self.http_request("GET", url, params={"ids": ",".join(chunk)}, provider=self)
            except ProviderError:
                continue
            if not isinstance(payload, dict):
                continue
            for mint, item in payload.items():
                parsed = parse_price_v3(str(mint), item)
                if parsed:
                    out.append(parsed)
        return out

    def get_quote_usd_price(self, mint: str, decimals: int = 6):
        if not mint:
            return None
        amount = 10 ** max(0, int(decimals or 6))
        url = f"{self.base_url}/swap/v1/quote"
        try:
            payload = self.http_request(
                "GET",
                url,
                params={
                    "inputMint": mint,
                    "outputMint": USDC_MINT,
                    "amount": str(amount),
                    "slippageBps": "1500",
                },
                provider=self,
            )
        except ProviderError:
            return None
        if not isinstance(payload, dict):
            return None
        out_amount = to_decimal(payload.get("outAmount"))
        if out_amount in (None, 0):
            return None
        return out_amount / Decimal("1000000")

    def quote_usd_as_market(self, mint: str, decimals: int = 6) -> MarketQuote | None:
        price = self.get_quote_usd_price(mint, decimals=decimals)
        if price in (None, 0):
            return None
        return MarketQuote(mint=mint, price_usd=price, dex_id="jupiter-quote", source="jupiter", raw={"outAmountUsd": str(price)})

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


def parse_price_v3(mint: str, item: Any) -> MarketQuote | None:
    if not mint:
        return None
    if not isinstance(item, dict):
        return None
    price = to_decimal(item.get("usdPrice") or item.get("price"))
    return MarketQuote(
        mint=mint,
        price_usd=price,
        liquidity_usd=decimal_or_none(item.get("liquidity")),
        pair_created_at=created_at_from(item.get("createdAt")),
        dex_id=str(item.get("launchpad") or "jupiter"),
        symbol=str(item.get("symbol") or "").strip(),
        source="jupiter",
        raw=item,
    )


def _quote_has_price(quotes: list[MarketQuote], mint: str) -> bool:
    for quote in quotes:
        if quote.mint == mint and quote.price_usd not in (None, 0):
            return True
    return False
