"""Opaque keyset-cursor primitives. Domain repositories define sort keys later."""

from __future__ import annotations

import base64
import json
from typing import Any


def encode_cursor(values: dict[str, Any]) -> str:
    """Encode a deterministic, opaque cursor without exposing SQL syntax."""

    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode an internally generated cursor and reject malformed values."""

    try:
        payload = base64.urlsafe_b64decode(cursor.encode("ascii"))
        result = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid pagination cursor") from exc
    if not isinstance(result, dict):
        raise ValueError("invalid pagination cursor")
    return result
