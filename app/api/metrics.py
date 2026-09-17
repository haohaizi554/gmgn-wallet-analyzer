from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class WindowStats:
    weight: float = 0.0
    requests: int = 0
    count_429: int = 0
    wait_seconds: float = 0.0
    latency: float = 0.0


class RateMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: deque[tuple[float, float, int, float, float, bool]] = deque()
        self.total_weight = 0.0
        self.total_requests = 0
        self.total_429 = 0
        self.total_401 = 0
        self.total_403 = 0
        self.total_5xx = 0
        self.timeouts = 0
        self.latencies: deque[float] = deque(maxlen=500)
        self.local_rate_wait = 0.0
        self.credential_wait = 0.0
        self.global_safety_wait = 0.0
        self.http_latency = 0.0
        self.server_cooldown_wait = 0.0
        self.rate_limit_events = 0

    def note_rate_limit_event(self) -> None:
        with self._lock:
            self.rate_limit_events += 1

    def record(
        self,
        weight: float,
        latency: float = 0.0,
        wait_seconds: float = 0.0,
        status: int = 200,
        local_wait: float = 0.0,
        credential_wait: float = 0.0,
        global_wait: float = 0.0,
        cooldown_wait: float = 0.0,
    ) -> None:
        now = time.time()
        is_429 = status == 429
        with self._lock:
            self._events.append((now, float(weight), 1, wait_seconds, latency, is_429))
            self.total_weight += float(weight)
            self.total_requests += 1
            self.local_rate_wait += float(local_wait or wait_seconds or 0.0)
            self.credential_wait += float(credential_wait)
            self.global_safety_wait += float(global_wait)
            self.server_cooldown_wait += float(cooldown_wait)
            self.http_latency += float(latency)
            if status == 429:
                self.total_429 += 1
            elif status == 401:
                self.total_401 += 1
            elif status == 403:
                self.total_403 += 1
            elif status >= 500:
                self.total_5xx += 1
            if latency > 0:
                self.latencies.append(latency)
            self._trim(now)

    def _trim(self, now: float) -> None:
        cutoff = now - 300
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def window(self, seconds: float) -> WindowStats:
        now = time.time()
        start = now - seconds
        stats = WindowStats()
        with self._lock:
            self._trim(now)
            for ts, weight, req, wait, lat, is_429 in self._events:
                if ts < start:
                    continue
                stats.weight += weight
                stats.requests += req
                stats.wait_seconds += wait
                stats.latency += lat
                if is_429:
                    stats.count_429 += 1
        return stats

    def utilization(self, server_rate: float, seconds: float = 60.0) -> float:
        if server_rate <= 0:
            return 0.0
        stats = self.window(seconds)
        return (stats.weight / max(seconds, 0.001)) / server_rate

    def percentile(self, p: float) -> float:
        with self._lock:
            if not self.latencies:
                return 0.0
            ordered = sorted(self.latencies)
        if not ordered:
            return 0.0
        idx = min(len(ordered) - 1, max(0, int(round((p / 100) * (len(ordered) - 1)))))
        return ordered[idx]

    def snapshot(self, server_rate: float) -> dict:
        u60 = self.utilization(server_rate, 60)
        u10 = self.utilization(server_rate, 10)
        u300 = self.utilization(server_rate, 300)
        return {
            "requests": self.total_requests,
            "weight": round(self.total_weight, 2),
            "utilization_10s": round(u10 * 100, 1),
            "utilization_1m": round(u60 * 100, 1),
            "utilization_5m": round(u300 * 100, 1),
            "429": self.total_429,
            "401": self.total_401,
            "403": self.total_403,
            "p50_latency": round(self.percentile(50), 3),
            "p95_latency": round(self.percentile(95), 3),
            "local_rate_wait": round(self.local_rate_wait, 3),
            "credential_wait": round(self.credential_wait, 3),
            "global_safety_wait": round(self.global_safety_wait, 3),
            "server_cooldown_wait": round(self.server_cooldown_wait, 3),
            "http_latency": round(self.http_latency, 3),
            "rate_limit_events": self.rate_limit_events,
        }
