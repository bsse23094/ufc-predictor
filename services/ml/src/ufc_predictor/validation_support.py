"""Small dependency-free integrity helpers shared by ingestion primitives."""

from __future__ import annotations

from hashlib import sha256


def content_sha256(content: bytes) -> str:
    """Return the exact-byte SHA-256 used by raw and later dataset manifests."""

    return sha256(content).hexdigest()
