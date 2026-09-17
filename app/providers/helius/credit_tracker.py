from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.providers.helius.credit_policy import credits_for
from app.utils.time_utils import now_ts


@dataclass
class HeliusCreditTracker:
    monthly_budget: int = 1_000_000
    estimated_credits: int = 0
    unpriced_requests: int = 0
    by_method: dict[str, int] = field(default_factory=dict)
    job_credits: int = 0

    def record(self, method: str, *, returned: int | None = None, details: str = "") -> Optional[int]:
        cost = credits_for(method, returned=returned, details=details)
        self.by_method[method] = self.by_method.get(method, 0) + 1
        if cost is None:
            self.unpriced_requests += 1
            return None
        self.estimated_credits += cost
        self.job_credits += cost
        return cost

    def load_month(self, snapshot: dict[str, Any] | None) -> None:
        if not snapshot:
            return
        self.estimated_credits = int(snapshot.get("estimated_credits") or 0)
        self.unpriced_requests = int(snapshot.get("unpriced_requests") or 0)
        by_method = snapshot.get("by_method") or {}
        if isinstance(by_method, dict):
            self.by_method = {str(k): int(v or 0) for k, v in by_method.items()}
        self.job_credits = 0

    @property
    def usage_ratio(self) -> float:
        if self.monthly_budget <= 0:
            return 0.0
        return self.estimated_credits / self.monthly_budget

    def allow_optional(self) -> bool:
        return self.usage_ratio < 0.90

    def warn_soft(self) -> bool:
        return self.usage_ratio >= 0.80

    def snapshot(self) -> dict[str, Any]:
        return {
            "estimated_credits": self.estimated_credits,
            "job_credits": self.job_credits,
            "unpriced_requests": self.unpriced_requests,
            "monthly_budget": self.monthly_budget,
            "usage_ratio": round(self.usage_ratio, 4),
            "by_method": dict(self.by_method),
            "note": "LOCAL ESTIMATE, not official remaining credits",
            "updated_at": now_ts(),
        }
