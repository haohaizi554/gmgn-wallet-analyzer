from __future__ import annotations

from typing import Any, Optional

from app.domain.enums import ProviderCapability, ProviderHealth
from app.providers.base import DataProvider, IndependentRateLimiter, ProviderCircuitBreaker, ProviderRetryPolicy
from app.providers.cache import ProviderCache
from app.providers.exceptions import ProviderAuthError, ProviderError
from app.providers.http import HttpProviderMixin
from app.providers.moralis.models import TokenMetadata, WalletPortfolio, WalletSwap
from app.providers.moralis.parsers import parse_metadata_batch, parse_portfolio, parse_swaps_page
from app.utils.logger import get_logger

logger = get_logger("gmgn.moralis")

METADATA_BATCH_SIZE = 100
SWAPS_TTL = 7 * 24 * 3600
METADATA_TTL = 24 * 3600
PORTFOLIO_TTL = 120


class MoralisProvider(HttpProviderMixin, DataProvider):
    name = "moralis"
    optional = False
    capabilities = {
        ProviderCapability.WALLET_SWAPS,
        ProviderCapability.WALLET_BALANCES,
        ProviderCapability.TOKEN_METADATA,
        ProviderCapability.TOKEN_MARKET,
        ProviderCapability.HISTORICAL_PRICE,
    }

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://solana-gateway.moralis.io",
        network: str = "mainnet",
        cache: ProviderCache | None = None,
        session=None,
        rate: float = 8.0,
        api_keys: list[str] | None = None,
        enabled_flag: bool = True,
    ) -> None:
        super().__init__()
        keys = [k.strip() for k in (api_keys or []) if k and k.strip()]
        primary = (api_key or "").strip()
        if primary and primary not in keys:
            keys.insert(0, primary)
        self.api_keys = keys
        self._key_index = 0
        self.api_key = self.api_keys[0] if self.api_keys else ""
        self.base_url = (base_url or "https://solana-gateway.moralis.io").rstrip("/")
        self.network = network or "mainnet"
        self.cache = cache
        self._shared_session = session
        self.limiter = IndependentRateLimiter(rate=rate, capacity=rate, min_spacing=0.05)
        self.circuit = ProviderCircuitBreaker(failure_threshold=3, open_seconds=30.0)
        self.retry_policy = ProviderRetryPolicy()
        if not enabled_flag:
            self.health = ProviderHealth.DISABLED
            self.health_detail = "ENABLE_MORALIS=false"
            self.enabled = False
            self.optional = True
        elif self.api_key:
            self.health = ProviderHealth.HEALTHY
            self.health_detail = f"已配置 {len(self.api_keys)} 把 Key"
            self.enabled = True
            self.optional = False
        else:
            self.health = ProviderHealth.NOT_CONFIGURED
            self.health_detail = "未配置 MORALIS_API_KEY"
            self.enabled = False
            self.optional = True

    def _rotate_key(self) -> None:
        if len(self.api_keys) <= 1:
            return
        self._key_index = (self._key_index + 1) % len(self.api_keys)
        self.api_key = self.api_keys[self._key_index]
        logger.info("Moralis 轮换 Key -> ****%s", self.api_key[-4:] if len(self.api_key) >= 4 else "")

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key, "Accept": "application/json", "Content-Type": "application/json"}

    def get_wallet_swaps(
        self,
        wallet: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
        order: str = "DESC",
        from_date: str | int | None = None,
        to_date: str | int | None = None,
        transaction_types: str = "buy,sell",
        token_address: str | None = None,
    ) -> tuple[list[WalletSwap], Optional[str]]:
        params: dict[str, Any] = {
            "limit": max(1, min(100, int(limit))),
            "order": order if order in ("ASC", "DESC") else "DESC",
            "transactionTypes": transaction_types or "buy,sell",
        }
        if cursor:
            params["cursor"] = cursor
        if from_date not in (None, "", 0):
            params["fromDate"] = str(from_date)
        if to_date not in (None, "", 0):
            params["toDate"] = str(to_date)
        if token_address:
            params["tokenAddress"] = token_address
        url = f"{self.base_url}/account/{self.network}/{wallet}/swaps"
        payload = self._request_rotating("GET", url, params=params)
        return parse_swaps_page(payload, wallet)

    def _request_rotating(self, method: str, url: str, **kwargs: Any) -> Any:
        from app.providers.exceptions import ProviderAuthError, ProviderRateLimitError

        last: Exception | None = None
        attempts = max(1, len(self.api_keys) or 1)
        for _ in range(attempts):
            try:
                return self.http_request(method, url, headers=self._headers(), provider=self, **kwargs)
            except (ProviderAuthError, ProviderRateLimitError) as exc:
                last = exc
                if attempts == 1:
                    raise
                self._rotate_key()
        if last:
            raise last
        raise ProviderError("Moralis 请求失败", provider=self.name)

    def iter_wallet_swaps(self, wallet: str, until_signature: str | None = None, **kwargs: Any) -> tuple[list[WalletSwap], int, bool]:
        swaps: list[WalletSwap] = []
        cursor = None
        pages = 0
        seen: set[str] = set()
        hit_known = False
        truncated = False
        while True:
            page, nxt = self.get_wallet_swaps(wallet, cursor=cursor, **kwargs)
            pages += 1
            for item in page:
                if until_signature and item.transaction_hash == until_signature:
                    hit_known = True
                    break
                key = f"{item.transaction_hash}:{item.transaction_type}:{item.token_address}:{item.block_timestamp}"
                if key in seen:
                    continue
                seen.add(key)
                swaps.append(item)
            if hit_known:
                break
            if not nxt:
                break
            cursor = nxt
            if pages > 500:
                logger.warning("Moralis swaps 分页超过 500 页，提前停止 wallet=%s", wallet[:8])
                truncated = True
                break
        complete = (not truncated) and (hit_known or not nxt)
        return swaps, pages, complete

    def earliest_buy(self, wallet: str, token_address: str) -> Optional[WalletSwap]:
        page, _ = self.get_wallet_swaps(
            wallet,
            limit=1,
            order="ASC",
            transaction_types="buy",
            token_address=token_address,
        )
        return page[0] if page else None

    def get_metadata_batch(self, mints: list[str]) -> list[TokenMetadata]:
        unique: list[str] = []
        seen: set[str] = set()
        for mint in mints:
            if not mint or mint in seen:
                continue
            seen.add(mint)
            unique.append(mint)
        results: list[TokenMetadata] = []
        for i in range(0, len(unique), METADATA_BATCH_SIZE):
            chunk = unique[i : i + METADATA_BATCH_SIZE]
            cached: list[TokenMetadata] = []
            missing: list[str] = []
            if self.cache:
                for mint in chunk:
                    hit = self.cache.get(self.name, "TOKEN_METADATA", mint)
                    if hit:
                        self.metrics.cache_hit += 1
                        parsed = parse_metadata_batch([hit])
                        if parsed:
                            cached.append(parsed[0])
                            continue
                    missing.append(mint)
            else:
                missing = chunk
            if missing:
                url = f"{self.base_url}/token/{self.network}/metadata"
                payload = self.http_request(
                    "POST",
                    url,
                    json_body={"addresses": missing},
                    headers=self._headers(),
                    provider=self,
                )
                parsed = parse_metadata_batch(payload)
                if self.cache:
                    by_mint = {item.mint: item for item in parsed}
                    for mint in missing:
                        item = by_mint.get(mint)
                        if item:
                            self.cache.set(self.name, "TOKEN_METADATA", mint, item.raw, METADATA_TTL)
                results.extend(parsed)
            results.extend(cached)
        return results

    def get_portfolio(self, wallet: str) -> WalletPortfolio:
        url = f"{self.base_url}/account/{self.network}/{wallet}/portfolio"
        payload = self.http_request("GET", url, params={"nftMetadata": "false"}, headers=self._headers(), provider=self)
        return parse_portfolio(payload)

    def test_connection(self) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderAuthError("未配置 Moralis API Key", provider=self.name, status=401)
        url = f"{self.base_url}/account/{self.network}/So11111111111111111111111111111111111111112/balance"
        try:
            payload = self.http_request("GET", url, headers=self._headers(), provider=self)
        except ProviderError:
            payload = self.get_metadata_batch(["So11111111111111111111111111111111111111112"])
            return {"ok": True, "sample": "metadata", "count": len(payload)}
        return payload if isinstance(payload, dict) else {"ok": True}
