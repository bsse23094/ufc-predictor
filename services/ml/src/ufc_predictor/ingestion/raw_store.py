"""Local immutable raw storage with content addressing and safe retrieval manifests."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from ufc_predictor.ingestion.base import RawReference, require_utc
from ufc_predictor.validation_support import content_sha256

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_HEADER_NAMES = frozenset(
    {"content-length", "content-type", "etag", "last-modified", "retry-after"}
)


class RawIntegrityError(RuntimeError):
    """Raised when an existing content-addressed object does not match its key."""


@dataclass(frozen=True, slots=True)
class RawWriteRequest:
    """Exact unparsed bytes plus audited retrieval metadata to preserve."""

    source_key: str
    ingestion_run_id: str
    source_locator: str
    requested_at: datetime
    retrieved_at: datetime
    content: bytes
    retrieval_code_version: str
    terms_policy_version: str
    dataset_license: str | None = None
    source_modified_at: datetime | None = None
    http_status: int | None = None
    http_headers: Mapping[str, str] | None = None
    content_type: str | None = None
    secrecy_classification: str = "internal"
    original_filename: str | None = None
    source_schema_version: str | None = None
    attribution: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("source_key", self.source_key),
            ("ingestion_run_id", self.ingestion_run_id),
            ("source_locator", self.source_locator),
            ("retrieval_code_version", self.retrieval_code_version),
            ("terms_policy_version", self.terms_policy_version),
        ):
            if not value:
                raise ValueError(f"{name} is required")
        _assert_safe_component(self.source_key, "source_key")
        _assert_safe_component(self.ingestion_run_id, "ingestion_run_id")
        if self.http_status is not None and not 100 <= self.http_status <= 599:
            raise ValueError("http_status must be an HTTP status code")
        if self.original_filename is not None:
            _assert_safe_component(self.original_filename, "original_filename")
        object.__setattr__(self, "requested_at", require_utc(self.requested_at))
        object.__setattr__(self, "retrieved_at", require_utc(self.retrieved_at))
        if self.source_modified_at is not None:
            object.__setattr__(self, "source_modified_at", require_utc(self.source_modified_at))


@dataclass(frozen=True, slots=True)
class RawObjectManifest:
    """Retrieval-event sidecar; each retrieval is retained even when bytes deduplicate."""

    source_key: str
    ingestion_run_id: str
    source_locator: str
    requested_at: str
    retrieved_at: str
    source_modified_at: str | None
    http_status: int | None
    http_headers: Mapping[str, str]
    content_type: str | None
    byte_length: int
    sha256: str
    retrieval_code_version: str
    terms_policy_version: str
    dataset_license: str | None
    secrecy_classification: str
    object_uri: str
    original_filename: str | None
    source_schema_version: str | None
    attribution: str | None


class LocalRawStore:
    """Filesystem implementation for local development and deterministic contract tests.

    The configured root is the raw zone itself.  Content blobs are written once
    under their SHA-256; retrieval manifests are append-only sidecars.  A
    production object-store adapter must retain these immutable semantics.
    """

    def __init__(self, root: Path, *, max_object_bytes: int = 10_485_760) -> None:
        if max_object_bytes < 1:
            raise ValueError("max_object_bytes must be positive")
        self.root = root.resolve()
        self.max_object_bytes = max_object_bytes

    def persist(self, request: RawWriteRequest) -> RawReference:
        """Persist bytes before parsing and return content plus retrieval provenance."""

        if len(request.content) > self.max_object_bytes:
            raise ValueError("raw object exceeds configured maximum size")
        digest = content_sha256(request.content)
        object_uri = f"objects/{digest}"
        object_path = self.root / object_uri
        self._write_content_once(object_path, request.content, digest)

        retrieval_id = uuid4().hex
        date_segment = request.retrieved_at.date().isoformat()
        manifest_uri = (
            f"retrievals/{request.source_key}/{date_segment}/"
            f"{request.ingestion_run_id}/{retrieval_id}.json"
        )
        manifest = RawObjectManifest(
            source_key=request.source_key,
            ingestion_run_id=request.ingestion_run_id,
            source_locator=redact_locator(request.source_locator),
            requested_at=request.requested_at.isoformat(),
            retrieved_at=request.retrieved_at.isoformat(),
            source_modified_at=(
                request.source_modified_at.isoformat()
                if request.source_modified_at is not None
                else None
            ),
            http_status=request.http_status,
            http_headers=sanitize_headers(request.http_headers or {}),
            content_type=request.content_type,
            byte_length=len(request.content),
            sha256=digest,
            retrieval_code_version=request.retrieval_code_version,
            terms_policy_version=request.terms_policy_version,
            dataset_license=request.dataset_license,
            secrecy_classification=request.secrecy_classification,
            object_uri=object_uri,
            original_filename=request.original_filename,
            source_schema_version=request.source_schema_version,
            attribution=request.attribution,
        )
        self._publish_once(
            self.root / manifest_uri,
            json.dumps(asdict(manifest), sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )
        return RawReference(
            sha256=digest,
            object_uri=object_uri,
            retrieval_manifest_uri=manifest_uri,
        )

    def _write_content_once(self, path: Path, content: bytes, expected_sha256: str) -> None:
        try:
            self._publish_once(path, content)
        except FileExistsError:
            actual_sha256 = content_sha256(path.read_bytes())
            if actual_sha256 != expected_sha256:
                raise RawIntegrityError(
                    f"existing raw object at {path} does not match content-addressed key"
                ) from None

    @staticmethod
    def _publish_once(path: Path, content: bytes) -> None:
        """Publish bytes without replacing an existing object on either supported OS."""

        path.parent.mkdir(parents=True, exist_ok=True)
        staging_path = path.with_name(f".{path.name}.{uuid4().hex}.staging")
        try:
            with staging_path.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(staging_path, path)
        finally:
            staging_path.unlink(missing_ok=True)


def sanitize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Retain only non-secret, useful response metadata in a bounded form."""

    sanitized: dict[str, str] = {}
    for name, value in headers.items():
        normalized_name = name.lower().strip()
        if normalized_name in _SAFE_HEADER_NAMES:
            sanitized[normalized_name] = value.strip()[:512]
    return sanitized


def redact_locator(locator: str) -> str:
    """Strip URL credentials, query strings, and fragments from stored lineage."""

    parsed = urlsplit(locator)
    if not parsed.scheme or not parsed.netloc:
        return locator.split("?", maxsplit=1)[0].split("#", maxsplit=1)[0]
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _assert_safe_component(value: str, field_name: str) -> None:
    if not _SAFE_COMPONENT.fullmatch(value):
        raise ValueError(f"{field_name} must be a safe storage path component")
