from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from app.api.credential_pool import ApiCredential, CredentialPool, CredentialState
from app.api.exceptions import AnalysisCancelledError, GMGNAuthError, GMGNRateLimitError
from app.api.rate_limiter import Clock
from app.api.route_policy import route_weight
from app.utils.logger import get_logger
from app.utils.time_utils import format_clock

logger = get_logger("gmgn.scheduler")

MODE_INDEPENDENT = "INDEPENDENT"
MODE_SHARED = "SHARED_LIMIT_SUSPECTED"


@dataclass
class CredentialLease:
    credential: ApiCredential
    route_name: str
    weight: int
    local_wait: float = 0.0
    credential_wait: float = 0.0
    global_wait: float = 0.0
    cooldown_wait: float = 0.0


@dataclass
class SafetyEvent:
    key_id: str
    ts: float
    reset_at: float


class GlobalSafetyController:
    """不负责 token bucket。只检测多 Key 同时 429 / IP 级共享限制。"""

    def __init__(
        self,
        pool: CredentialPool,
        *,
        enabled: bool = True,
        window: float = 10.0,
        reset_slop: float = 5.0,
        safety_margin: float = 3.0,
        clock: Optional[Clock] = None,
    ) -> None:
        self.pool = pool
        self.enabled = enabled
        self.window = window
        self.reset_slop = reset_slop
        self.safety_margin = safety_margin
        self._clock = clock or Clock()
        self._lock = threading.RLock()
        self._events: list[SafetyEvent] = []
        self.mode = MODE_INDEPENDENT
        self.global_cooldown_until = 0.0
        self.global_cooldown_count = 0
        self.last_message = ""

    def wait_if_needed(self, cancel_event: Optional[threading.Event] = None) -> float:
        waited = 0.0
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise AnalysisCancelledError()
            with self._lock:
                now = self._clock.time()
                remaining = self.global_cooldown_until - now
            if remaining <= 0:
                return waited
            step = min(0.2, remaining)
            if cancel_event is not None:
                if cancel_event.wait(step):
                    raise AnalysisCancelledError()
            else:
                self._clock.sleep(step)
            waited += step
        return waited

    def note_429(self, cred: ApiCredential, reset_at: Optional[int]) -> bool:
        if not self.enabled:
            return False
        now = self._clock.time()
        reset = float(reset_at or (now + 2))
        triggered = False
        with self._lock:
            self._events.append(SafetyEvent(cred.id, now, reset))
            cutoff = now - self.window
            self._events = [e for e in self._events if e.ts >= cutoff]
            by_key: dict[str, SafetyEvent] = {}
            for event in self._events:
                prev = by_key.get(event.key_id)
                if prev is None or event.ts >= prev.ts:
                    by_key[event.key_id] = event
            if len(by_key) >= 2:
                resets = [e.reset_at for e in by_key.values()]
                if max(resets) - min(resets) <= self.reset_slop:
                    until = max(resets) + self.safety_margin
                    if until > self.global_cooldown_until:
                        self.global_cooldown_until = until
                        self.global_cooldown_count += 1
                    self.mode = MODE_SHARED
                    self.last_message = "检测到服务端可能存在共享限制，已自动降低请求速率。"
                    triggered = True
                    logger.warning(
                        "GLOBAL_COOLDOWN until=%s keys=%s",
                        format_clock(int(until)),
                        ",".join(sorted(by_key)),
                    )
        if triggered:
            for item in self.pool.all():
                item.limiter._adaptive_target = max(0.30, round(item.limiter._adaptive_target * 0.8, 2))
                item.limiter.rate = item.limiter.server_rate * item.limiter._adaptive_target
        return triggered

    def snapshot(self) -> dict:
        with self._lock:
            now = self._clock.time()
            remaining = max(0.0, self.global_cooldown_until - now)
            return {
                "mode": self.mode,
                "mode_label": "检测到共享限制" if self.mode == MODE_SHARED else "独立 Key",
                "global_cooldown_until": self.global_cooldown_until,
                "global_cooldown_remaining": remaining,
                "global_cooldown_count": self.global_cooldown_count,
                "message": self.last_message,
            }


class CredentialScheduler:
    def __init__(
        self,
        pool: CredentialPool,
        *,
        safety: Optional[GlobalSafetyController] = None,
        clock: Optional[Clock] = None,
        max_wait: float = 900.0,
        on_waiting: Optional[callable] = None,
    ) -> None:
        self.pool = pool
        self._clock = clock or Clock()
        self.safety = safety or GlobalSafetyController(pool, clock=self._clock, safety_margin=pool.safety_margin)
        self.max_wait = max_wait
        self.on_waiting = on_waiting
        self._lock = threading.RLock()
        self._rr = 0
        self._cond = threading.Condition(self._lock)

    def get_next_available_time(self) -> float:
        safety_at = self.safety.global_cooldown_until
        pool_at = self.pool.next_available_at()
        return max(safety_at, pool_at)

    def wait_for_available_credential(self, cancel_event: Optional[threading.Event] = None, timeout: Optional[float] = None) -> ApiCredential:
        deadline = self._clock.time() + (self.max_wait if timeout is None else timeout)
        started = self._clock.time()
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise AnalysisCancelledError()
            self.safety.wait_if_needed(cancel_event)
            now = self._clock.time()
            if now > deadline:
                raise GMGNRateLimitError("等待 API 恢复超时", status=429)
            for cred in self.pool.all():
                self.pool.recover_if_due(cred, now)
                if cred.is_schedulable(now):
                    return cred
            if not self.pool.has_usable():
                raise GMGNAuthError("所有 API Key 均不可用（AUTH_FAILED / DISABLED）")
            remaining = min(0.2, max(0.05, self.get_next_available_time() - now))
            if self.on_waiting:
                try:
                    self.on_waiting(
                        {
                            "type": "WAITING_FOR_API",
                            "resume_at": self.get_next_available_time(),
                            "waited": now - started,
                        }
                    )
                except Exception:
                    pass
            if cancel_event is not None:
                if cancel_event.wait(remaining):
                    raise AnalysisCancelledError()
            else:
                self._clock.sleep(remaining)

    def acquire_credential(self, route_name: str, cancel_event: Optional[threading.Event] = None, weight: Optional[int] = None) -> CredentialLease:
        need = int(weight if weight is not None else route_weight(route_name))
        global_wait = self.safety.wait_if_needed(cancel_event)
        cred_wait = 0.0
        cooldown_wait = 0.0
        started = self._clock.time()
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise AnalysisCancelledError()
            extra = self.safety.wait_if_needed(cancel_event)
            global_wait += extra
            now = self._clock.time()
            if now - started > self.max_wait:
                raise GMGNRateLimitError("等待可用 API Key 超时", status=429)
            cred = self._pick(need)
            if cred is None:
                if not any(c.enabled and c.state != CredentialState.AUTH_FAILED for c in self.pool.all()):
                    raise GMGNAuthError("无可用 GMGN API Key")
                resume = self.get_next_available_time()
                wait_for = min(0.2, max(0.05, resume - now))
                cred_wait += wait_for
                cooldown_wait += wait_for
                if self.on_waiting:
                    try:
                        self.on_waiting({"type": "WAITING_FOR_API", "resume_at": resume, "route": route_name})
                    except Exception:
                        pass
                if cancel_event is not None:
                    if cancel_event.wait(wait_for):
                        raise AnalysisCancelledError()
                else:
                    self._clock.sleep(wait_for)
                continue
            spacing = self._min_spacing(cred, need)
            local_wait = cred.limiter.acquire(need, cancel_event, min_spacing=spacing)
            if local_wait is None:
                local_wait = 0.0
            with self._lock:
                cred.inflight += 1
                cred.last_used_at = self._clock.time()
                cred.request_count += 1
                cred.weighted_units += need
            return CredentialLease(
                credential=cred,
                route_name=route_name,
                weight=need,
                local_wait=float(local_wait),
                credential_wait=cred_wait,
                global_wait=global_wait,
                cooldown_wait=cooldown_wait,
            )

    def release_credential(self, lease: CredentialLease) -> None:
        cred = lease.credential
        with self._lock:
            cred.inflight = max(0, cred.inflight - 1)
            self._cond.notify_all()

    def report_response(
        self,
        lease: CredentialLease,
        *,
        status: int,
        latency: float,
        body: Optional[dict] = None,
        reset_at: Optional[int] = None,
        banned: bool = False,
    ) -> None:
        cred = lease.credential
        if status == 429:
            self.pool.mark_429(cred, reset_at=reset_at, banned=banned, safety_margin=self.pool.safety_margin)
            self.safety.note_429(cred, reset_at)
            self._maybe_climb = False
            return
        if status in (401, 403):
            message = ""
            if isinstance(body, dict):
                message = str(body.get("message") or body.get("error") or "")
            self.pool.mark_auth_failed(cred, status, message)
            return
        if status >= 500 or status == 0:
            self.pool.mark_network(cred, f"HTTP {status}")
            return
        self.pool.mark_success(cred, latency)
        self._climb_if_stable(cred)

    def _climb_if_stable(self, cred: ApiCredential) -> None:
        now = self._clock.time()
        limiter = cred.limiter
        if limiter._consecutive_429 > 0:
            return
        if cred.climb_started_at <= 0:
            cred.climb_started_at = now
            cred.last_success_mono = now
            return
        if now - cred.climb_started_at < 60:
            return
        if cred.success_since_429 < 20:
            return
        current = limiter._adaptive_target
        target = limiter.target_utilization
        if current >= target - 1e-9:
            return
        if current < 0.70 - 1e-9:
            limiter.raise_utilization(0.10)
        elif current < 0.75 - 1e-9:
            limiter.raise_utilization(0.05)
        else:
            limiter.raise_utilization(max(0.01, target - current))
        cred.climb_started_at = now
        cred.success_since_429 = 0

    def _pick(self, weight: int) -> Optional[ApiCredential]:
        now = self._clock.time()
        eligible: list[ApiCredential] = []
        for cred in self.pool.all():
            self.pool.recover_if_due(cred, now)
            if not cred.is_schedulable(now):
                continue
            wait = cred.limiter.wait_time(weight)
            if wait > 8:
                continue
            eligible.append(cred)
        if not eligible:
            return None
        n = len(eligible)
        with self._lock:
            rr = self._rr

            def score(c: ApiCredential) -> tuple:
                wait = c.limiter.wait_time(weight)
                return (
                    round(wait, 2),
                    c.inflight,
                    round(c.latency_ewma, 3),
                    (c.index - 1 - rr) % max(n, 1),
                )

            eligible.sort(key=score)
            picked = eligible[0]
            self._rr += 1
        return picked

    def _min_spacing(self, cred: ApiCredential, weight: int) -> float:
        if weight < 3:
            return 0.0
        if cred.limiter.server_rate >= 20:
            return 0.0
        adaptive = max(0.30, cred.limiter._adaptive_target)
        return max(0.8, min(1.2, 1.0 * (0.60 / adaptive)))
