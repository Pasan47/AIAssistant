"""Typed exceptions so callers can degrade gracefully instead of crashing the turn."""


class AppError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request"):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


class AuthError(AppError):
    def __init__(self, message: str = "Invalid or expired credentials"):
        super().__init__(message, 401, "unauthorized")


class LLMUnavailable(Exception):
    """LLM call failed after retries (timeout, rate limit, provider outage, malformed output)."""


class RetrievalUnavailable(Exception):
    """Both dense and sparse retrieval failed."""
