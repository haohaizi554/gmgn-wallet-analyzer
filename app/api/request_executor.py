from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

T = TypeVar("T")


class ApiRequestExecutor:
    """有限并发 HTTP 执行器。速率仍完全由 GlobalWeightedRateLimiter 约束。"""

    def __init__(self, max_workers: int = 4) -> None:
        workers = max(1, min(8, int(max_workers)))
        self.max_workers = workers
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gmgn-api")

    def submit(self, fn: Callable[..., T], *args, **kwargs):
        return self._pool.submit(fn, *args, **kwargs)

    def shutdown(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=True)
