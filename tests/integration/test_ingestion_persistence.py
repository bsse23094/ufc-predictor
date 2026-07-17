"""PostgreSQL integration checks for the source-neutral M2 persistence boundary."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Generator, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ufc_api.data.models import (
    DataQualityIssue,
    DataSource,
    IngestionRunRecord,
    RawObject,
    RawRetrieval,
)
from ufc_api.data.repository import DataGovernanceRepository
from ufc_api.fighters.models import (
    Fighter,
    FighterAlias,
    FighterAliasSupersession,
    FighterIdentityMerge,
    FighterIdentitySplit,
    IdentityResolutionApplication,
    IdentityResolutionDecision,
)
from ufc_api.fighters.repository import (
    FighterIdentityRepository,
    ResolutionApplicationState,
    ReviewedAliasInput,
)
from ufc_predictor.identity.candidates import FighterAliasCandidatePair, generate_candidate_pairs
from ufc_predictor.identity.normalize import FighterAliasCandidate, candidate_fighter_aliases
from ufc_predictor.identity.resolver import ReviewedFighterMerge, ReviewedFighterSplit
from ufc_predictor.identity.review import (
    IdentityReviewDecision,
    IdentityReviewDecisionType,
    create_review_queue,
)
from ufc_predictor.identity.scorer import score_candidate_pair
from ufc_predictor.ingestion.base import (
    FetchResponse,
    ParsedRecord,
    RawReference,
    SchemaFingerprint,
    WorkUnit,
)
from ufc_predictor.ingestion.rate_limit import RateLimitPolicy
from ufc_predictor.ingestion.raw_store import LocalRawStore
from ufc_predictor.ingestion.registry import SourceAuditState, SourcePolicy, SourceRegistry
from ufc_predictor.ingestion.runner import FetchRetryPolicy, IngestionExecutor, IngestionRunState
from ufc_predictor.ingestion.validation import (
    RecordDisposition,
    SchemaGate,
    TransportPolicy,
    ValidatedRecord,
)

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = "postgresql+asyncpg://ufc_predictor:ufc_predictor@127.0.0.1:5432/ufc_predictor"


@pytest.fixture(scope="module")
def compose_database() -> Generator[None, None, None]:
    if os.environ.get("RUN_CONTAINER_TESTS") != "1":
        docker_info = subprocess.run(["docker", "info"], cwd=ROOT, capture_output=True, timeout=10)
        if docker_info.returncode != 0:
            pytest.skip(
                "Docker is unavailable; start Docker Desktop to run container integration tests"
            )
    try:
        subprocess.run(
            ["docker", "compose", "up", "-d", "--wait", "postgres", "redis"],
            cwd=ROOT,
            check=True,
            timeout=90,
        )
        subprocess.run(
            [
                "uv",
                "run",
                "--project",
                "apps/api",
                "alembic",
                "-c",
                "apps/api/alembic.ini",
                "upgrade",
                "head",
            ],
            cwd=ROOT,
            check=True,
            timeout=60,
        )
        yield
    finally:
        subprocess.run(
            ["docker", "compose", "--profile", "app", "down"],
            cwd=ROOT,
            check=False,
            timeout=60,
        )


class DurableSyntheticAdapter:
    """A source-neutral test adapter that never contacts a network service."""

    parser_version = "persistence-parser-v1"

    def __init__(
        self,
        *,
        source_key: str,
        fingerprint: SchemaFingerprint,
        statuses: list[int],
        payload_key: str | None = None,
    ) -> None:
        self.source_key = source_key
        self._fingerprint = fingerprint
        self._statuses = statuses
        self._payload_key = payload_key or source_key
        self.fetch_calls = 0
        self.parse_calls = 0

    def discover(self, checkpoint: Mapping[str, object] | None) -> Iterable[WorkUnit]:
        assert checkpoint == {"page": 1}
        return (
            WorkUnit(
                source_key=self.source_key,
                unit_key="unit-1",
                locator="https://example.invalid/fixture?secret=redacted",
                discovered_at=datetime(2026, 7, 17, tzinfo=UTC),
                attributes={},
            ),
        )

    async def fetch(self, work_unit: WorkUnit) -> FetchResponse:
        self.fetch_calls += 1
        status = self._statuses.pop(0)
        return FetchResponse(
            work_unit=work_unit,
            requested_at=datetime(2026, 7, 17, 10, 0, tzinfo=UTC),
            retrieved_at=datetime(2026, 7, 17, 10, 1, tzinfo=UTC),
            status_code=status,
            headers={"retry-after": "0", "authorization": "never-store"},
            content=f"{self._payload_key}-synthetic-response-{status}".encode(),
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


def _policy(source_key: str) -> SourcePolicy:
    return SourcePolicy(
        source_key=source_key,
        audit_state=SourceAuditState.APPROVED,
        enabled=True,
        terms_policy_version="synthetic-terms-v1",
        retention_classification="test-only",
        approved_at=datetime(2026, 7, 17, tzinfo=UTC),
        audit_evidence_ref="tests/fixtures/synthetic-source-audit.md",
        rate_limit=RateLimitPolicy(requests_per_minute=60, max_concurrency=1),
    )


async def _insert_source(factory: async_sessionmaker[AsyncSession], policy: SourcePolicy) -> UUID:
    async with factory() as session, session.begin():
        source = DataSource(
            stable_key=policy.source_key,
            display_name="Synthetic persistence source",
            source_type="test",
            audit_state=policy.audit_state.value,
            dataset_license=policy.dataset_license,
            policy_terms_version=policy.terms_policy_version,
            retention_classification=policy.retention_classification,
            audit_evidence_ref=policy.audit_evidence_ref,
            approved_at=policy.approved_at,
            enabled=policy.enabled,
            rate_policy={
                "requests_per_minute": policy.rate_limit.requests_per_minute
                if policy.rate_limit is not None
                else 0,
                "max_concurrency": policy.rate_limit.max_concurrency
                if policy.rate_limit is not None
                else 0,
            },
        )
        session.add(source)
        await session.flush()
        return source.source_id


def _executor(
    *,
    policy: SourcePolicy,
    raw_root: Path,
    repository: DataGovernanceRepository,
    schema_gate: SchemaGate,
) -> IngestionExecutor:
    async def no_delay(_: float) -> None:
        return None

    return IngestionExecutor(
        registry=SourceRegistry([policy]),
        raw_store=LocalRawStore(raw_root),
        schema_gate=schema_gate,
        transport_policy=TransportPolicy(max_response_bytes=1_024),
        retry_policy=FetchRetryPolicy(max_attempts=2, base_delay_seconds=0, max_delay_seconds=0),
        persistence=repository,
        clock=lambda: 0.0,
        sleeper=no_delay,
    )


async def _database_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.anyio
async def test_durable_ingestion_persists_retry_bytes_accounting_and_checkpoint(
    compose_database: None, tmp_path: Path
) -> None:
    assert compose_database is None
    engine, factory = await _database_factory()
    try:
        policy = _policy(f"synthetic-persistence-{uuid4().hex}")
        source_id = await _insert_source(factory, policy)
        fingerprint = SchemaFingerprint.from_markers(
            ["fixture-v1"], parser_version="persistence-parser-v1"
        )
        repository = DataGovernanceRepository(factory)
        executor = _executor(
            policy=policy,
            raw_root=tmp_path / "raw",
            repository=repository,
            schema_gate=SchemaGate(frozenset({fingerprint.value})),
        )

        result = await executor.execute(
            adapter=DurableSyntheticAdapter(
                source_key=policy.source_key,
                fingerprint=fingerprint,
                statuses=[429, 200],
                payload_key="shared-content",
            ),
            mode="incremental",
            previous_checkpoint={"page": 1},
            candidate_checkpoint={"page": 2},
        )

        assert result.run.state is IngestionRunState.PUBLISHED
        assert result.replayed is False
        assert result.run.new_checkpoint == {"page": 2}
        assert len(result.raw_references) == 2

        replay_adapter = DurableSyntheticAdapter(
            source_key=policy.source_key,
            fingerprint=fingerprint,
            statuses=[],
            payload_key="shared-content",
        )
        replay = await executor.execute(
            adapter=replay_adapter,
            mode="incremental",
            previous_checkpoint={"page": 1},
            candidate_checkpoint={"page": 2},
        )

        assert replay.replayed is True
        assert replay_adapter.fetch_calls == 0
        assert replay.run.run_id == result.run.run_id

        async with factory() as session:
            run = await session.scalar(
                select(IngestionRunRecord).where(
                    IngestionRunRecord.ingestion_run_id == UUID(result.run.run_id)
                )
            )
            assert run is not None
            assert run.source_id == source_id
            assert run.status == IngestionRunState.PUBLISHED.value
            assert (
                run.input_count,
                run.accepted_count,
                run.quarantined_count,
                run.filtered_count,
            ) == (
                1,
                1,
                0,
                0,
            )
            assert run.new_checkpoint == {"page": 2}
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(RawObject)
                    .where(RawObject.source_id == source_id)
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(RawRetrieval)
                    .where(RawRetrieval.source_id == source_id)
                )
                == 2
            )
            retrieval = await session.scalar(
                select(RawRetrieval).where(RawRetrieval.source_id == source_id)
            )
            assert retrieval is not None
            assert retrieval.source_locator_redacted == "https://example.invalid/fixture"
            assert retrieval.http_metadata == {"retry-after": "0"}
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_reviewed_fighter_merges_and_splits_preserve_alias_history_and_audit(
    compose_database: None,
) -> None:
    """A canonical transition needs reviewed aliases, remains replay-safe, and never moves them."""

    assert compose_database is None
    engine, factory = await _database_factory()
    try:
        policy = _policy(f"identity-merge-source-{uuid4().hex}")
        source_id = await _insert_source(factory, policy)
        async with factory() as session, session.begin():
            run = IngestionRunRecord(
                source_id=source_id,
                mode="fixture",
                idempotency_key=uuid4().hex,
                status=IngestionRunState.PUBLISHED.value,
            )
            session.add(run)
            await session.flush()
            raw_by_sha = {
                sha: RawObject(
                    source_id=source_id,
                    ingestion_run_id=run.ingestion_run_id,
                    object_uri=f"objects/{sha * 64}",
                    sha256=sha * 64,
                    byte_length=1,
                    retention_classification="test-only",
                )
                for sha in ("a", "b", "c", "d")
            }
            canonical = Fighter(display_name="Jose Aldo")
            duplicate = Fighter(display_name="J. Aldo")
            session.add_all((*raw_by_sha.values(), canonical, duplicate))
            await session.flush()
            raw_object_ids = {
                sha * 64: raw_object.raw_object_id for sha, raw_object in raw_by_sha.items()
            }
            canonical_id = canonical.fighter_id
            duplicate_id = duplicate.fighter_id

        candidates = candidate_fighter_aliases(
            source_identifier=policy.source_key,
            rows=tuple(
                {
                    "source_record_key": f"fight-00{index}",
                    "source_raw_sha256": sha * 64,
                    "fighter_one_source_name": "Jose Aldo",
                    "fighter_two_source_name": f"Opponent {index}",
                }
                for index, sha in enumerate(("a", "b", "c", "d"), start=1)
            ),
        )
        pairs = generate_candidate_pairs(candidates)

        def pair_for(first_sha: str, second_sha: str) -> FighterAliasCandidatePair:
            return next(
                pair
                for pair in pairs
                if {pair.first.source_raw_sha256, pair.second.source_raw_sha256}
                == {first_sha * 64, second_sha * 64}
            )

        def alias_inputs(
            pair: FighterAliasCandidatePair,
        ) -> tuple[ReviewedAliasInput, ReviewedAliasInput]:
            def input_for(candidate: FighterAliasCandidate) -> ReviewedAliasInput:
                return ReviewedAliasInput(
                    source_id=source_id,
                    raw_object_id=raw_object_ids[candidate.source_raw_sha256],
                    source_record_key=candidate.source_record_key,
                    source_field=candidate.source_field,
                    alias_value=candidate.alias.original_value,
                    normalized_value=candidate.alias.normalized_value,
                    observed_at=datetime(2026, 7, 17, tzinfo=UTC),
                )

            return (
                input_for(pair.first),
                input_for(pair.second),
            )

        repository = FighterIdentityRepository(factory)

        async def record_and_link(first_sha: str, second_sha: str, fighter_id: UUID) -> None:
            pair = pair_for(first_sha, second_sha)
            queue = create_review_queue((score_candidate_pair(pair),))
            decision = IdentityReviewDecision(
                review_key=queue[0].review_key,
                decision=IdentityReviewDecisionType.PROPOSE_LINK,
                decided_by="data-steward@example.test",
                decided_at=datetime(2026, 7, 17, tzinfo=UTC),
                rationale="Reviewed source aliases belong to this canonical fighter.",
            )
            decision_id = await repository.record_review_decision(item=queue[0], decision=decision)
            applied = await repository.apply_proposed_link(
                decision_id=decision_id,
                canonical_fighter_id=fighter_id,
                aliases=alias_inputs(pair),
                applied_by="identity-resolver@example.test",
            )
            assert applied.state is ResolutionApplicationState.APPLIED

        await record_and_link("a", "b", canonical_id)
        await record_and_link("c", "d", duplicate_id)

        merge_pair = pair_for("a", "c")
        merge_queue = create_review_queue((score_candidate_pair(merge_pair),))
        merge_decision_id = await repository.record_review_decision(
            item=merge_queue[0],
            decision=IdentityReviewDecision(
                review_key=merge_queue[0].review_key,
                decision=IdentityReviewDecisionType.PROPOSE_MERGE,
                decided_by="data-steward@example.test",
                decided_at=datetime(2026, 7, 17, 1, tzinfo=UTC),
                rationale="The two reviewed identities describe the same fighter.",
            ),
        )
        merge = await repository.merge_reviewed_fighters(
            request=ReviewedFighterMerge(
                decision_id=merge_decision_id,
                canonical_fighter_id=canonical_id,
                merged_fighter_id=duplicate_id,
            ),
            applied_by="identity-resolver@example.test",
        )
        merge_replay = await repository.merge_reviewed_fighters(
            request=ReviewedFighterMerge(
                decision_id=merge_decision_id,
                canonical_fighter_id=canonical_id,
                merged_fighter_id=duplicate_id,
            ),
            applied_by="identity-resolver@example.test",
        )

        assert merge.state is ResolutionApplicationState.APPLIED
        assert merge.fighter_identity_merge_id is not None
        assert merge_replay.fighter_identity_merge_id == merge.fighter_identity_merge_id
        async with factory() as session:
            merged = await session.scalar(select(Fighter).where(Fighter.fighter_id == duplicate_id))
            assert merged is not None
            assert merged.merged_into_fighter_id == canonical_id
            assert merged.identity_status == "merged"
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(FighterAlias)
                    .where(
                        FighterAlias.fighter_id == duplicate_id, FighterAlias.system_to.is_(None)
                    )
                )
                == 2
            )
            merge_record = await session.scalar(
                select(FighterIdentityMerge).where(
                    FighterIdentityMerge.fighter_identity_merge_id
                    == merge.fighter_identity_merge_id
                )
            )
            assert merge_record is not None
            merge_record.applied_by = "mutation-must-fail@example.test"
            with pytest.raises(DBAPIError, match="append-only"):
                await session.commit()
            await session.rollback()
        async with factory() as session:
            merged = await session.scalar(select(Fighter).where(Fighter.fighter_id == duplicate_id))
            assert merged is not None
            merged.merged_into_fighter_id = None
            merged.identity_status = "resolved_by_review"
            with pytest.raises(DBAPIError, match="split transition"):
                await session.commit()
            await session.rollback()

        split_pair = pair_for("b", "d")
        split_queue = create_review_queue((score_candidate_pair(split_pair),))
        split_decision_id = await repository.record_review_decision(
            item=split_queue[0],
            decision=IdentityReviewDecision(
                review_key=split_queue[0].review_key,
                decision=IdentityReviewDecisionType.PROPOSE_SPLIT,
                decided_by="data-steward@example.test",
                decided_at=datetime(2026, 7, 17, 2, tzinfo=UTC),
                rationale="New review establishes that the merged identities are distinct.",
            ),
            supersedes_decision_id=merge_decision_id,
        )
        split = await repository.split_reviewed_fighters(
            request=ReviewedFighterSplit(
                decision_id=split_decision_id,
                canonical_fighter_id=canonical_id,
                restored_fighter_id=duplicate_id,
            ),
            applied_by="identity-resolver@example.test",
        )
        split_replay = await repository.split_reviewed_fighters(
            request=ReviewedFighterSplit(
                decision_id=split_decision_id,
                canonical_fighter_id=canonical_id,
                restored_fighter_id=duplicate_id,
            ),
            applied_by="identity-resolver@example.test",
        )

        assert split.state is ResolutionApplicationState.APPLIED
        assert split.fighter_identity_split_id is not None
        assert split_replay.fighter_identity_split_id == split.fighter_identity_split_id
        async with factory() as session:
            restored = await session.scalar(
                select(Fighter).where(Fighter.fighter_id == duplicate_id)
            )
            assert restored is not None
            assert restored.merged_into_fighter_id is None
            assert restored.identity_status == "resolved_by_review"
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(FighterAlias)
                    .where(
                        FighterAlias.fighter_id == duplicate_id, FighterAlias.system_to.is_(None)
                    )
                )
                == 2
            )
            split_record = await session.scalar(
                select(FighterIdentitySplit).where(
                    FighterIdentitySplit.fighter_identity_split_id
                    == split.fighter_identity_split_id
                )
            )
            assert split_record is not None
            split_record.applied_by = "mutation-must-fail@example.test"
            with pytest.raises(DBAPIError, match="append-only"):
                await session.commit()
            await session.rollback()
        async with factory() as session:
            alias = await session.scalar(
                select(FighterAlias).where(
                    FighterAlias.fighter_id == duplicate_id,
                    FighterAlias.system_to.is_(None),
                )
            )
            assert alias is not None
            alias.fighter_id = canonical_id
            with pytest.raises(DBAPIError, match="fighter aliases"):
                await session.commit()
            await session.rollback()
        async with factory() as session:
            restored = await session.scalar(
                select(Fighter).where(Fighter.fighter_id == duplicate_id)
            )
            assert restored is not None
            restored.merged_into_fighter_id = canonical_id
            restored.identity_status = "merged"
            with pytest.raises(DBAPIError, match="merge transition"):
                await session.commit()
            await session.rollback()

        invalid_merge_pair = pair_for("a", "b")
        invalid_queue = create_review_queue((score_candidate_pair(invalid_merge_pair),))
        invalid_decision_id = await repository.record_review_decision(
            item=invalid_queue[0],
            decision=IdentityReviewDecision(
                review_key=invalid_queue[0].review_key,
                decision=IdentityReviewDecisionType.PROPOSE_MERGE,
                decided_by="data-steward@example.test",
                decided_at=datetime(2026, 7, 17, 3, tzinfo=UTC),
                rationale="This intentionally invalid request tests the review evidence gate.",
            ),
        )
        invalid = await repository.merge_reviewed_fighters(
            request=ReviewedFighterMerge(
                decision_id=invalid_decision_id,
                canonical_fighter_id=canonical_id,
                merged_fighter_id=duplicate_id,
            ),
            applied_by="identity-resolver@example.test",
        )
        assert invalid.state is ResolutionApplicationState.QUARANTINED
        assert invalid.fighter_identity_merge_id is None
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_quarantined_run_can_retry_without_advancing_a_checkpoint(
    compose_database: None, tmp_path: Path
) -> None:
    assert compose_database is None
    engine, factory = await _database_factory()
    try:
        policy = _policy(f"synthetic-quarantine-{uuid4().hex}")
        source_id = await _insert_source(factory, policy)
        fingerprint = SchemaFingerprint.from_markers(
            ["fixture-v1"], parser_version="persistence-parser-v1"
        )
        repository = DataGovernanceRepository(factory)
        blocked_executor = _executor(
            policy=policy,
            raw_root=tmp_path / "raw",
            repository=repository,
            schema_gate=SchemaGate(),
        )

        quarantined = await blocked_executor.execute(
            adapter=DurableSyntheticAdapter(
                source_key=policy.source_key,
                fingerprint=fingerprint,
                statuses=[200],
                payload_key="shared-content",
            ),
            mode="incremental",
            previous_checkpoint={"page": 1},
            candidate_checkpoint={"page": 2},
        )

        assert quarantined.run.state is IngestionRunState.QUARANTINED
        assert quarantined.run.new_checkpoint is None
        retry_executor = _executor(
            policy=policy,
            raw_root=tmp_path / "raw",
            repository=repository,
            schema_gate=SchemaGate(frozenset({fingerprint.value})),
        )
        published = await retry_executor.execute(
            adapter=DurableSyntheticAdapter(
                source_key=policy.source_key,
                fingerprint=fingerprint,
                statuses=[200],
                payload_key="shared-content",
            ),
            mode="incremental",
            previous_checkpoint={"page": 1},
            candidate_checkpoint={"page": 2},
        )

        assert published.run.state is IngestionRunState.PUBLISHED
        assert published.run.run_id == quarantined.run.run_id
        async with factory() as session:
            run = await session.scalar(
                select(IngestionRunRecord).where(
                    IngestionRunRecord.ingestion_run_id == UUID(published.run.run_id)
                )
            )
            assert run is not None
            assert run.attempt == 1
            assert run.new_checkpoint == {"page": 2}
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(RawObject)
                    .where(RawObject.source_id == source_id)
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(RawRetrieval)
                    .where(RawRetrieval.source_id == source_id)
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DataQualityIssue)
                    .where(DataQualityIssue.source_id == source_id)
                )
                == 1
            )
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_human_identity_review_evidence_is_durable_and_append_only(
    compose_database: None,
) -> None:
    assert compose_database is None
    engine, factory = await _database_factory()
    try:
        candidates = candidate_fighter_aliases(
            source_identifier="fixture-source",
            rows=(
                {
                    "source_record_key": "fight-001",
                    "source_raw_sha256": "a" * 64,
                    "fighter_one_source_name": "José Aldo",
                    "fighter_two_source_name": "Alpha Fighter",
                },
                {
                    "source_record_key": "fight-002",
                    "source_raw_sha256": "b" * 64,
                    "fighter_one_source_name": "Jose Aldo",
                    "fighter_two_source_name": "Beta Fighter",
                },
            ),
        )
        queue = create_review_queue(
            (score_candidate_pair(generate_candidate_pairs(candidates)[0]),)
        )
        decision = IdentityReviewDecision(
            review_key=queue[0].review_key,
            decision=IdentityReviewDecisionType.PROPOSE_LINK,
            decided_by="data-steward@example.test",
            decided_at=datetime(2026, 7, 17, tzinfo=UTC),
            rationale="A resolver must evaluate the source-backed candidate pair.",
        )

        repository = FighterIdentityRepository(factory)
        decision_id = await repository.record_review_decision(item=queue[0], decision=decision)

        async with factory() as session:
            persisted = await session.scalar(
                select(IdentityResolutionDecision).where(
                    IdentityResolutionDecision.identity_resolution_decision_id == decision_id
                )
            )
            assert persisted is not None
            assert persisted.review_key == decision.review_key
            assert persisted.proposed_fighter_id is None
            assert persisted.resolved_fighter_id is None
            first_evidence = persisted.evidence["first"]
            second_evidence = persisted.evidence["second"]
            assert isinstance(first_evidence, Mapping)
            assert isinstance(second_evidence, Mapping)
            assert first_evidence["source_raw_sha256"] == "a" * 64
            assert second_evidence["source_raw_sha256"] == "b" * 64
            persisted.rationale = "This mutation must be rejected."
            with pytest.raises(DBAPIError, match="append-only"):
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_reviewed_resolution_applies_exact_evidence_once_and_quarantines_mismatch(
    compose_database: None,
) -> None:
    assert compose_database is None
    engine, factory = await _database_factory()
    try:
        policy = _policy(f"identity-review-source-{uuid4().hex}")
        source_id = await _insert_source(factory, policy)
        async with factory() as session, session.begin():
            run = IngestionRunRecord(
                source_id=source_id,
                mode="fixture",
                idempotency_key=uuid4().hex,
                status=IngestionRunState.PUBLISHED.value,
            )
            session.add(run)
            await session.flush()
            raw_first = RawObject(
                source_id=source_id,
                ingestion_run_id=run.ingestion_run_id,
                object_uri="objects/" + "a" * 64,
                sha256="a" * 64,
                byte_length=1,
                retention_classification="test-only",
            )
            raw_second = RawObject(
                source_id=source_id,
                ingestion_run_id=run.ingestion_run_id,
                object_uri="objects/" + "b" * 64,
                sha256="b" * 64,
                byte_length=1,
                retention_classification="test-only",
            )
            fighter = Fighter(display_name="Jose Aldo")
            corrected_fighter = Fighter(display_name="Jose Also")
            session.add_all((raw_first, raw_second, fighter, corrected_fighter))
            await session.flush()
            raw_first_id = raw_first.raw_object_id
            raw_second_id = raw_second.raw_object_id
            fighter_id = fighter.fighter_id
            corrected_fighter_id = corrected_fighter.fighter_id

        candidates = candidate_fighter_aliases(
            source_identifier=policy.source_key,
            rows=(
                {
                    "source_record_key": "fight-001",
                    "source_raw_sha256": "a" * 64,
                    "fighter_one_source_name": "José Aldo",
                    "fighter_two_source_name": "Alpha Fighter",
                },
                {
                    "source_record_key": "fight-002",
                    "source_raw_sha256": "b" * 64,
                    "fighter_one_source_name": "Jose Aldo",
                    "fighter_two_source_name": "Beta Fighter",
                },
            ),
        )
        pair = generate_candidate_pairs(candidates)[0]
        queue = create_review_queue((score_candidate_pair(pair),))
        decision = IdentityReviewDecision(
            review_key=queue[0].review_key,
            decision=IdentityReviewDecisionType.PROPOSE_LINK,
            decided_by="data-steward@example.test",
            decided_at=datetime(2026, 7, 17, tzinfo=UTC),
            rationale="The canonical fighter was selected after manual review.",
        )
        repository = FighterIdentityRepository(factory)
        decision_id = await repository.record_review_decision(item=queue[0], decision=decision)
        aliases = (
            ReviewedAliasInput(
                source_id=source_id,
                raw_object_id=raw_first_id,
                source_record_key=pair.first.source_record_key,
                source_field=pair.first.source_field,
                alias_value=pair.first.alias.original_value,
                normalized_value=pair.first.alias.normalized_value,
                observed_at=datetime(2026, 7, 17, tzinfo=UTC),
            ),
            ReviewedAliasInput(
                source_id=source_id,
                raw_object_id=raw_second_id,
                source_record_key=pair.second.source_record_key,
                source_field=pair.second.source_field,
                alias_value=pair.second.alias.original_value,
                normalized_value=pair.second.alias.normalized_value,
                observed_at=datetime(2026, 7, 17, tzinfo=UTC),
            ),
        )

        applied = await repository.apply_proposed_link(
            decision_id=decision_id,
            canonical_fighter_id=fighter_id,
            aliases=aliases,
            applied_by="identity-resolver@example.test",
        )
        replay = await repository.apply_proposed_link(
            decision_id=decision_id,
            canonical_fighter_id=fighter_id,
            aliases=aliases,
            applied_by="identity-resolver@example.test",
        )

        assert applied.state is ResolutionApplicationState.APPLIED
        assert len(applied.fighter_alias_ids) == 2
        assert replay.application_id == applied.application_id
        assert replay.state is ResolutionApplicationState.APPLIED
        async with factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(FighterAlias)
                    .where(FighterAlias.fighter_id == fighter_id)
                )
                == 2
            )

        correction_decision_id = await repository.record_review_decision(
            item=queue[0],
            decision=IdentityReviewDecision(
                review_key=queue[0].review_key,
                decision=IdentityReviewDecisionType.PROPOSE_LINK,
                decided_by="data-steward@example.test",
                decided_at=datetime(2026, 7, 17, 1, tzinfo=UTC),
                rationale="The prior alias link was assigned to the wrong canonical fighter.",
            ),
            supersedes_decision_id=decision_id,
        )
        corrected = await repository.supersede_reviewed_aliases(
            decision_id=correction_decision_id,
            canonical_fighter_id=corrected_fighter_id,
            aliases=aliases,
            superseded_alias_ids=applied.fighter_alias_ids,
            applied_by="identity-resolver@example.test",
        )
        correction_replay = await repository.supersede_reviewed_aliases(
            decision_id=correction_decision_id,
            canonical_fighter_id=corrected_fighter_id,
            aliases=aliases,
            superseded_alias_ids=applied.fighter_alias_ids,
            applied_by="identity-resolver@example.test",
        )

        assert corrected.state is ResolutionApplicationState.APPLIED
        assert len(corrected.fighter_alias_ids) == 2
        assert correction_replay.application_id == corrected.application_id
        async with factory() as session:
            old_aliases = list(
                (
                    await session.scalars(
                        select(FighterAlias).where(
                            FighterAlias.fighter_alias_id.in_(applied.fighter_alias_ids)
                        )
                    )
                ).all()
            )
            assert len(old_aliases) == 2
            assert all(alias.system_to is not None for alias in old_aliases)
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(FighterAlias)
                    .where(
                        FighterAlias.fighter_id == corrected_fighter_id,
                        FighterAlias.system_to.is_(None),
                    )
                )
                == 2
            )
            supersession = await session.scalar(
                select(FighterAliasSupersession).where(
                    FighterAliasSupersession.identity_resolution_application_id
                    == corrected.application_id
                )
            )
            assert supersession is not None
            supersession.applied_by = "mutation-must-fail@example.test"
            with pytest.raises(DBAPIError, match="append-only"):
                await session.commit()
            await session.rollback()

        quarantine_decision_id = await repository.record_review_decision(
            item=queue[0], decision=decision
        )
        quarantined = await repository.apply_proposed_link(
            decision_id=quarantine_decision_id,
            canonical_fighter_id=fighter_id,
            aliases=(aliases[0],),
            applied_by="identity-resolver@example.test",
        )

        assert quarantined.state is ResolutionApplicationState.QUARANTINED
        assert quarantined.quarantine_reason is not None
        async with factory() as session:
            persisted = await session.scalar(
                select(IdentityResolutionApplication).where(
                    IdentityResolutionApplication.identity_resolution_application_id
                    == quarantined.application_id
                )
            )
            assert persisted is not None
            assert persisted.state == ResolutionApplicationState.QUARANTINED.value
            assert persisted.canonical_fighter_id is None
            persisted.state = ResolutionApplicationState.APPLIED.value
            with pytest.raises(DBAPIError, match="append-only"):
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()
