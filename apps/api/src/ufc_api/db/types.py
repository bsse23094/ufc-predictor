"""Small domain-neutral helpers for UTC and immutable-content handling."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256


def require_utc(value: datetime) -> datetime:
    """Normalize an aware timestamp to UTC and reject naive timestamps."""

    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)


def content_sha256(content: bytes) -> str:
    """Return the stable SHA-256 used by later immutable manifests."""

    return sha256(content).hexdigest()
