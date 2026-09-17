from __future__ import annotations

import threading
from concurrent.futures import Future
from typing import Callable, TypeVar

T = TypeVar("T")


class SingleFlight:
    """Coalesce identical in-flight calls. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight: dict[str, Future] = {}

    def do(self, key: str, fn: Callable[[], T]) -> T:
        with self._lock:
            existing = self._inflight.get(key)
            if existing is not None:
                fut = existing
                owned = False
            else:
                fut = Future()
                self._inflight[key] = fut
                owned = True
        if not owned:
            return fut.result()
        try:
            result = fn()
            fut.set_result(result)
            return result
        except Exception as exc:
            fut.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._inflight.pop(key, None)
