from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from app.api.metrics import RateMetrics
from app.api.rate_limiter import Clock, WeightedRateLimiter


class CredentialState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    COOLDOWN = "COOLDOWN"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_FAILED = "AUTH_FAILED"
    DISABLED = "DISABLED"


def mask_key(api_key: str, index: int | None = None) -> str:
    suffix = (api_key or "")[-4:] if api_key else "????"
    prefix = f"Key #{index} " if index is not None else "Key "
    return f"{prefix}****{suffix}"


def _new_limiter(
    *,
    rate: float = 5.0,
    capacity: float = 5.0,
    target_utilization: float = 0.75,
    initial_utilization: float = 0.60,
    safety_margin: float = 3.0,
    clock: Optional[Clock] = None,
    metrics: Optional[RateMetrics] = None,
) -> WeightedRateLimiter:
    return WeightedRateLimiter(
        rate=rate,
        capacity=capacity,
        clock=clock,
        target_utilization=target_utilization,
        initial_utilization=initial_utilization,
        safety_margin=safety_margin,
        metrics=metrics or RateMetrics(),
    )


@dataclass
class ApiCredential:
    id: str
    api_key: str
    enabled: bool = True
    state: CredentialState = CredentialState.HEALTHY
    last_used_at: float = 0.0
    consecutive_failures: int = 0
    last_error: str | None = None
    cooldown_until: float = 0.0
    request_count: int = 0
    weighted_units: float = 0.0
    error_count: int = 0
    consecutive_429: int = 0
    consecutive_401: int = 0
    count_401: int = 0
    count_403: int = 0
    count_429: int = 0
    inflight: int = 0
    latency_ewma: float = 0.0
    latency_sum: float = 0.0
    index: int = 1
    limiter: WeightedRateLimiter = field(default_factory=WeightedRateLimiter)
    success_since_429: int = 0
    last_success_mono: float = 0.0
    climb_started_at: float = 0.0

    @property
    def key_id(self) -> str:
        return self.id

    @property
    def masked(self) -> str:
        return mask_key(self.api_key, self.index)

    @property
    def avg_latency(self) -> float:
        if self.request_count <= 0:
            return 0.0
        return self.latency_sum / self.request_count

    def is_schedulable(self, now: float) -> bool:
        if not self.enabled:
            return False
        if self.state in (CredentialState.AUTH_FAILED, CredentialState.DISABLED):
            return False
        if self.state in (CredentialState.RATE_LIMITED, CredentialState.COOLDOWN):
            return now >= self.cooldown_until
        return True


LimiterFactory = Callable[[], WeightedRateLimiter]


class CredentialPool:
    """每个 Key 独立 WeightedRateLimiter。调度与 429 状态由 CredentialScheduler 负责。"""

    def __init__(
        self,
        api_keys: list[str],
        *,
        rate: float = 5.0,
        capacity: float = 5.0,
        target_utilization: float = 0.75,
        initial_utilization: float = 0.60,
        safety_margin: float = 0.0,
        clock: Optional[Clock] = None,
        limiter_factory: Optional[LimiterFactory] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._creds: list[ApiCredential] = []
        self._clock = clock or Clock()
        self.rate = float(rate)
        self.capacity = float(capacity)
        self.target_utilization = float(target_utilization)
        self.initial_utilization = float(initial_utilization)
        self.safety_margin = float(safety_margin)
        factory = limiter_factory or (
            lambda: _new_limiter(
                rate=self.rate,
                capacity=self.capacity,
                target_utilization=self.target_utilization,
                initial_utilization=self.initial_utilization,
                safety_margin=self.safety_margin,
                clock=self._clock,
            )
        )
        for i, key in enumerate(api_keys or [], start=1):
            value = (key or "").strip()
            if not value:
                continue
            self._creds.append(
                ApiCredential(
                    id=f"key-{i}",
                    api_key=value,
                    index=i,
                    limiter=factory(),
                )
            )

    def __len__(self) -> int:
        return len(self._creds)

    def all(self) -> list[ApiCredential]:
        with self._lock:
            return list(self._creds)

    def get(self, cred_id: str) -> Optional[ApiCredential]:
        with self._lock:
            for cred in self._creds:
                if cred.id == cred_id:
                    return cred
            return None

    def apply_limiter_settings(self, template: WeightedRateLimiter) -> None:
        """复制速率参数到每把独立 limiter，不共享 token bucket / cooldown。"""
        with self._lock:
            for cred in self._creds:
                src = cred.limiter
                cred.limiter = WeightedRateLimiter(
                    rate=template.server_rate,
                    capacity=template.capacity,
                    clock=getattr(template, "_clock", self._clock),
                    target_utilization=template.target_utilization,
                    initial_utilization=getattr(template, "_adaptive_target", template.target_utilization),
                    safety_margin=getattr(template, "safety_margin", self.safety_margin),
                    metrics=RateMetrics(),
                )
                cred.limiter.tokens = min(cred.limiter.capacity, template.tokens if template.tokens > 0 else cred.limiter.rate)
                _ = src

    def recover_if_due(self, cred: ApiCredential, now: Optional[float] = None) -> None:
        stamp = self._clock.time() if now is None else now
        with self._lock:
            if cred.state in (CredentialState.AUTH_FAILED, CredentialState.DISABLED):
                return
            if cred.state in (CredentialState.RATE_LIMITED, CredentialState.COOLDOWN) and stamp >= cred.cooldown_until:
                cred.state = CredentialState.DEGRADED if cred.consecutive_429 else CredentialState.HEALTHY
                cred.consecutive_429 = 0

    def has_usable(self) -> bool:
        with self._lock:
            return any(c.enabled and c.state not in (CredentialState.AUTH_FAILED, CredentialState.DISABLED) for c in self._creds)

    def has_healthy_now(self) -> bool:
        with self._lock:
            now = self._clock.time()
            for cred in self._creds:
                self.recover_if_due(cred, now)
                if cred.is_schedulable(now):
                    return True
            return False

    def next_available_at(self) -> float:
        with self._lock:
            now = self._clock.time()
            times: list[float] = []
            for cred in self._creds:
                if not cred.enabled or cred.state in (CredentialState.AUTH_FAILED, CredentialState.DISABLED):
                    continue
                if cred.is_schedulable(now):
                    return now
                times.append(cred.cooldown_until or now)
            return min(times) if times else now + 30.0

    def mark_auth_failed(self, cred: ApiCredential, status: int, message: str) -> None:
        with self._lock:
            cred.consecutive_failures += 1
            cred.error_count += 1
            cred.last_error = message[:200]
            if status == 401:
                cred.count_401 += 1
                cred.consecutive_401 += 1
                cred.state = CredentialState.AUTH_FAILED
                cred.enabled = False
            elif status == 403:
                cred.count_403 += 1
                cred.state = (
                    CredentialState.AUTH_FAILED
                    if "forbidden" in message.lower() or "invalid" in message.lower()
                    else CredentialState.DEGRADED
                )
                if cred.state == CredentialState.AUTH_FAILED:
                    cred.enabled = False
            else:
                cred.state = CredentialState.DEGRADED

    def mark_success(self, cred: ApiCredential, latency: float) -> None:
        with self._lock:
            cred.consecutive_failures = 0
            cred.consecutive_401 = 0
            cred.latency_sum += latency
            cred.success_since_429 += 1
            alpha = 0.3
            cred.latency_ewma = latency if cred.latency_ewma <= 0 else (alpha * latency + (1 - alpha) * cred.latency_ewma)
            if cred.state in (CredentialState.DEGRADED, CredentialState.COOLDOWN) and cred.enabled:
                cred.state = CredentialState.HEALTHY
            if cred.state == CredentialState.RATE_LIMITED and time.time() >= cred.cooldown_until:
                cred.state = CredentialState.HEALTHY

    def mark_429(self, cred: ApiCredential, reset_at: int | None = None, banned: bool = False, safety_margin: float = 3.0) -> None:
        with self._lock:
            now = self._clock.time()
            cred.count_429 += 1
            cred.consecutive_429 += 1
            cred.success_since_429 = 0
            cred.last_error = "RATE_LIMIT_BANNED" if banned else "RATE_LIMIT_EXCEEDED"
            unix = int(reset_at or (now + 2))
            margin = max(0.0, float(safety_margin))
            cred.cooldown_until = float(unix) + margin
            cred.state = CredentialState.RATE_LIMITED
            cred.limiter.set_server_cooldown(unix, safety_margin=margin)
            if banned:
                cred.limiter._adaptive_target = max(0.30, min(cred.limiter._adaptive_target - 0.20, 0.50))
                cred.limiter.rate = cred.limiter.server_rate * cred.limiter._adaptive_target

    def mark_network(self, cred: ApiCredential, message: str) -> None:
        with self._lock:
            cred.last_error = message[:200]
            cred.consecutive_failures += 1
            cred.error_count += 1
            if cred.state == CredentialState.HEALTHY:
                cred.state = CredentialState.DEGRADED

    def snapshot(self) -> list[dict]:
        with self._lock:
            now = self._clock.time()
            rows = []
            for c in self._creds:
                self.recover_if_due(c, now)
                snap = c.limiter.snapshot()
                rows.append(
                    {
                        "id": c.id,
                        "index": c.index,
                        "masked": c.masked,
                        "state": c.state.value,
                        "enabled": c.enabled,
                        "requests": c.request_count,
                        "inflight": c.inflight,
                        "401": c.count_401,
                        "403": c.count_403,
                        "429": c.count_429,
                        "avg_latency": round(c.avg_latency, 3),
                        "latency_ewma": round(c.latency_ewma, 3),
                        "last_error": c.last_error,
                        "cooldown_until": c.cooldown_until,
                        "utilization": snap.adaptive_target,
                        "actual_utilization": snap.utilization_1m,
                        "effective_rate": snap.effective_rate,
                    }
                )
            return rows
