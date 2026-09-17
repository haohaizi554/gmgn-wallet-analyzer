from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Optional, TypeVar

from app.domain.enums import DataSource

T = TypeVar("T")


@dataclass
class HistoryCoverage:
    requested_start_ts: int = 0
    requested_end_ts: int = 0
    actual_start_ts: int | None = None
    actual_end_ts: int | None = None
    pages: int = 0
    transactions: int = 0
    complete: bool = False
    verified_empty: bool = False
    provider: DataSource = DataSource.MORALIS
    termination_reason: str = "unknown"
    errors: list[str] = field(default_factory=list)
    fallback_used: bool = False
    fallback_provider: str = ""

    def mark_verified_empty(self, provider: DataSource) -> None:
        self.provider = provider
        self.complete = True
        self.verified_empty = True
        self.transactions = 0
        self.termination_reason = "verified_empty"

    def mark_unknown_empty(self, provider: DataSource, reason: str, error: str = "") -> None:
        self.provider = provider
        self.complete = False
        self.verified_empty = False
        self.termination_reason = reason
        if error:
            self.errors.append(error)


@dataclass
class ProviderResult(Generic[T]):
    data: T
    provider: DataSource
    success: bool
    complete: bool
    from_cache: bool = False
    coverage: HistoryCoverage | None = None
    error_type: str | None = None
    error_message: str | None = None
    request_count: int = 0
    fallback_used: bool = False


def coverage_from_swaps(
    *,
    provider: DataSource,
    start_ts: int,
    end_ts: int,
    timestamps: list[int],
    pages: int,
    complete: bool,
    success: bool,
    errors: list[str] | None = None,
) -> HistoryCoverage:
    present = [ts for ts in timestamps if ts]
    actual_start = min(present) if present else None
    actual_end = max(present) if present else None
    count = len(timestamps)
    verified_empty = bool(success and complete and count == 0)
    reason = "verified_empty" if verified_empty else ("complete" if complete and success else ("provider_error" if not success else "incomplete"))
    return HistoryCoverage(
        requested_start_ts=start_ts,
        requested_end_ts=end_ts,
        actual_start_ts=actual_start,
        actual_end_ts=actual_end,
        pages=pages,
        transactions=count,
        complete=bool(success and complete),
        verified_empty=verified_empty,
        provider=provider,
        termination_reason=reason,
        errors=list(errors or []),
    )
