from __future__ import annotations

import json
import random
import threading
import time
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter

from app.api.exceptions import AnalysisCancelledError
from app.providers.base import DataProvider, ProviderRetryPolicy
from app.providers.exceptions import ProviderAuthError, ProviderError, ProviderRateLimitError
from app.utils.logger import get_logger

logger = get_logger("gmgn.provider.http")

NETWORK_ERROR = "NETWORK_TRANSIENT_ERROR"
AUTH_FAILED = "AUTH_FAILED"
PLAN_UNAVAILABLE = "PLAN_UNAVAILABLE"
PERMISSION_DENIED = "PERMISSION_DENIED"


def _session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _sleep(owner: DataProvider, seconds: float) -> None:
    clock = getattr(getattr(owner, "circuit", None), "_clock", None)
    sleeper = getattr(clock, "sleep", None)
    if callable(sleeper):
        sleeper(seconds)
    elif seconds > 0:
        time.sleep(seconds)


class HttpProviderMixin:
    def __init__(self) -> None:
        self._local = threading.local()
        self._shared_session: Optional[requests.Session] = None
        self.cancel_event = None
        super().__init__()

    def _http(self) -> requests.Session:
        if self._shared_session is not None:
            return self._shared_session
        session = getattr(self._local, "session", None)
        if session is None:
            session = _session()
            self._local.session = session
        return session

    def _check_cancel(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise AnalysisCancelledError()

    def http_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        timeout: tuple[float, float] = (8, 30),
        provider: DataProvider | None = None,
    ) -> Any:
        owner: DataProvider = provider or self  # type: ignore[assignment]
        policy: ProviderRetryPolicy = getattr(owner, "retry_policy", None) or ProviderRetryPolicy()
        last_error: Exception | None = None
        for attempt in range(1, policy.max_attempts + 1):
            self._check_cancel()
            if attempt == 1:
                if not owner.circuit.allow():
                    owner.metrics.circuit_open += 1
                    raise ProviderError(f"{owner.name} circuit open", provider=owner.name, status=0, retryable=True)
            owner.limiter.acquire(self.cancel_event)
            started = time.perf_counter()
            owner.metrics.request_count += 1
            try:
                response = self._http().request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                owner.metrics.errors += 1
                owner.metrics.network_error += 1
                owner.circuit.record_failure(None)
                last_error = ProviderError(
                    f"{owner.name} 网络错误: {exc}",
                    provider=owner.name,
                    retryable=True,
                    error_type=NETWORK_ERROR,
                )
                logger.info(
                    "%s %s attempt=%s %s %s",
                    owner.name,
                    url.split("?")[0][-48:],
                    attempt,
                    NETWORK_ERROR,
                    exc.__class__.__name__,
                )
                if attempt < policy.max_attempts:
                    delay = _retry_delay(policy, attempt)
                    logger.info("%s retry=%.2fs", owner.name, delay)
                    _sleep(owner, delay)
                    continue
                logger.warning("%s failed after %s attempts", owner.name, attempt)
                raise last_error from exc
            elapsed = time.perf_counter() - started
            owner.metrics.latency_total += elapsed
            owner.metrics.bytes += len(response.content or b"")
            status = response.status_code
            body: Any
            try:
                body = response.json() if response.content else {}
            except json.JSONDecodeError:
                body = response.text[:4000]
            if status == 429:
                owner.metrics.count_429 += 1
                reset = _reset_seconds(response.headers, body)
                owner.limiter.set_cooldown(reset)
                owner.circuit.record_failure(429)
                if attempt < policy.max_attempts and reset <= policy.max_rate_limit_wait:
                    logger.info("%s 429 Retry-After=%.2fs attempt=%s", owner.name, reset, attempt)
                    _sleep(owner, reset)
                    continue
                raise ProviderRateLimitError(f"{owner.name} 429", provider=owner.name, reset_at=int(reset), status=429)
            if status in policy.no_retry_statuses:
                owner.metrics.errors += 1
                if status == 401:
                    owner.metrics.count_401 += 1
                    err_type = AUTH_FAILED
                else:
                    owner.metrics.count_403 += 1
                    text = str(body).lower()
                    err_type = PLAN_UNAVAILABLE if "plan" in text or "upgrade" in text or "payment" in text else PERMISSION_DENIED
                owner.circuit.record_failure(status)
                raise ProviderAuthError(
                    f"{owner.name} 认证失败 HTTP {status}",
                    provider=owner.name,
                    status=status,
                    error_type=err_type,
                )
            if status in policy.retry_statuses or status >= 500:
                owner.metrics.count_5xx += 1
                owner.circuit.record_failure(status)
                last_error = ProviderError(
                    f"{owner.name} HTTP {status}",
                    provider=owner.name,
                    status=status,
                    retryable=True,
                    error_type="SERVER_ERROR",
                )
                if attempt < policy.max_attempts:
                    delay = _retry_delay(policy, attempt)
                    logger.info("%s HTTP %s attempt=%s retry=%.2fs", owner.name, status, attempt, delay)
                    _sleep(owner, delay)
                    continue
                logger.warning("%s failed after %s attempts", owner.name, attempt)
                raise last_error
            if status >= 400:
                owner.metrics.errors += 1
                raise ProviderError(f"{owner.name} HTTP {status}: {str(body)[:300]}", provider=owner.name, status=status)
            owner.circuit.record_success()
            owner.metrics.success += 1
            if attempt > 1:
                logger.info("provider=%s recovered attempt=%s status=%s latency=%.2fs", owner.name, attempt, status, elapsed)
            else:
                logger.info("provider=%s method=%s status=%s latency=%.2fs", owner.name, method, status, elapsed)
            return body
        if last_error:
            raise last_error
        raise ProviderError(f"{owner.name} 请求失败", provider=owner.name)


def _retry_delay(policy: ProviderRetryPolicy, attempt: int) -> float:
    idx = min(max(0, attempt - 1), len(policy.base_delays) - 1)
    return policy.base_delays[idx] + random.uniform(0, max(0.0, policy.jitter))


def _reset_seconds(headers: Any, body: Any) -> float:
    headers = headers or {}
    for header_name in ("Retry-After", "retry-after", "x-ratelimit-reset", "X-RateLimit-Reset"):
        retry = headers.get(header_name)
        if retry:
            try:
                value = float(retry)
                if value > 1e12:
                    value /= 1000
                if value > 1e9:
                    return max(1.0, value - time.time())
                return max(1.0, value)
            except (TypeError, ValueError):
                continue
    if isinstance(body, dict):
        for key in ("reset_at", "resetAt", "retry_after"):
            if body.get(key):
                try:
                    value = float(body[key])
                    if value > 1e12:
                        value /= 1000
                    if value > 1e9:
                        return max(1.0, value - time.time())
                    return max(1.0, value)
                except (TypeError, ValueError):
                    continue
    return 15.0
