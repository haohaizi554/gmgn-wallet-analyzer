from __future__ import annotations

from typing import Any

from app.domain.enums import HeliusCapStatus, ProviderCapability, ProviderHealth
from app.providers.exceptions import ProviderAuthError, ProviderError, ProviderPlanError, ProviderRateLimitError

PROBE_CAPS = ("RPC", "DAS", "ENHANCED_TRANSACTIONS", "WALLET_HISTORY", "WALLET_TRANSFERS", "WALLET_BALANCES", "GTFA", "ARCHIVAL")
CAP_TTL = 3600
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _status_from_exc(exc: Exception) -> HeliusCapStatus:
    if isinstance(exc, ProviderAuthError):
        if getattr(exc, "status", None) == 403:
            return HeliusCapStatus.PLAN_UNAVAILABLE
        return HeliusCapStatus.AUTH_FAILED
    if isinstance(exc, ProviderPlanError):
        return HeliusCapStatus.PLAN_UNAVAILABLE
    if isinstance(exc, ProviderRateLimitError):
        return HeliusCapStatus.TEMPORARY_ERROR
    if isinstance(exc, ProviderError):
        status = getattr(exc, "status", None)
        text = str(exc).lower()
        if status == 404:
            return HeliusCapStatus.NOT_FOUND
        if status == 403 or "plan" in text or "upgrade" in text or "not available" in text or "method not found" in text:
            return HeliusCapStatus.PLAN_UNAVAILABLE
        if status and status >= 500:
            return HeliusCapStatus.TEMPORARY_ERROR
        return HeliusCapStatus.UNKNOWN
    return HeliusCapStatus.UNKNOWN


def apply_probe_result(provider, result: dict[str, str]) -> None:
    caps: set[ProviderCapability] = set()
    mapping = {
        "RPC": {ProviderCapability.TRANSACTION_DETAIL, ProviderCapability.WALLET_BALANCES},
        "DAS": {ProviderCapability.TOKEN_METADATA},
        "ENHANCED_TRANSACTIONS": {ProviderCapability.WALLET_SWAPS},
        "WALLET_HISTORY": {ProviderCapability.WALLET_HISTORY, ProviderCapability.WALLET_SWAPS},
        "WALLET_TRANSFERS": {ProviderCapability.WALLET_TRANSFERS},
        "WALLET_BALANCES": {ProviderCapability.WALLET_BALANCES},
        "GTFA": {ProviderCapability.WALLET_HISTORY, ProviderCapability.WALLET_SWAPS},
        "ARCHIVAL": {ProviderCapability.TRANSACTION_DETAIL},
    }
    for name, status in result.items():
        ok = status == HeliusCapStatus.AVAILABLE.value
        provider.cap_flags[name] = ok
        if ok:
            caps |= mapping.get(name, set())
    provider.capabilities = caps
    if result.get("RPC") == HeliusCapStatus.AUTH_FAILED.value:
        provider.health = ProviderHealth.AUTH_FAILED
        provider.health_detail = "Helius Key 无效"
        return
    if result.get("RPC") == HeliusCapStatus.AVAILABLE.value:
        provider.health = ProviderHealth.HEALTHY
        advanced = [k for k, v in result.items() if v == HeliusCapStatus.AVAILABLE.value and k != "RPC"]
        missing = [k for k, v in result.items() if v == HeliusCapStatus.PLAN_UNAVAILABLE.value]
        parts = ["基础 RPC 可用"]
        if advanced:
            parts.append("可用：" + ",".join(advanced))
        if missing:
            parts.append("套餐不可用：" + ",".join(missing))
        provider.health_detail = "；".join(parts)
    else:
        provider.health = ProviderHealth.DEGRADED
        provider.health_detail = "Helius RPC 探测失败: " + str(result.get("RPC"))
