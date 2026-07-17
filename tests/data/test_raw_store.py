from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ufc_predictor.ingestion.raw_store import LocalRawStore, RawWriteRequest
from ufc_predictor.validation_support import content_sha256


def _request(*, run_id: str, content: bytes = b"synthetic raw bytes") -> RawWriteRequest:
    return RawWriteRequest(
        source_key="synthetic-source",
        ingestion_run_id=run_id,
        source_locator="https://user:secret@example.invalid/resource?token=secret#fragment",
        requested_at=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
        retrieved_at=datetime(2026, 7, 17, 10, 1, tzinfo=UTC),
        content=content,
        retrieval_code_version="test-v1",
        terms_policy_version="synthetic-terms-v1",
        http_status=200,
        http_headers={"ETag": "abc", "Authorization": "Bearer secret"},
        content_type="application/octet-stream",
    )


def test_raw_store_preserves_exact_bytes_deduplicates_content_and_appends_retrievals(
    tmp_path: Path,
) -> None:
    store = LocalRawStore(tmp_path / "raw")
    first = store.persist(_request(run_id="run-one"))
    second = store.persist(_request(run_id="run-two"))

    assert first.sha256 == content_sha256(b"synthetic raw bytes")
    assert first.object_uri == second.object_uri
    assert first.retrieval_manifest_uri != second.retrieval_manifest_uri
    assert (store.root / first.object_uri).read_bytes() == b"synthetic raw bytes"

    manifests = list((store.root / "retrievals").rglob("*.json"))
    assert len(manifests) == 2
    manifest = json.loads((store.root / first.retrieval_manifest_uri).read_text(encoding="utf-8"))
    assert manifest["source_locator"] == "https://example.invalid/resource"
    assert manifest["http_headers"] == {"etag": "abc"}
    assert "secret" not in json.dumps(manifest)


def test_raw_store_rejects_oversized_objects_before_writing(tmp_path: Path) -> None:
    store = LocalRawStore(tmp_path / "raw", max_object_bytes=4)

    with pytest.raises(ValueError, match="exceeds configured maximum"):
        store.persist(_request(run_id="run-one", content=b"five!"))

    assert not (store.root / "objects").exists()
