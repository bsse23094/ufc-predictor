"""Source-neutral ingestion contracts.

These types deliberately carry opaque source payloads.  An adapter may be
implemented only after its source-policy audit supplies observed fields and a
permitted access method.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ufc_predictor.ingestion.validation import ValidatedRecord


def require_utc(value: datetime) -> datetime:
    """Return a UTC timestamp and reject ambiguous naive timestamps."""

    if value.tzinfo is None:
        raise ValueError("ingestion timestamps must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class WorkUnit:
    """One adapter-discovered item to retrieve, without assuming its format."""

    source_key: str
    unit_key: str
    locator: str
    discovered_at: datetime
    attributes: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.source_key or not self.unit_key or not self.locator:
            raise ValueError("source_key, unit_key, and locator are required")
        object.__setattr__(self, "discovered_at", require_utc(self.discovered_at))


@dataclass(frozen=True, slots=True)
class FetchResponse:
    """Unparsed transport response that must be persisted before parsing."""

    work_unit: WorkUnit
    requested_at: datetime
    retrieved_at: datetime
    status_code: int
    headers: Mapping[str, str]
    content: bytes
    content_type: str | None = None
    source_modified_at: datetime | None = None

    def __post_init__(self) -> None:
        if not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be an HTTP status code")
        object.__setattr__(self, "requested_at", require_utc(self.requested_at))
        object.__setattr__(self, "retrieved_at", require_utc(self.retrieved_at))
        if self.retrieved_at < self.requested_at:
            raise ValueError("retrieved_at must not precede requested_at")
        if self.source_modified_at is not None:
            object.__setattr__(self, "source_modified_at", require_utc(self.source_modified_at))


@dataclass(frozen=True, slots=True)
class RawReference:
    """Immutable raw-object identity supplied to every parsed source record."""

    sha256: str
    object_uri: str
    retrieval_manifest_uri: str

    def __post_init__(self) -> None:
        if len(self.sha256) != 64 or any(char not in "0123456789abcdef" for char in self.sha256):
            raise ValueError("sha256 must be a lowercase SHA-256 digest")
        if not self.object_uri or not self.retrieval_manifest_uri:
            raise ValueError("raw reference URIs are required")


@dataclass(frozen=True, slots=True)
class SchemaFingerprint:
    """Adapter-owned fingerprint derived only from observed source structure."""

    value: str
    parser_version: str

    def __post_init__(self) -> None:
        if not self.value or not self.parser_version:
            raise ValueError("schema fingerprint and parser version are required")

    @classmethod
    def from_markers(cls, markers: Iterable[str], *, parser_version: str) -> SchemaFingerprint:
        """Create a stable fingerprint from an adapter's audited structure markers."""

        normalized = tuple(sorted(marker.strip() for marker in markers if marker.strip()))
        if not normalized:
            raise ValueError("at least one observed schema marker is required")
        digest = sha256("\x00".join(normalized).encode("utf-8")).hexdigest()
        return cls(value=f"sha256:{digest}", parser_version=parser_version)


@dataclass(frozen=True, slots=True)
class ParsedRecord:
    """Source-shaped record with provenance; canonical mapping belongs to a later milestone."""

    record_key: str
    raw_reference: RawReference
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.record_key:
            raise ValueError("record_key is required")


class TransientFetchError(RuntimeError):
    """A retriable transport failure reported by a source adapter.

    Adapters translate bounded timeout, connection, 429, and transient-server
    failures into this type. They must not retry parser or schema failures.
    """

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        if retry_after_seconds is not None and retry_after_seconds < 0:
            raise ValueError("retry_after_seconds must be non-negative")
        self.retry_after_seconds = retry_after_seconds


class SourceAdapter(Protocol):
    """Protocol for a permitted, source-specific adapter.

    Implementations must not be registered until a completed source audit has
    supplied terms, rate policy, fixtures, fingerprints, and an allow-list.
    """

    source_key: str
    parser_version: str

    def discover(self, checkpoint: Mapping[str, object] | None) -> Iterable[WorkUnit]:
        """Return bounded work discovered from the last durable checkpoint."""

    async def fetch(self, work_unit: WorkUnit) -> FetchResponse:
        """Fetch a work unit under the registry-controlled rate policy."""

    def fingerprint(self, response: FetchResponse) -> SchemaFingerprint:
        """Return the fingerprint of observed source structure."""

    def parse(self, response: FetchResponse, raw_reference: RawReference) -> Iterable[ParsedRecord]:
        """Parse a known fingerprint into source-shaped, provenance-linked records."""

    def validate(self, records: Iterable[ParsedRecord]) -> Iterable[ValidatedRecord]:
        """Account for every parsed record before it can leave ingestion."""
