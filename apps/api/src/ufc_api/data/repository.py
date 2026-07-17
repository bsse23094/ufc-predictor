"""PostgreSQL persistence for source-neutral ingestion governance.

This adapter implements the ML package's narrow persistence port.  It owns the
SQLAlchemy models and keeps raw-object metadata, retrievals, run accounting,
quality issues, and checkpoint visibility in the transactional API boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ufc_api.data.models import (
    DataQualityIssue,
    DataSource,
    IngestionRunRecord,
    RawObject,
    RawRetrieval,
)
from ufc_predictor.ingestion.base import RawReference
from ufc_predictor.ingestion.raw_store import RawWriteRequest, redact_locator, sanitize_headers
from ufc_predictor.ingestion.registry import SourcePolicy, SourcePolicyError
from ufc_predictor.ingestion.runner import (
    IngestionRun,
    IngestionRunState,
    PersistedIngestionRun,
)
from ufc_predictor.ingestion.validation import IssueSeverity, RowAccounting


class IngestionRunConflictError(RuntimeError):
    """Raised when an equivalent run is already active and cannot be safely replayed."""


class DataGovernanceRepository:
    """Persist M2 ingestion state without teaching the ML package SQLAlchemy."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def begin_run(
        self, *, run: IngestionRun, policy: SourcePolicy, parser_version: str
    ) -> PersistedIngestionRun:
        """Create one durable run, retry a terminal failure, or return a published replay."""

        if policy.rate_limit is None:
            raise SourcePolicyError(f"source '{policy.source_key}' has no audited rate policy")

        async with self._session_factory() as session, session.begin():
            source = await self._load_matching_source(session, policy)
            create = (
                insert(IngestionRunRecord)
                .values(
                    source_id=source.source_id,
                    mode=run.mode,
                    idempotency_key=run.idempotency_key,
                    parser_version=parser_version,
                    status=IngestionRunState.REQUESTED.value,
                    previous_checkpoint=dict(run.previous_checkpoint or {}),
                    requested_at=_utc_now(),
                )
                .on_conflict_do_nothing(index_elements=["source_id", "idempotency_key"])
                .returning(IngestionRunRecord.ingestion_run_id)
            )
            created_run_id = (await session.execute(create)).scalar_one_or_none()
            if created_run_id is not None:
                return PersistedIngestionRun(
                    run_id=str(created_run_id), state=IngestionRunState.REQUESTED
                )

            existing = await session.scalar(
                select(IngestionRunRecord)
                .where(
                    IngestionRunRecord.source_id == source.source_id,
                    IngestionRunRecord.idempotency_key == run.idempotency_key,
                )
                .with_for_update()
            )
            if (
                existing is None
            ):  # Defensive guard against a database anomaly after conflict handling.
                raise RuntimeError("idempotent ingestion run could not be resolved")
            state = _run_state(existing.status)
            if state is IngestionRunState.PUBLISHED:
                return PersistedIngestionRun(
                    run_id=str(existing.ingestion_run_id),
                    state=state,
                    accounting=_row_accounting(existing),
                    new_checkpoint=existing.new_checkpoint,
                )
            if state in {IngestionRunState.FAILED, IngestionRunState.QUARANTINED}:
                existing.status = IngestionRunState.REQUESTED.value
                existing.attempt += 1
                existing.started_at = None
                existing.completed_at = None
                existing.published_at = None
                existing.input_count = 0
                existing.accepted_count = 0
                existing.quarantined_count = 0
                existing.filtered_count = 0
                existing.new_checkpoint = None
                existing.error_summary = None
                existing.parser_version = parser_version
                return PersistedIngestionRun(
                    run_id=str(existing.ingestion_run_id), state=IngestionRunState.REQUESTED
                )
            raise IngestionRunConflictError(
                f"equivalent ingestion run {existing.ingestion_run_id} is already {state.value}"
            )

    async def record_state(self, *, run: IngestionRun) -> None:
        """Persist a nonterminal lifecycle state using a short transaction."""

        if run.state in {
            IngestionRunState.PUBLISHED,
            IngestionRunState.QUARANTINED,
            IngestionRunState.FAILED,
        }:
            raise ValueError("terminal ingestion states must use finalize_run")
        async with self._session_factory() as session, session.begin():
            record = await self._load_run(session, run.run_id)
            record.status = run.state.value
            if run.state is IngestionRunState.FETCHING and record.started_at is None:
                record.started_at = _utc_now()

    async def record_raw_response(
        self,
        *,
        run: IngestionRun,
        policy: SourcePolicy,
        request: RawWriteRequest,
        raw_reference: RawReference,
    ) -> None:
        """Record content identity and an append-only retrieval after byte persistence."""

        if policy.retention_classification is None:
            raise SourcePolicyError(f"source '{policy.source_key}' has no retention classification")
        async with self._session_factory() as session, session.begin():
            source = await self._load_matching_source(session, policy)
            run_record = await self._load_run(session, run.run_id)
            if run_record.source_id != source.source_id:
                raise SourcePolicyError("ingestion run and source policy do not match")

            raw_object_id = await self._insert_or_load_raw_object(
                session=session,
                source_id=source.source_id,
                ingestion_run_id=run_record.ingestion_run_id,
                request=request,
                raw_reference=raw_reference,
                retention_classification=policy.retention_classification,
            )
            session.add(
                RawRetrieval(
                    raw_object_id=raw_object_id,
                    source_id=source.source_id,
                    ingestion_run_id=run_record.ingestion_run_id,
                    source_locator_redacted=redact_locator(request.source_locator),
                    requested_at=request.requested_at,
                    retrieved_at=request.retrieved_at,
                    source_modified_at=request.source_modified_at,
                    http_status=request.http_status,
                    http_metadata=sanitize_headers(request.http_headers or {}),
                    retrieval_code_version=request.retrieval_code_version,
                    terms_policy_version=request.terms_policy_version,
                    secrecy_classification=request.secrecy_classification,
                    original_filename=request.original_filename,
                    source_schema_version=request.source_schema_version,
                )
            )

    async def finalize_run(self, *, run: IngestionRun, error_summary: str | None = None) -> None:
        """Make terminal row accounting and checkpoint state durable together."""

        if run.state not in {
            IngestionRunState.PUBLISHED,
            IngestionRunState.QUARANTINED,
            IngestionRunState.FAILED,
        }:
            raise ValueError("only terminal ingestion runs may be finalized")
        async with self._session_factory() as session, session.begin():
            record = await self._load_run(session, run.run_id)
            accounting = run.accounting
            record.status = run.state.value
            record.completed_at = _utc_now()
            record.input_count = accounting.input_count if accounting is not None else 0
            record.accepted_count = accounting.accepted_count if accounting is not None else 0
            record.quarantined_count = accounting.quarantined_count if accounting is not None else 0
            record.filtered_count = accounting.filtered_count if accounting is not None else 0
            record.error_summary = error_summary
            if run.state is IngestionRunState.PUBLISHED:
                record.published_at = _utc_now()
                record.new_checkpoint = dict(run.new_checkpoint or {})
            else:
                record.published_at = None
                record.new_checkpoint = None

            report = run.report
            if report is not None:
                for issue in report.issues:
                    session.add(
                        DataQualityIssue(
                            ingestion_run_id=record.ingestion_run_id,
                            source_id=record.source_id,
                            rule_id=issue.rule_id,
                            severity=issue.severity.value,
                            blocking=issue.severity is IssueSeverity.BLOCKING,
                            safe_summary=issue.summary[:2_000],
                            evidence={"raw_sha256": issue.raw_sha256}
                            if issue.raw_sha256 is not None
                            else None,
                        )
                    )

    async def _load_matching_source(
        self, session: AsyncSession, policy: SourcePolicy
    ) -> DataSource:
        if policy.rate_limit is None:
            raise SourcePolicyError(f"source '{policy.source_key}' has no audited rate policy")
        source = await session.scalar(
            select(DataSource).where(DataSource.stable_key == policy.source_key).with_for_update()
        )
        if source is None:
            raise SourcePolicyError(
                f"source '{policy.source_key}' is absent from durable policy storage"
            )
        if (
            source.audit_state != policy.audit_state.value
            or source.enabled != policy.enabled
            or source.dataset_license != policy.dataset_license
            or source.policy_terms_version != policy.terms_policy_version
            or source.retention_classification != policy.retention_classification
            or source.audit_evidence_ref != policy.audit_evidence_ref
            or source.attribution != policy.attribution
        ):
            raise SourcePolicyError(
                f"source '{policy.source_key}' does not match durable audit policy"
            )
        rate_policy = source.rate_policy or {}
        if (
            rate_policy.get("requests_per_minute") != policy.rate_limit.requests_per_minute
            or rate_policy.get("max_concurrency") != policy.rate_limit.max_concurrency
        ):
            raise SourcePolicyError(
                f"source '{policy.source_key}' does not match durable rate policy"
            )
        return source

    async def _load_run(self, session: AsyncSession, run_id: str) -> IngestionRunRecord:
        try:
            parsed_run_id = UUID(run_id)
        except ValueError as exc:
            raise ValueError("durable ingestion run ID must be a UUID") from exc
        record = await session.scalar(
            select(IngestionRunRecord)
            .where(IngestionRunRecord.ingestion_run_id == parsed_run_id)
            .with_for_update()
        )
        if record is None:
            raise ValueError(f"durable ingestion run does not exist: {run_id}")
        return record

    async def _insert_or_load_raw_object(
        self,
        *,
        session: AsyncSession,
        source_id: UUID,
        ingestion_run_id: UUID,
        request: RawWriteRequest,
        raw_reference: RawReference,
        retention_classification: str,
    ) -> UUID:
        create = (
            insert(RawObject)
            .values(
                source_id=source_id,
                ingestion_run_id=ingestion_run_id,
                storage_namespace="raw",
                object_uri=raw_reference.object_uri,
                sha256=raw_reference.sha256,
                byte_length=len(request.content),
                content_type=request.content_type,
                retention_classification=retention_classification,
            )
            .on_conflict_do_nothing(index_elements=["source_id", "storage_namespace", "sha256"])
            .returning(RawObject.raw_object_id)
        )
        raw_object_id = (await session.execute(create)).scalar_one_or_none()
        if raw_object_id is not None:
            return raw_object_id
        existing = await session.scalar(
            select(RawObject.raw_object_id).where(
                RawObject.source_id == source_id,
                RawObject.storage_namespace == "raw",
                RawObject.sha256 == raw_reference.sha256,
            )
        )
        if existing is None:
            raise RuntimeError("content-addressed raw object could not be resolved")
        return existing


def _run_state(value: str) -> IngestionRunState:
    try:
        return IngestionRunState(value)
    except ValueError as exc:
        raise ValueError(f"unknown persisted ingestion run state: {value}") from exc


def _row_accounting(record: IngestionRunRecord) -> RowAccounting:
    return RowAccounting(
        input_count=record.input_count,
        accepted_count=record.accepted_count,
        quarantined_count=record.quarantined_count,
        filtered_count=record.filtered_count,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)
