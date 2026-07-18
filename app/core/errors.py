"""Application error types and a consistent error envelope.

The pipeline degrades gracefully: a failing sub-service should downgrade its
signal to "unknown", never crash the whole analysis. These exceptions are for
genuinely unrecoverable request-level problems (bad input, unsupported type).
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class SentinelError(Exception):
    """Base class for expected, client-facing errors."""

    status_code = 400
    code = "sentinel_error"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class UnsupportedContentError(SentinelError):
    status_code = 415
    code = "unsupported_content"


class ContentTooLargeError(SentinelError):
    status_code = 413
    code = "content_too_large"


class NotFoundError(SentinelError):
    status_code = 404
    code = "not_found"


class RateLimitedError(SentinelError):
    status_code = 429
    code = "rate_limited"


class AuthError(SentinelError):
    status_code = 401
    code = "unauthorized"


async def sentinel_error_handler(_: Request, exc: SentinelError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )
