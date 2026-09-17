from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from app.storage.repositories import Repositories
from app.utils.time_utils import now_ts


class ProviderCache:
    def __init__(self, repos: Repositories) -> None:
        self.repos = repos

    def get(self, provider: str, capability: str, cache_key: str) -> Optional[Any]:
        key = f"{provider}|{capability}|{cache_key}"
        return self.repos.get_provider_cache(key)

    def set(self, provider: str, capability: str, cache_key: str, payload: Any, ttl: int) -> None:
        key = f"{provider}|{capability}|{cache_key}"
        self.repos.save_provider_cache(provider, capability, key, payload, ttl)

    @staticmethod
    def digest(*parts: Any) -> str:
        blob = json.dumps(parts, ensure_ascii=False, default=str, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]
