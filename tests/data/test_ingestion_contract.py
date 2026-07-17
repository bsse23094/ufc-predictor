from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ufc_predictor.ingestion.base import (
    FetchResponse,
    ParsedRecord,
    RawReference,
    SchemaFingerprint,
    WorkUnit,
)
from ufc_predictor.ingestion.rate_limit import RateLimitPolicy, TokenBucket, parse_retry_after
from ufc_predictor.ingestion.raw_store import LocalRawStore
from ufc_predictor.ingestion.registry import (
    SourceAuditState,
    SourcePolicy,
    SourcePolicyError,
    SourceRegistry,
)
from ufc_predictor.ingestion.runner import (
    FetchRetryPolicy,
    IngestionExecutor,
    IngestionRun,
    IngestionRunState,
)
from ufc_predictor.ingestion.validation import (
    RecordDisposition,
    RowAccounting,
    SchemaGate,
    TransportPolicy,
    ValidatedRecord,
)


class SyntheticAdapter:
    """A non-network adapter used only to verify source-neutral orchestration."""

    source_key = "synthetic-source"
    parser_version = "parser-v1"

    def __init__(self, *, statuses: list[int], fingerprint: SchemaFingerprint) -> None:
        self._statuses = statuses
        self._fingerprint = fingerprint
        self.parse_calls = 0

    def discover(self, checkpoint: Mapping[str, object] | None) -> Iterable[WorkUnit]:
        assert checkpoint == {"page": 1}
        return (
            WorkUnit(
                source_key=self.source_key,
                unit_key="unit-1",
                locator="https://example.invalid/fixture?token=secret",
                discovered_at=datetime(2026, 7, 17, tzinfo=UTC),
                attributes={},
            ),
        )

    async def fetch(self, work_unit: WorkUnit) -> FetchResponse:
        status = self._statuses.pop(0)
        return FetchResponse(
            work_unit=work_unit,
            requested_at=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
            retrieved_at=datetime(2026, 7, 17, 10, 1, tzinfo=UTC),
            status_code=status,
            headers={"retry-after": "3"} if status == 429 else {},
            content=f"fixture-{status}".encode(),
            content_type="application/json",
        )

    def fingerprint(self, response: FetchResponse) -> SchemaFingerprint:
        return self._fingerprint

    def parse(self, response: FetchResponse, raw_reference: RawReference) -> Iterable[ParsedRecord]:
        self.parse_calls += 1
        return (ParsedRecord(record_key="record-1", raw_reference=raw_reference, payload={}),)

    def validate(self, records: Iterable[ParsedRecord]) -> Iterable[ValidatedRecord]:
        return tuple(
            ValidatedRecord(record=record, disposition=RecordDisposition.ACCEPTED)
            for record in records
        )


def approved_enabled_registry() -> SourceRegistry:
    return SourceRegistry(
        [
            SourcePolicy(
                source_key="synthetic-source",
                audit_state=SourceAuditState.APPROVED,
                enabled=True,
                terms_policy_version="synthetic-terms-v1",
                retention_classification="test-only",
                approved_at=datetime(2026, 7, 17, tzinfo=UTC),
                audit_evidence_ref="tests/fixtures/synthetic-source-audit.md",
                rate_limit=RateLimitPolicy(requests_per_minute=60, max_concurrency=1),
            )
        ]
    )


def test_unapproved_or_disabled_source_cannot_be_resolved_for_fetching() -> None:
    registry = SourceRegistry([SourcePolicy(source_key="candidate")])

    with pytest.raises(SourcePolicyError, match="approved audit"):
        registry.require_enabled("candidate")


def test_approved_policy_still_requires_explicit_enablement() -> None:
    policy = SourcePolicy(
        source_key="candidate",
        audit_state=SourceAuditState.APPROVED,
        terms_policy_version="terms-v1",
        retention_classification="internal",
        approved_at=datetime(2026, 7, 17, tzinfo=UTC),
        audit_evidence_ref="docs/audits/candidate.md",
    )

    with pytest.raises(SourcePolicyError, match="disabled by policy"):
        SourceRegistry([policy]).require_enabled("candidate")


def test_unknown_schema_quarantines_run_and_never_exposes_new_checkpoint() -> None:
    fingerprint = SchemaFingerprint.from_markers(["observed-marker"], parser_version="parser-v1")
    report = SchemaGate().assess(fingerprint, raw_sha256="a" * 64)
    run = IngestionRun(source_key="candidate", mode="incremental", previous_checkpoint={"page": 1})
    run.transition(IngestionRunState.FETCHING)
    run.transition(IngestionRunState.PARSED)
    run.record_validation(
        accounting=RowAccounting(3, 0, 3, 0),
        report=report,
        candidate_checkpoint={"page": 2},
    )

    assert run.state is IngestionRunState.QUARANTINED
    assert run.new_checkpoint is None


def test_row_accounting_must_balance_before_validation() -> None:
    with pytest.raises(ValueError, match="does not balance"):
        RowAccounting(3, 2, 0, 0).assert_balanced()


def test_idempotency_key_is_stable_for_equivalent_checkpoints() -> None:
    first = IngestionRun(
        source_key="candidate", mode="incremental", previous_checkpoint={"b": 2, "a": 1}
    )
    second = IngestionRun(
        source_key="candidate", mode="incremental", previous_checkpoint={"a": 1, "b": 2}
    )

    assert first.idempotency_key == second.idempotency_key


def test_token_bucket_and_retry_after_are_deterministic() -> None:
    bucket = TokenBucket(RateLimitPolicy(requests_per_minute=2, max_concurrency=1))

    assert bucket.acquire_delay(0.0) == 0.0
    assert bucket.acquire_delay(0.0) == 0.0
    assert bucket.acquire_delay(0.0) == 30.0
    assert parse_retry_after("15", now=datetime(2026, 7, 17, tzinfo=UTC)) == 15.0


@pytest.mark.anyio
async def test_executor_persists_each_retry_before_parsing_and_publishes_only_accounted_records(
    tmp_path: Path,
) -> None:
    fingerprint = SchemaFingerprint.from_markers(["fixture-v1"], parser_version="parser-v1")
    adapter = SyntheticAdapter(statuses=[429, 200], fingerprint=fingerprint)
    delays: list[float] = []

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    executor = IngestionExecutor(
        registry=approved_enabled_registry(),
        raw_store=LocalRawStore(tmp_path / "raw"),
        schema_gate=SchemaGate(frozenset({fingerprint.value})),
        transport_policy=TransportPolicy(max_response_bytes=1_024),
        retry_policy=FetchRetryPolicy(max_attempts=2, base_delay_seconds=0.5, max_delay_seconds=2),
        clock=lambda: 0.0,
        sleeper=record_delay,
    )

    result = await executor.execute(
        adapter=adapter,
        mode="incremental",
        previous_checkpoint={"page": 1},
        candidate_checkpoint={"page": 2},
    )

    assert result.run.state is IngestionRunState.PUBLISHED
    assert result.run.new_checkpoint == {"page": 2}
    assert result.run.accounting == RowAccounting(1, 1, 0, 0)
    assert len(result.raw_references) == 2
    assert len(result.records) == 1
    assert delays == [3.0]


@pytest.mark.anyio
async def test_executor_quarantines_unknown_schema_after_preserving_raw_bytes(
    tmp_path: Path,
) -> None:
    unknown_fingerprint = SchemaFingerprint.from_markers(["unknown"], parser_version="parser-v1")
    adapter = SyntheticAdapter(statuses=[200], fingerprint=unknown_fingerprint)
    raw_store = LocalRawStore(tmp_path / "raw")
    executor = IngestionExecutor(
        registry=approved_enabled_registry(),
        raw_store=raw_store,
        schema_gate=SchemaGate(),
        transport_policy=TransportPolicy(max_response_bytes=1_024),
    )

    result = await executor.execute(
        adapter=adapter,
        mode="incremental",
        previous_checkpoint={"page": 1},
        candidate_checkpoint={"page": 2},
    )

    assert result.run.state is IngestionRunState.QUARANTINED
    assert result.run.new_checkpoint is None
    assert result.run.accounting == RowAccounting(1, 0, 1, 0)
    assert len(result.raw_references) == 1
    assert result.records == ()
    assert adapter.parse_calls == 0
    assert (raw_store.root / result.raw_references[0].object_uri).read_bytes() == b"fixture-200"
