from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Optional


class AnalysisEventBus:
    """Worker 只 emit，GUI 用 root.after 消费。按 job_id 路由。"""

    def __init__(self, ui_queue: Optional[queue.Queue] = None) -> None:
        self._q = ui_queue or queue.Queue()
        self._lock = threading.Lock()
        self._subs: dict[str, list[Callable[[dict[str, Any]], None]]] = {}

    def emit(self, event: dict[str, Any]) -> None:
        event = dict(event)
        event.setdefault("job_id", event.get("job_id") or "")
        self._q.put(event)
        job_id = str(event.get("job_id") or "")
        with self._lock:
            cbs = list(self._subs.get(job_id, []))
            cbs.extend(self._subs.get("*", []))
        for cb in cbs:
            try:
                cb(event)
            except Exception:
                pass

    def subscribe(self, job_id: str, callback: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._subs.setdefault(job_id, []).append(callback)

    def drain(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        while True:
            try:
                items.append(self._q.get_nowait())
            except queue.Empty:
                break
        return items
