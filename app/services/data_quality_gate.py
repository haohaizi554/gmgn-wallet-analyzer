from __future__ import annotations

from app.domain.enums import TaskStatus
from app.providers.result import HistoryCoverage


class DataQualityGate:
    """Core report-window history must be complete or verified empty before SUCCESS."""

    @staticmethod
    def evaluate(
        coverage: HistoryCoverage | None,
        *,
        token_count: int,
        failed_tokens: int = 0,
    ) -> TaskStatus:
        if failed_tokens and not token_count:
            return TaskStatus.FAILED
        if coverage is None:
            if token_count:
                return TaskStatus.PARTIAL
            return TaskStatus.FAILED
        if coverage.verified_empty:
            return TaskStatus.SUCCESS
        if coverage.complete:
            if failed_tokens:
                return TaskStatus.PARTIAL
            return TaskStatus.SUCCESS
        if token_count:
            return TaskStatus.PARTIAL
        return TaskStatus.FAILED
