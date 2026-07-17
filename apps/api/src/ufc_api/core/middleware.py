"""Request correlation and conservative HTTP protection middleware."""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach and return a request ID while adding baseline security headers."""

    def __init__(self, app: ASGIApp, request_id_header: str) -> None:
        super().__init__(app)
        self.request_id_header = request_id_header

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(self.request_id_header, str(uuid4()))
        request.state.request_id = request_id
        started_at = perf_counter()
        response = await call_next(request)
        response.headers[self.request_id_header] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Response-Time-Ms"] = f"{(perf_counter() - started_at) * 1000:.2f}"
        return response
