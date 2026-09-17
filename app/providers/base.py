from __future__ import annotations

import threading
import time
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Optional

from app.domain.enums import CircuitState, ProviderCapability, ProviderHealth


class Clock:
    def monotonic(self) -> float:
        return time.monotonic()

    def time(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


@dataclass
class ProviderRetryPolicy:
    max_attempts: int = 3
    base_delays: tuple[float, ...] = (0.5, 1.0, 2.0)
    jitter: float = 0.1
    retry_statuses: tuple[int, ...] = (408, 500, 502, 503, 504)
    no_retry_statuses: tuple[int, ...] = (401, 403)
    rate_limit_status: int = 429
    max_rate_limit_wait: float = 5.0


@dataclass
class ProviderMetrics:
    provider: str
    request_count: int = 0
    cache_hit: int = 0
    success: int = 0
    count_429: int = 0
    count_5xx: int = 0
    count_401: int = 0
    count_403: int = 0
    network_error: int = 0
    bytes: int = 0
    circuit_open: int = 0
    fallback_count: int = 0
    latency_total: float = 0.0
    errors: int = 0

    def snapshot(self) -> dict[str, Any]:
        avg = (self.latency_total / self.request_count) if self.request_count else 0.0
        return {
            "provider": self.provider,
            "request_count": self.request_count,
            "cache_hit": self.cache_hit,
            "success": self.success,
            "429": self.count_429,
            "401": self.count_401,
            "403": self.count_403,
            "5xx": self.count_5xx,
            "network_error": self.network_error,
            "bytes": self.bytes,
            "circuit_open": self.circuit_open,
            "fallback_count": self.fallback_count,
            "latency_seconds": round(self.latency_total, 3),
            "avg_latency": round(avg, 3),
            "errors": self.errors,
        }


class IndependentRateLimiter:
    """Per-provider token bucket. Must never share cooldown with other providers."""

    def __init__(self, rate: float = 5.0, capacity: float | None = None, clock: Clock | None = None, min_spacing: float = 0.0):
        self.rate = max(0.1, float(rate))
        self.capacity = max(1.0, float(capacity if capacity is not None else rate))
        self.tokens = self.capacity
        self.min_spacing = max(0.0, float(min_spacing))
        self._clock = clock or Clock()
        self._last = self._clock.monotonic()
        self._last_grant = 0.0
        self.cooldown_until = 0.0
        self._lock = threading.Lock()

    def acquire(self, cancel_event=None) -> float:
        waited = 0.0
        while True:
            if cancel_event is not None and cancel_event.is_set():
                from app.api.exceptions import AnalysisCancelledError

                raise AnalysisCancelledError()
            with self._lock:
                now = self._clock.monotonic()
                wall = self._clock.time()
                elapsed = max(0.0, now - self._last)
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self._last = now
                cooldown = max(0.0, self.cooldown_until - wall)
                spacing = 0.0
                if self.min_spacing and self._last_grant:
                    spacing = max(0.0, self.min_spacing - (now - self._last_grant))
                if cooldown <= 0 and spacing <= 0 and self.tokens >= 1:
                    self.tokens -= 1
                    self._last_grant = now
                    return waited
                sleep_for = max(cooldown, spacing, 0.05 if self.tokens < 1 else 0.0)
            self._clock.sleep(min(sleep_for, 1.0))
            waited += min(sleep_for, 1.0)

    def set_cooldown(self, seconds: float) -> None:
        with self._lock:
            self.cooldown_until = max(self.cooldown_until, self._clock.time() + max(0.0, seconds))


class ProviderCircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        open_seconds: float = 60.0,
        clock: Clock | None = None,
        rate_limit_codes: tuple[int, ...] = (429,),
        server_error_codes: tuple[int, ...] = (500, 502, 503, 504),
    ) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.open_seconds = float(open_seconds)
        self._clock = clock or Clock()
        self.rate_limit_codes = rate_limit_codes
        self.server_error_codes = server_error_codes
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.opened_at = 0.0
        self.half_open_probe_inflight = False
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            now = self._clock.monotonic()
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.OPEN:
                if now - self.opened_at >= self.open_seconds:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_probe_inflight = False
                else:
                    return False
            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_probe_inflight:
                    return False
                self.half_open_probe_inflight = True
                return True
            return True

    def record_success(self) -> None:
        with self._lock:
            self.consecutive_failures = 0
            self.state = CircuitState.CLOSED
            self.half_open_probe_inflight = False

    def record_failure(self, status: int | None = None) -> CircuitState:
        with self._lock:
            interesting = status in self.rate_limit_codes or status in self.server_error_codes or status is None
            if not interesting and status not in (401, 403):
                return self.state
            self.consecutive_failures += 1
            self.half_open_probe_inflight = False
            if self.state == CircuitState.HALF_OPEN or self.consecutive_failures >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.opened_at = self._clock.monotonic()
            return self.state

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "open_seconds": self.open_seconds,
        }


@dataclass
class ProviderStatus:
    name: str
    health: ProviderHealth = ProviderHealth.NOT_CONFIGURED
    detail: str = ""
    capabilities: set[ProviderCapability] = field(default_factory=set)
    circuit: CircuitState = CircuitState.CLOSED
    optional: bool = False


class DataProvider(ABC):
    name: str = "base"
    optional: bool = False
    capabilities: set[ProviderCapability] = set()

    def __init__(self) -> None:
        self.health = ProviderHealth.NOT_CONFIGURED
        self.health_detail = ""
        self.metrics = ProviderMetrics(self.name)
        self.limiter = IndependentRateLimiter()
        self.circuit = ProviderCircuitBreaker()
        self.retry_policy = ProviderRetryPolicy()
        self.enabled = True

    def has_capability(self, capability: ProviderCapability) -> bool:
        return capability in self.capabilities and self.enabled and self.health not in {
            ProviderHealth.UNAVAILABLE,
            ProviderHealth.AUTH_FAILED,
            ProviderHealth.NOT_CONFIGURED,
            ProviderHealth.DISABLED,
        }

    def status(self) -> ProviderStatus:
        health = self.health
        if self.circuit.state == CircuitState.OPEN:
            health = ProviderHealth.CIRCUIT_OPEN
        return ProviderStatus(
            name=self.name,
            health=health,
            detail=self.health_detail,
            capabilities=set(self.capabilities),
            circuit=self.circuit.state,
            optional=self.optional,
        )
