from __future__ import annotations

from typing import Any, Optional

from app.domain.enums import HeliusCapStatus, ProviderCapability, ProviderHealth
from app.providers.base import DataProvider, IndependentRateLimiter
from app.providers.cache import ProviderCache
from app.providers.exceptions import ProviderAuthError, ProviderError, ProviderPlanError
from app.providers.helius.capabilities import CAP_TTL, PROBE_CAPS, USDC, apply_probe_result, _status_from_exc
from app.providers.helius.credit_tracker import HeliusCreditTracker
from app.providers.helius.history import build_index
from app.providers.helius.models import WalletHistoryIndex
from app.providers.helius.wallet_api import HeliusWalletApi
from app.providers.http import HttpProviderMixin
from app.utils.logger import get_logger
from app.utils.time_utils import now_ts

logger = get_logger("gmgn.helius")
OFFICIAL_RPC = "https://mainnet.helius-rpc.com"


class HeliusProvider(HeliusWalletApi, HttpProviderMixin, DataProvider):
    name = "helius"
    optional = True
    capabilities: set[ProviderCapability] = set()

    def __init__(
        self,
        api_key: str = "",
        rpc_url: str = "",
        cache: ProviderCache | None = None,
        session=None,
        target_rps: float = 8.0,
        rest_rps: float = 1.6,
        monthly_budget: int = 1_000_000,
        credits: HeliusCreditTracker | None = None,
    ) -> None:
        super().__init__()
        self.api_key = (api_key or "").strip()
        self.rest_base = "https://api.helius.xyz"
        if rpc_url:
            self.rpc_url = rpc_url.rstrip("/")
        elif self.api_key:
            self.rpc_url = f"{OFFICIAL_RPC}/?api-key={self.api_key}"
        else:
            self.rpc_url = ""
        self._shared_session = session
        self.cache = cache
        self.rpc_limiter = IndependentRateLimiter(rate=max(0.5, float(target_rps)), capacity=max(1.0, float(target_rps)), min_spacing=0.05)
        self.rest_limiter = IndependentRateLimiter(rate=max(0.2, float(rest_rps)), capacity=max(1.0, float(rest_rps)), min_spacing=0.2)
        self.limiter = self.rpc_limiter
        self.credits = credits or HeliusCreditTracker(monthly_budget=monthly_budget)
        self.cap_flags = {k: False for k in PROBE_CAPS}
        self.cap_status: dict[str, str] = {k: HeliusCapStatus.NOT_CONFIGURED.value for k in PROBE_CAPS}
        self.probed = False
        self.history_pages = 0
        if not self.api_key:
            self.health = ProviderHealth.NOT_CONFIGURED
            self.health_detail = "NOT CONFIGURED (Optional)"
            self.enabled = False
            self.optional = True
        else:
            self.health = ProviderHealth.HEALTHY
            self.health_detail = "已配置，尚未探测套餐"
            self.enabled = True
            self.capabilities = {ProviderCapability.TRANSACTION_DETAIL}

    def _use_rpc(self) -> None:
        self.limiter = self.rpc_limiter

    def _use_rest(self) -> None:
        self.limiter = self.rest_limiter

    def ensure_probed(self, repos=None, force: bool = False) -> dict[str, str]:
        if not self.api_key:
            return dict(self.cap_status)
        if not force and self.probed:
            return dict(self.cap_status)
        if repos and not force:
            cached = repos.get_helius_capabilities() if hasattr(repos, "get_helius_capabilities") else None
            if cached:
                self.cap_status = cached
                apply_probe_result(self, cached)
                self.probed = True
                return dict(self.cap_status)
        result = self.probe_capabilities()
        if repos and hasattr(repos, "save_helius_capabilities"):
            repos.save_helius_capabilities(result)
        return result

    def probe_capabilities(self) -> dict[str, str]:
        result = {k: HeliusCapStatus.NOT_CONFIGURED.value for k in PROBE_CAPS}
        if not self.api_key:
            self.health = ProviderHealth.NOT_CONFIGURED
            return result
        self.probed = True
        result["RPC"] = self._probe_rpc()
        result["DAS"] = self._probe_das()
        result["WALLET_HISTORY"] = self._probe_wallet("/v1/wallet/11111111111111111111111111111111/history")
        result["WALLET_TRANSFERS"] = self._probe_wallet("/v1/wallet/11111111111111111111111111111111/transfers")
        result["WALLET_BALANCES"] = self._probe_wallet("/v1/wallet/11111111111111111111111111111111/balances")
        result["GTFA"] = self._probe_gtfa()
        result["ENHANCED_TRANSACTIONS"] = self._probe_enhanced()
        result["ARCHIVAL"] = result["RPC"]
        self.cap_status = result
        apply_probe_result(self, result)
        logger.info("Helius capabilities %s", result)
        return result

    def _probe_rpc(self) -> str:
        try:
            payload = self.rpc_call("getHealth", [])
            return self._jsonrpc_cap_status(payload, default_available=True)
        except Exception as exc:
            return _status_from_exc(exc).value

    def _probe_das(self) -> str:
        try:
            self._use_rpc()
            payload = self.http_request(
                "POST",
                self.rpc_url,
                json_body={"jsonrpc": "2.0", "id": 1, "method": "getAsset", "params": {"id": USDC}},
                headers={"Content-Type": "application/json"},
                provider=self,
            )
            self.credits.record("getAsset")
            return self._jsonrpc_cap_status(payload)
        except Exception as exc:
            return _status_from_exc(exc).value

    def _jsonrpc_cap_status(self, payload: Any, default_available: bool = False) -> str:
        if isinstance(payload, dict) and payload.get("error"):
            err = payload.get("error") or {}
            text = str(err).lower()
            code = err.get("code") if isinstance(err, dict) else None
            if code == -32601 or "not found" in text or "not available" in text or "upgrade" in text:
                return HeliusCapStatus.PLAN_UNAVAILABLE.value
            if "unauthorized" in text or "forbidden" in text:
                return HeliusCapStatus.AUTH_FAILED.value
            return HeliusCapStatus.UNKNOWN.value
        return HeliusCapStatus.AVAILABLE.value

    def _probe_wallet(self, path: str) -> str:
        try:
            self._use_rest()
            self.http_request(
                "GET",
                f"{self.rest_base}{path}",
                params={"api-key": self.api_key, "limit": 1},
                provider=self,
            )
            self.credits.record("wallet_history" if path.endswith("history") else ("wallet_transfers" if path.endswith("transfers") else "wallet_balances"))
            return HeliusCapStatus.AVAILABLE.value
        except ProviderError as exc:
            if getattr(exc, "status", None) == 400:
                return HeliusCapStatus.AVAILABLE.value
            return _status_from_exc(exc).value
        except Exception as exc:
            return _status_from_exc(exc).value

    def _probe_gtfa(self) -> str:
        try:
            self._use_rpc()
            payload = self.http_request(
                "POST",
                self.rpc_url,
                json_body={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTransactionsForAddress",
                    "params": ["11111111111111111111111111111111", {"transactionDetails": "signatures", "limit": 1, "sortOrder": "asc"}],
                },
                headers={"Content-Type": "application/json"},
                provider=self,
            )
            self.credits.record("getTransactionsForAddress", returned=0, details="signatures")
            return self._jsonrpc_cap_status(payload)
        except Exception as exc:
            return _status_from_exc(exc).value

    def _probe_enhanced(self) -> str:
        try:
            self._use_rest()
            self.http_request(
                "GET",
                f"{self.rest_base}/v0/addresses/11111111111111111111111111111111/transactions",
                params={"api-key": self.api_key, "limit": 1},
                provider=self,
            )
            self.credits.record("enhanced_tx")
            return HeliusCapStatus.AVAILABLE.value
        except Exception as exc:
            return _status_from_exc(exc).value

    def collect_history(
        self,
        wallet: str,
        *,
        start_ts: int = 0,
        end_ts: int = 0,
        max_transactions: int = 0,
        max_pages: int = 80,
        until_signature: str | None = None,
    ) -> WalletHistoryIndex:
        if not self.cap_flags.get("WALLET_HISTORY"):
            raise ProviderPlanError("Wallet History 当前不可用", provider=self.name, status=403)
        txs = []
        before = None
        pages = 0
        hit_known = False
        while pages < max_pages:
            page, nxt, has_more = self.get_wallet_history_page(wallet, before=before, limit=100)
            pages += 1
            self.history_pages += 1
            if not page:
                break
            stop = False
            for item in page:
                if until_signature and item.signature == until_signature:
                    hit_known = True
                    stop = True
                    break
                txs.append(item)
                if max_transactions and len(txs) >= max_transactions:
                    stop = True
                    break
            if stop or not has_more or not nxt:
                bottom = (not has_more and not bool(max_transactions)) or hit_known
                return build_index(wallet, txs, source="helius_wallet_api", pages=pages, bottom_complete=bottom)
            before = nxt
        return build_index(wallet, txs, source="helius_wallet_api", pages=pages, bottom_complete=False)

    def rpc_call(self, method: str, params: Any) -> Any:
        self._use_rpc()
        payload = self.http_request(
            "POST",
            self.rpc_url,
            json_body={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            headers={"Content-Type": "application/json"},
            provider=self,
        )
        from app.providers.helius.credit_policy import KNOWN_METHOD_CREDITS

        self.credits.record(method if method in KNOWN_METHOD_CREDITS or method == "getTransactionsForAddress" else "rpc")
        if isinstance(payload, dict) and payload.get("error"):
            raise ProviderError(f"Helius RPC {method} error: {payload.get('error')}", provider=self.name, status=200)
        return payload.get("result") if isinstance(payload, dict) else payload

    def get_transaction(self, signature: str) -> Any:
        if self.cache:
            hit = self.cache.get(self.name, "TRANSACTION_DETAIL", signature)
            if hit is not None:
                self.metrics.cache_hit += 1
                return hit
        result = self.rpc_call(
            "getTransaction",
            [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"}],
        )
        if result and self.cache:
            self.cache.set(self.name, "TRANSACTION_DETAIL", signature, result, 10 * 365 * 24 * 3600)
        return result

    def get_asset_batch(self, mints: list[str]) -> list[dict[str, Any]]:
        unique = []
        seen: set[str] = set()
        for mint in mints:
            if mint and mint not in seen:
                seen.add(mint)
                unique.append(mint)
        out: list[dict[str, Any]] = []
        for i in range(0, len(unique), 100):
            chunk = unique[i : i + 100]
            self._use_rpc()
            payload = self.http_request(
                "POST",
                self.rpc_url,
                json_body={"jsonrpc": "2.0", "id": 1, "method": "getAssetBatch", "params": {"ids": chunk}},
                headers={"Content-Type": "application/json"},
                provider=self,
            )
            self.credits.record("getAssetBatch")
            rows = payload.get("result") if isinstance(payload, dict) else payload
            if isinstance(rows, list):
                out.extend([r for r in rows if isinstance(r, dict)])
        return out

    def parse_das_metadata(self, asset: dict[str, Any]):
        from app.providers.moralis.models import TokenMetadata
        from app.utils.money import to_decimal

        content = asset.get("content") if isinstance(asset.get("content"), dict) else {}
        meta = content.get("metadata") if isinstance(content.get("metadata"), dict) else {}
        token_info = asset.get("token_info") if isinstance(asset.get("token_info"), dict) else {}
        mint = str(asset.get("id") or "").strip()
        if not mint:
            return None
        return TokenMetadata(
            mint=mint,
            name=str(meta.get("name") or token_info.get("symbol") or "").strip(),
            symbol=str(meta.get("symbol") or token_info.get("symbol") or "").strip(),
            decimals=int(token_info["decimals"]) if token_info.get("decimals") not in (None, "") else None,
            total_supply=to_decimal(token_info.get("supply")),
            raw=asset,
        )

    def test_connection(self) -> dict[str, Any]:
        if not self.api_key:
            return {"ok": False, "detail": "未配置"}
        return self.probe_capabilities()
