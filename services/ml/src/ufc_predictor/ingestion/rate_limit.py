"""Deterministic local rate-limit primitives for future permitted adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """Per-host policy from an approved source audit, never a guessed default."""

    requests_per_minute: int
    max_concurrency: int

    def __post_init__(self) -> None:
        if self.requests_per_minute < 1 or self.max_concurrency < 1:
            raise ValueError("rate-limit values must be positive")


@dataclass(slots=True)
class TokenBucket:
    """Small testable token bucket; a caller owns sleeping and host concurrency."""

    policy: RateLimitPolicy
    tokens: float = field(init=False)
    updated_at_seconds: float = field(default=0.0)

    def __post_init__(self) -> None:
        self.tokens = float(self.policy.requests_per_minute)

    def acquire_delay(self, now_seconds: float) -> float:
        """Reserve one request and return the delay needed before it may start."""

        if now_seconds < self.updated_at_seconds:
            raise ValueError("monotonic time must not move backward")
        rate_per_second = self.policy.requests_per_minute / 60
        elapsed = now_seconds - self.updated_at_seconds
        self.tokens = min(
            float(self.policy.requests_per_minute), self.tokens + elapsed * rate_per_second
        )
        self.updated_at_seconds = now_seconds
        if self.tokens >= 1:
            self.tokens -= 1
            return 0.0
        delay = (1 - self.tokens) / rate_per_second
        self.tokens = 0.0
        self.updated_at_seconds = now_seconds + delay
        return delay


def parse_retry_after(value: str | None, *, now: datetime) -> float | None:
    """Parse seconds or an HTTP-date without silently ignoring server backoff instructions."""

    if value is None:
        return None
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    stripped = value.strip()
    if stripped.isdecimal():
        return float(stripped)
    try:
        retry_at = parsedate_to_datetime(stripped)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0.0, (retry_at.astimezone(UTC) - now.astimezone(UTC)).total_seconds())
