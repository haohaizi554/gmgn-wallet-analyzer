from __future__ import annotations


class RateLimitSeverity:
    THROTTLED = "THROTTLED"
    BANNED = "BANNED"


class GMGNError(Exception):
    def __init__(self, message: str, *, status: int | None = None, api_error: str = "", reset_at: int | None = None):
        super().__init__(message)
        self.status = status
        self.api_error = api_error
        self.reset_at = reset_at


class GMGNAuthError(GMGNError):
    pass


class GMGNRateLimitError(GMGNError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = 429,
        api_error: str = "",
        reset_at: int | None = None,
        severity: "RateLimitSeverity | None" = None,
    ):
        super().__init__(message, status=status, api_error=api_error, reset_at=reset_at)
        self.severity = severity or RateLimitSeverity.THROTTLED


class GMGNNetworkError(GMGNError):
    pass


class GMGNBadResponseError(GMGNError):
    pass


class GMGNDataMissingError(GMGNError):
    pass


class AnalysisCancelledError(GMGNError):
    def __init__(self, message: str = "分析已取消"):
        super().__init__(message)
