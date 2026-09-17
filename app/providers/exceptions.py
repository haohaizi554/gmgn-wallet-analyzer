from __future__ import annotations


class ProviderError(Exception):
    def __init__(self, message: str, *, provider: str = "", status: int | None = None, retryable: bool = False, error_type: str | None = None):
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.retryable = retryable
        self.error_type = error_type


class ProviderAuthError(ProviderError):
    def __init__(self, message: str, *, provider: str = "", status: int | None = None, error_type: str | None = None):
        super().__init__(message, provider=provider, status=status, retryable=False, error_type=error_type)


class ProviderRateLimitError(ProviderError):
    def __init__(self, message: str, *, provider: str = "", reset_at: int | None = None, status: int | None = 429):
        super().__init__(message, provider=provider, status=status, retryable=True)
        self.reset_at = reset_at


class ProviderUnavailableError(ProviderError):
    pass


class ProviderPlanError(ProviderError):
    pass
