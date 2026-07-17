"""Stable public error envelope and exception translation."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """A safe validation detail returned to API consumers."""

    field: str | None = None
    reason: str


class ApiErrorBody(BaseModel):
    """Architecture-defined API error payload."""

    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)
    request_id: str
    retryable: bool = False


class ApiErrorResponse(BaseModel):
    """Envelope used for every intentional API error."""

    error: ApiErrorBody


class DomainError(Exception):
    """A safe, structured error raised by a domain service."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        details: list[ErrorDetail] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []
        self.retryable = retryable


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Translate domain errors without exposing implementation details."""

    if not isinstance(exc, DomainError):
        return unexpected_error_response(request, exc)

    request_id = getattr(request.state, "request_id", "unknown")
    body = ApiErrorResponse(
        error=ApiErrorBody(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            request_id=request_id,
            retryable=exc.retryable,
        )
    )
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))


def unexpected_error_response(request: Request, _: Exception) -> JSONResponse:
    """Return the same safe envelope for unhandled errors."""

    request_id = getattr(request.state, "request_id", "unknown")
    response: dict[str, Any] = ApiErrorResponse(
        error=ApiErrorBody(
            code="internal_error",
            message="An unexpected error occurred.",
            request_id=request_id,
        )
    ).model_dump(mode="json")
    return JSONResponse(status_code=500, content=response)
