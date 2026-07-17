"""Idempotent, policy-gated ingestion execution and checkpoint rules."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from time import monotonic
from typing import Protocol
from uuid import uuid4

from ufc_predictor.ingestion.base import (
    FetchResponse,
    ParsedRecord,
    RawReference,
    SourceAdapter,
    TransientFetchError,
    WorkUnit,
)
from ufc_predictor.ingestion.rate_limit import TokenBucket, parse_retry_after
from ufc_predictor.ingestion.raw_store import RawWriteRequest
from ufc_predictor.ingestion.registry import SourcePolicy, SourceRegistry
from ufc_predictor.ingestion.validation import (
    RecordDisposition,
    RowAccounting,
    SchemaGate,
    TransportPolicy,
    ValidatedRecord,
    ValidationReport,
)


class IngestionRunState(StrEnum):
    """Durable run lifecycle; only published runs expose a new checkpoint."""

    REQUESTED = "requested"
    FETCHING = "fetching"
    PARSED = "parsed"
    VALIDATED = "validated"
    PUBLISHED = "published"
    FAILED = "failed"
    QUARANTINED = "quarantined"


_ALLOWED_TRANSITIONS: dict[IngestionRunState, frozenset[IngestionRunState]] = {
    IngestionRunState.REQUESTED: frozenset({IngestionRunState.FETCHING, IngestionRunState.FAILED}),
    IngestionRunState.FETCHING: frozenset(
        {IngestionRunState.PARSED, IngestionRunState.QUARANTINED, IngestionRunState.FAILED}
    ),
    IngestionRunState.PARSED: frozenset(
        {IngestionRunState.VALIDATED, IngestionRunState.QUARANTINED, IngestionRunState.FAILED}
    ),
    IngestionRunState.VALIDATED: frozenset(
        {IngestionRunState.PUBLISHED, IngestionRunState.QUARANTINED, IngestionRunState.FAILED}
    ),
    IngestionRunState.PUBLISHED: frozenset(),
    IngestionRunState.FAILED: frozenset(),
    IngestionRunState.QUARANTINED: frozenset(),
}


@dataclass(slots=True)
class IngestionRun:
    """Source-neutral state machine used by future durable run persistence."""

    source_key: str
    mode: str
    previous_checkpoint: Mapping[str, object] | None = None
    run_id: str = field(default_factory=lambda: uuid4().hex)
    state: IngestionRunState = IngestionRunState.REQUESTED
    accounting: RowAccounting | None = None
    report: ValidationReport | None = None
    _candidate_checkpoint: Mapping[str, object] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.source_key or not self.mode:
            raise ValueError("source_key and mode are required")

    @property
    def idempotency_key(self) -> str:
        """Hash source/mode/checkpoint deterministically without embedding its values in logs."""

        payload = {
            "source_key": self.source_key,
            "mode": self.mode,
            "previous_checkpoint": self.previous_checkpoint or {},
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def new_checkpoint(self) -> Mapping[str, object] | None:
        """Expose a checkpoint only after it has crossed the publication boundary."""

        if self.state is IngestionRunState.PUBLISHED:
            return self._candidate_checkpoint
        return None

    def transition(self, target: IngestionRunState) -> None:
        """Enforce lifecycle ordering rather than accepting arbitrary status writes."""

        if target not in _ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"invalid ingestion run transition: {self.state} -> {target}")
        self.state = target

    def record_validation(
        self,
        *,
        accounting: RowAccounting,
        report: ValidationReport,
        candidate_checkpoint: Mapping[str, object] | None,
    ) -> None:
        """Balance rows and quarantine before a checkpoint can become durable."""

        if self.state is not IngestionRunState.PARSED:
            raise ValueError("validation may be recorded only after parsing")
        accounting.assert_balanced()
        self.accounting = accounting
        self.report = report
        if report.allows_publication:
            self._candidate_checkpoint = dict(candidate_checkpoint or {})
            self.transition(IngestionRunState.VALIDATED)
        else:
            self.transition(IngestionRunState.QUARANTINED)

    def publish(self) -> None:
        """Mark a validated run as published; callers persist this transactionally later."""

        if self.state is not IngestionRunState.VALIDATED:
            raise ValueError("only a validated ingestion run may publish")
        self.transition(IngestionRunState.PUBLISHED)

    def restore_persisted(
        self,
        *,
        run_id: str,
        state: IngestionRunState,
        accounting: RowAccounting | None,
        new_checkpoint: Mapping[str, object] | None,
    ) -> None:
        """Restore a durable idempotency result without replaying completed work."""

        if not run_id:
            raise ValueError("persisted ingestion run ID is required")
        self.run_id = run_id
        self.state = state
        self.accounting = accounting
        self._candidate_checkpoint = dict(new_checkpoint or {})

    def quarantine(self, *, accounting: RowAccounting, report: ValidationReport) -> None:
        """Record a non-publishable result from fetching or parsing without losing counts."""

        if self.state not in {IngestionRunState.FETCHING, IngestionRunState.PARSED}:
            raise ValueError("a run may be quarantined only while fetching or parsing")
        accounting.assert_balanced()
        if report.allows_publication:
            raise ValueError("a quarantined run requires at least one quarantine or blocking issue")
        self.accounting = accounting
        self.report = report
        self.transition(IngestionRunState.QUARANTINED)


class RawStore(Protocol):
    """Persistence port used by the executor before any parsing occurs."""

    def persist(self, request: RawWriteRequest) -> RawReference:
        """Store exact bytes and return their immutable provenance reference."""


@dataclass(frozen=True, slots=True)
class PersistedIngestionRun:
    """Minimal durable state needed to preserve safe idempotency semantics."""

    run_id: str
    state: IngestionRunState
    accounting: RowAccounting | None = None
    new_checkpoint: Mapping[str, object] | None = None


class IngestionPersistence(Protocol):
    """Durable boundary owned by the application data-governance context.

    The ML package depends only on this port.  PostgreSQL/SQLAlchemy remain on
    the API side, so ingestion orchestration does not import application
    internals or bypass their transactions.
    """

    async def begin_run(
        self, *, run: IngestionRun, policy: SourcePolicy, parser_version: str
    ) -> PersistedIngestionRun:
        """Create, retry, or resolve one idempotent durable run."""

    async def record_state(self, *, run: IngestionRun) -> None:
        """Persist a nonterminal lifecycle transition."""

    async def record_raw_response(
        self,
        *,
        run: IngestionRun,
        policy: SourcePolicy,
        request: RawWriteRequest,
        raw_reference: RawReference,
    ) -> None:
        """Record a raw object and append-only retrieval after bytes are stored."""

    async def finalize_run(self, *, run: IngestionRun, error_summary: str | None = None) -> None:
        """Commit terminal accounting, issues, and checkpoint visibility."""


@dataclass(frozen=True, slots=True)
class FetchRetryPolicy:
    """Bounded retry policy for transport failures only."""

    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 15.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("retry delays must be non-negative and ordered")

    def delay_for_attempt(self, attempt: int, *, retry_after_seconds: float | None = None) -> float:
        """Return a capped exponential delay while respecting a server backoff if supplied."""

        if attempt < 1:
            raise ValueError("attempt must be at least one")
        exponential: float = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** (attempt - 1)),
        )
        return float(max(exponential, retry_after_seconds or 0.0))


@dataclass(frozen=True, slots=True)
class IngestionExecutionResult:
    """Source-neutral execution output; only published records may proceed downstream."""

    run: IngestionRun
    raw_references: tuple[RawReference, ...]
    records: tuple[ParsedRecord, ...]
    replayed: bool = False


class IngestionExecutor:
    """Execute a bounded audited adapter without granting it publication authority.

    The executor is intentionally sequential: one active request always satisfies
    the source's audited concurrency cap, while the token bucket enforces its
    request-rate cap. Source-specific adapters own discovery, parsing, and
    record-level validation; this boundary owns policy checks, persistence order,
    retries, schema quarantine, and run accounting.
    """

    def __init__(
        self,
        *,
        registry: SourceRegistry,
        raw_store: RawStore,
        schema_gate: SchemaGate,
        transport_policy: TransportPolicy,
        retry_policy: FetchRetryPolicy | None = None,
        persistence: IngestionPersistence | None = None,
        max_work_units: int = 1_000,
        clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if max_work_units < 1:
            raise ValueError("max_work_units must be positive")
        self._registry = registry
        self._raw_store = raw_store
        self._schema_gate = schema_gate
        self._transport_policy = transport_policy
        self._retry_policy = retry_policy or FetchRetryPolicy()
        self._persistence = persistence
        self._max_work_units = max_work_units
        self._clock = clock
        self._sleeper = sleeper

    async def execute(
        self,
        *,
        adapter: SourceAdapter,
        mode: str,
        previous_checkpoint: Mapping[str, object] | None,
        candidate_checkpoint: Mapping[str, object] | None,
    ) -> IngestionExecutionResult:
        """Persist, validate, and account for a bounded run without canonical publication."""

        policy = self._registry.require_enabled(adapter.source_key)
        if policy.rate_limit is None:  # Narrowing for static analysis and future registry ports.
            raise RuntimeError("enabled source policy unexpectedly has no rate limit")
        run = IngestionRun(
            source_key=adapter.source_key,
            mode=mode,
            previous_checkpoint=previous_checkpoint,
        )
        if self._persistence is not None:
            persisted = await self._persistence.begin_run(
                run=run,
                policy=policy,
                parser_version=adapter.parser_version,
            )
            run.restore_persisted(
                run_id=persisted.run_id,
                state=persisted.state,
                accounting=persisted.accounting,
                new_checkpoint=persisted.new_checkpoint,
            )
            if run.state is IngestionRunState.PUBLISHED:
                return IngestionExecutionResult(run, (), (), replayed=True)

        raw_references: list[RawReference] = []
        validated_records: list[ValidatedRecord] = []
        try:
            work_units = self._bounded_work_units(adapter, previous_checkpoint)
            bucket = TokenBucket(policy.rate_limit)
            run.transition(IngestionRunState.FETCHING)
            await self._record_state(run)

            for work_unit in work_units:
                response, raw_reference = await self._fetch_with_retry(
                    adapter=adapter,
                    work_unit=work_unit,
                    policy=policy,
                    ingestion_run=run,
                    bucket=bucket,
                )
                raw_references.extend(raw_reference)
                transport_report = self._transport_policy.assess(
                    status_code=response.status_code,
                    byte_length=len(response.content),
                )
                if not transport_report.allows_publication:
                    return await self._quarantined_result(
                        run=run,
                        raw_references=raw_references,
                        validated_records=validated_records,
                        extra_quarantined=1,
                        report=transport_report,
                    )

                persisted_reference = raw_reference[-1]
                fingerprint = adapter.fingerprint(response)
                schema_report = self._schema_gate.assess(
                    fingerprint,
                    raw_sha256=persisted_reference.sha256,
                )
                if not schema_report.allows_publication:
                    return await self._quarantined_result(
                        run=run,
                        raw_references=raw_references,
                        validated_records=validated_records,
                        extra_quarantined=1,
                        report=schema_report,
                    )

                parsed_records = tuple(adapter.parse(response, persisted_reference))
                newly_validated_records = tuple(adapter.validate(parsed_records))
                self._assert_all_records_accounted_for(parsed_records, newly_validated_records)
                validated_records.extend(newly_validated_records)

            run.transition(IngestionRunState.PARSED)
            await self._record_state(run)
            accounting = self._accounting(validated_records)
            report = ValidationReport(
                issues=tuple(issue for record in validated_records for issue in record.issues)
            )
            run.record_validation(
                accounting=accounting,
                report=report,
                candidate_checkpoint=candidate_checkpoint,
            )
            if run.state is IngestionRunState.QUARANTINED:
                return await self._finalize_quarantined_result(run, raw_references)
            await self._record_state(run)
            run.publish()
            await self._finalize_run(run)
            return IngestionExecutionResult(
                run,
                tuple(raw_references),
                tuple(
                    record.record
                    for record in validated_records
                    if record.disposition is RecordDisposition.ACCEPTED
                ),
            )
        except Exception as exc:
            if run.state not in {
                IngestionRunState.PUBLISHED,
                IngestionRunState.QUARANTINED,
                IngestionRunState.FAILED,
            }:
                run.transition(IngestionRunState.FAILED)
                await self._finalize_run(
                    run, error_summary=f"{type(exc).__name__}: execution failed"
                )
            raise

    def _bounded_work_units(
        self,
        adapter: SourceAdapter,
        checkpoint: Mapping[str, object] | None,
    ) -> tuple[WorkUnit, ...]:
        work_units: list[WorkUnit] = []
        for work_unit in adapter.discover(checkpoint):
            if work_unit.source_key != adapter.source_key:
                raise ValueError("adapter returned a work unit for a different source")
            if len(work_units) >= self._max_work_units:
                raise ValueError(
                    "adapter discovery exceeded the configured bounded work-unit limit"
                )
            work_units.append(work_unit)
        return tuple(work_units)

    async def _fetch_with_retry(
        self,
        *,
        adapter: SourceAdapter,
        work_unit: WorkUnit,
        policy: SourcePolicy,
        ingestion_run: IngestionRun,
        bucket: TokenBucket,
    ) -> tuple[FetchResponse, tuple[RawReference, ...]]:
        raw_references: list[RawReference] = []
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            rate_delay = bucket.acquire_delay(self._clock())
            if rate_delay:
                await self._sleeper(rate_delay)
            try:
                response = await adapter.fetch(work_unit)
            except TransientFetchError as exc:
                if attempt == self._retry_policy.max_attempts:
                    raise RuntimeError("transient fetch retries exhausted") from exc
                await self._sleeper(
                    self._retry_policy.delay_for_attempt(
                        attempt,
                        retry_after_seconds=exc.retry_after_seconds,
                    )
                )
                continue
            if response.work_unit != work_unit:
                raise ValueError("adapter response does not belong to the requested work unit")
            raw_reference = self._raw_store.persist(
                RawWriteRequest(
                    source_key=policy.source_key,
                    ingestion_run_id=ingestion_run.run_id,
                    source_locator=work_unit.locator,
                    requested_at=response.requested_at,
                    retrieved_at=response.retrieved_at,
                    source_modified_at=response.source_modified_at,
                    content=response.content,
                    retrieval_code_version=adapter.parser_version,
                    terms_policy_version=policy.terms_policy_version or "",
                    dataset_license=policy.dataset_license,
                    http_status=response.status_code,
                    http_headers=response.headers,
                    content_type=response.content_type,
                    original_filename=_work_unit_string_attribute(work_unit, "original_filename"),
                    source_schema_version=_work_unit_string_attribute(
                        work_unit, "source_schema_version"
                    ),
                    attribution=policy.attribution,
                )
            )
            raw_references.append(raw_reference)
            if self._persistence is not None:
                await self._persistence.record_raw_response(
                    run=ingestion_run,
                    policy=policy,
                    request=RawWriteRequest(
                        source_key=policy.source_key,
                        ingestion_run_id=ingestion_run.run_id,
                        source_locator=work_unit.locator,
                        requested_at=response.requested_at,
                        retrieved_at=response.retrieved_at,
                        source_modified_at=response.source_modified_at,
                        content=response.content,
                        retrieval_code_version=adapter.parser_version,
                        terms_policy_version=policy.terms_policy_version or "",
                        dataset_license=policy.dataset_license,
                        http_status=response.status_code,
                        http_headers=response.headers,
                        content_type=response.content_type,
                        original_filename=_work_unit_string_attribute(
                            work_unit, "original_filename"
                        ),
                        source_schema_version=_work_unit_string_attribute(
                            work_unit, "source_schema_version"
                        ),
                        attribution=policy.attribution,
                    ),
                    raw_reference=raw_reference,
                )
            if (
                not self._is_transient_response(response)
                or attempt == self._retry_policy.max_attempts
            ):
                return response, tuple(raw_references)
            retry_after = parse_retry_after(
                response.headers.get("retry-after"), now=response.retrieved_at
            )
            await self._sleeper(
                self._retry_policy.delay_for_attempt(attempt, retry_after_seconds=retry_after)
            )
        raise AssertionError("retry loop must return or raise")

    @staticmethod
    def _is_transient_response(response: FetchResponse) -> bool:
        return response.status_code == 429 or 500 <= response.status_code <= 599

    @staticmethod
    def _assert_all_records_accounted_for(
        parsed_records: tuple[ParsedRecord, ...],
        validated_records: tuple[ValidatedRecord, ...],
    ) -> None:
        def record_identity(record: ParsedRecord) -> tuple[str, str, str]:
            return (
                record.record_key,
                record.raw_reference.sha256,
                record.raw_reference.retrieval_manifest_uri,
            )

        expected = Counter(record_identity(record) for record in parsed_records)
        actual = Counter(record_identity(record.record) for record in validated_records)
        if expected != actual:
            raise ValueError("adapter validation must account for every parsed record exactly once")

    @staticmethod
    def _accounting(records: list[ValidatedRecord], *, extra_quarantined: int = 0) -> RowAccounting:
        accepted = sum(record.disposition is RecordDisposition.ACCEPTED for record in records)
        quarantined = sum(record.disposition is RecordDisposition.QUARANTINED for record in records)
        filtered = sum(record.disposition is RecordDisposition.FILTERED for record in records)
        return RowAccounting(
            input_count=len(records) + extra_quarantined,
            accepted_count=accepted,
            quarantined_count=quarantined + extra_quarantined,
            filtered_count=filtered,
        )

    async def _quarantined_result(
        self,
        *,
        run: IngestionRun,
        raw_references: list[RawReference],
        validated_records: list[ValidatedRecord],
        extra_quarantined: int,
        report: ValidationReport,
    ) -> IngestionExecutionResult:
        run.quarantine(
            accounting=self._accounting(validated_records, extra_quarantined=extra_quarantined),
            report=report,
        )
        return await self._finalize_quarantined_result(run, raw_references)

    async def _finalize_quarantined_result(
        self,
        run: IngestionRun,
        raw_references: list[RawReference],
    ) -> IngestionExecutionResult:
        await self._finalize_run(run)
        return IngestionExecutionResult(run, tuple(raw_references), ())

    async def _record_state(self, run: IngestionRun) -> None:
        if self._persistence is not None:
            await self._persistence.record_state(run=run)

    async def _finalize_run(self, run: IngestionRun, *, error_summary: str | None = None) -> None:
        if self._persistence is not None:
            await self._persistence.finalize_run(run=run, error_summary=error_summary)


def _work_unit_string_attribute(work_unit: WorkUnit, name: str) -> str | None:
    """Return an optional audited string attribute without coercing arbitrary payloads."""

    value = work_unit.attributes.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"work unit attribute '{name}' must be a string")
    return value
