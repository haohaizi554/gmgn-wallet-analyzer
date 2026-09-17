from __future__ import annotations

import threading
from typing import Any, Optional

from app.storage.repositories import Repositories


class CacheService:
    def __init__(self, repos: Repositories, token_ttl: int = 43200, pool_ttl: int = 1800) -> None:
        self.repos = repos
        self.token_ttl = token_ttl
        self.pool_ttl = pool_ttl
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()

    def _hit(self) -> None:
        with self._lock:
            self.hits += 1

    def _miss(self) -> None:
        with self._lock:
            self.misses += 1

    def get_token_info(self, chain: str, token: str) -> Optional[dict[str, Any]]:
        data = self.repos.get_token_info(chain, token, self.token_ttl)
        if data is None:
            self._miss()
        else:
            self._hit()
        return data

    def set_token_info(self, chain: str, token: str, payload: dict[str, Any]) -> None:
        self.repos.save_token_info(chain, token, payload)

    def get_pool(self, chain: str, token: str) -> Optional[dict[str, Any]]:
        data = self.repos.get_pool(chain, token, self.pool_ttl)
        if data is None:
            self._miss()
        else:
            self._hit()
        return data

    def set_pool(self, chain: str, token: str, payload: dict[str, Any]) -> None:
        self.repos.save_pool(chain, token, payload)

    @property
    def hit_rate(self) -> str:
        total = self.hits + self.misses
        if total <= 0:
            return "0%"
        return f"{(self.hits / total) * 100:.1f}%"
