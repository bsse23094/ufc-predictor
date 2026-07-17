"""Live PostgreSQL checks for the M3 relational canonical-bout boundary."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TypedDict
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ufc_api.data.models import DataQualityIssue, DataSource, IngestionRunRecord, RawObject
from ufc_api.fighters.models import (
    Fighter,
    IdentityResolutionApplication,
    IdentityResolutionDecision,
)
from ufc_api.fights.models import (
    Division,
    Event,
    EventSourceReference,
    Fight,
    FightParticipant,
    FightParticipantIdentityEvidence,
    FightResult,
    FightSourceReference,
)
from ufc_api.fights.repository import (
    CanonicalCatalogPublicationBlocked,
    CanonicalCatalogRepository,
)
from ufc_predictor.canonical.mappers import canonicalize_kaggle_ultimate_records
from ufc_predictor.canonical.models import ReviewedCanonicalAlias
from ufc_predictor.canonical.taxonomy import (
    CanonicalOutcomeType,
    DivisionTaxonomyEntry,
    MethodTaxonomyEntry,
    ObservedLabelTaxonomy,
    OutcomeTaxonomyEntry,
    SourceFighterField,
    TaxonomyScope,
)
from ufc_predictor.ingestion.base import ParsedRecord
from ufc_predictor.ingestion.kaggle_ultimate import ingest_local_kaggle_ultimate_dataset
from ufc_predictor.ingestion.policies import KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "kaggle_ultimate" / "ufc-master.csv"
DATABASE_URL = "postgresql+asyncpg://ufc_predictor:ufc_predictor@127.0.0.1:5432/ufc_predictor"
INGESTED_AT = datetime(2026, 7, 17, tzinfo=UTC)


class MappingApproval(TypedDict):
    mapping_version: str
    approved_by: str
    approved_at: datetime
    rationale: str


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


async def _database_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(DATABASE_URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _incoming_fixture(tmp_path: Path) -> Path:
    incoming = tmp_path / "incoming" / "ultimate-ufc-dataset"
    incoming.mkdir(parents=True)
    shutil.copy2(FIXTURE, incoming / "ufc-master.csv")
    return incoming


def _fighter_id(alias: str, test_token: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"catalog-fixture-fighter:{test_token}:{alias}")


def _decision_id(record_key: str, field_name: str, test_token: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"catalog-fixture-decision:{test_token}:{record_key}:{field_name}")


def _aliases(
    records: tuple[ParsedRecord, ...], test_token: str
) -> tuple[ReviewedCanonicalAlias, ...]:
    aliases: list[ReviewedCanonicalAlias] = []
    for record in records:
        fields = record.payload["source_fields"]
        schema = record.payload["source_schema_version"]
        assert isinstance(fields, dict)
        assert isinstance(schema, str)
        for field_name in ("R_fighter", "B_fighter"):
            value = fields[field_name]
            assert isinstance(value, str)
            aliases.append(
                ReviewedCanonicalAlias(
                    source_identifier=KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY,
                    source_schema_version=schema,
                    raw_sha256=record.raw_reference.sha256,
                    source_record_key=record.record_key,
                    source_field=field_name,
                    alias_value=value,
                    fighter_id=_fighter_id(value, test_token),
                    identity_resolution_decision_id=_decision_id(
                        record.record_key, field_name, test_token
                    ),
                )
            )
    return tuple(aliases)


def _taxonomy(records: tuple[ParsedRecord, ...]) -> ObservedLabelTaxonomy:
    schema = records[0].payload["source_schema_version"]
    assert isinstance(schema, str)
    scope = TaxonomyScope(KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY, schema)
    approval: MappingApproval = {
        "mapping_version": "catalog-fixture-taxonomy-v1",
        "approved_by": "data-steward@example.test",
        "approved_at": INGESTED_AT,
        "rationale": "Synthetic test labels were explicitly reviewed.",
    }
    return ObservedLabelTaxonomy(
        taxonomy_version="catalog-fixture-taxonomy-v1",
        outcomes=(
            OutcomeTaxonomyEntry(
                scope=scope,
                source_label="Red",
                outcome_type=CanonicalOutcomeType.DECISIVE,
                winner_source_field=SourceFighterField.RED,
                **approval,
            ),
            OutcomeTaxonomyEntry(
                scope=scope,
                source_label="Blue",
                outcome_type=CanonicalOutcomeType.DECISIVE,
                winner_source_field=SourceFighterField.BLUE,
                **approval,
            ),
        ),
        methods=(
            MethodTaxonomyEntry(
                scope=scope,
                source_label="KO/TKO",
                canonical_method_code="knockout_or_tko",
                **approval,
            ),
            MethodTaxonomyEntry(
                scope=scope,
                source_label="U-DEC",
                canonical_method_code="unanimous_decision",
                **approval,
            ),
        ),
        divisions=(
            DivisionTaxonomyEntry(
                scope=scope,
                source_label="Lightweight",
                canonical_division_code="lightweight",
                **approval,
            ),
            DivisionTaxonomyEntry(
                scope=scope,
                source_label="Welterweight",
                canonical_division_code="welterweight",
                **approval,
            ),
        ),
    )


@pytest.mark.anyio
async def test_canonical_mapping_publishes_idempotent_relational_facts_without_inventing_events(
    compose_database: None, tmp_path: Path
) -> None:
    assert compose_database is None
    ingestion = await ingest_local_kaggle_ultimate_dataset(
        incoming_directory=_incoming_fixture(tmp_path),
        raw_root=tmp_path / "raw",
        interim_root=tmp_path / "interim",
    )
    records = ingestion.execution.records
    test_token = uuid4().hex
    source_key = f"{KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY}-catalog-{test_token}"
    mapping = canonicalize_kaggle_ultimate_records(
        records,
        reviewed_aliases=_aliases(records, test_token),
        taxonomy=_taxonomy(records),
        ingested_at=INGESTED_AT,
    )
    mapping = replace(
        mapping,
        accepted=tuple(
            replace(observation, source_identifier=source_key) for observation in mapping.accepted
        ),
    )
    engine, factory = await _database_factory()
    try:
        async with factory() as session, session.begin():
            source = DataSource(
                stable_key=source_key,
                display_name="Catalog fixture source",
                source_type="fixture",
            )
            session.add(source)
            await session.flush()
            run = IngestionRunRecord(
                source_id=source.source_id,
                mode="fixture",
                idempotency_key=uuid5(NAMESPACE_URL, "catalog-fixture-run").hex,
                status="published",
            )
            session.add(run)
            await session.flush()
            raw = RawObject(
                source_id=source.source_id,
                ingestion_run_id=run.ingestion_run_id,
                object_uri=records[0].raw_reference.object_uri,
                sha256=records[0].raw_reference.sha256,
                byte_length=1,
                retention_classification="test-only",
            )
            session.add(raw)
            applications: list[IdentityResolutionApplication] = []
            for alias in _aliases(records, test_token):
                fighter = Fighter(fighter_id=alias.fighter_id, display_name=alias.alias_value)
                decision = IdentityResolutionDecision(
                    identity_resolution_decision_id=alias.identity_resolution_decision_id,
                    review_key=sha256(
                        f"review:{alias.identity_resolution_decision_id}".encode()
                    ).hexdigest(),
                    entity_type="fixture_fighter_alias",
                    decision_type="propose_link",
                    evidence={"fixture": True},
                    actor="data-steward@example.test",
                    decided_at=INGESTED_AT,
                    rationale="Fixture reviewed alias evidence.",
                )
                application = IdentityResolutionApplication(
                    decision_id=alias.identity_resolution_decision_id,
                    canonical_fighter_id=alias.fighter_id,
                    state="applied",
                    applied_by="identity-resolver@example.test",
                    applied_at=INGESTED_AT,
                )
                session.add_all((fighter, decision))
                applications.append(application)
            await session.flush()
            session.add_all(applications)
            await session.flush()
            source_id = source.source_id

        repository = CanonicalCatalogRepository(factory)
        published = await repository.publish_mapping(source_id=source_id, mapping=mapping)
        replay = await repository.publish_mapping(source_id=source_id, mapping=mapping)

        assert published.accepted_count == 2
        assert not published.replayed_record_keys
        assert replay.fight_ids == published.fight_ids
        assert replay.replayed_record_keys == tuple(record.record_key for record in records)
        conflicting_mapping = replace(
            mapping,
            accepted=(
                replace(mapping.accepted[0], taxonomy_version="conflicting-fixture-taxonomy-v1"),
                mapping.accepted[1],
            ),
        )
        with pytest.raises(CanonicalCatalogPublicationBlocked) as conflict:
            await repository.publish_mapping(source_id=source_id, mapping=conflicting_mapping)
        assert conflict.value.issues[0].rule_id == "CAN-006.conflicting_catalog_replay"
        with pytest.raises(CanonicalCatalogPublicationBlocked):
            await repository.publish_mapping(source_id=source_id, mapping=conflicting_mapping)
        async with factory() as session:
            replay_issue = await session.scalar(
                select(DataQualityIssue).where(
                    DataQualityIssue.source_id == source_id,
                    DataQualityIssue.rule_id == "CAN-006.conflicting_catalog_replay",
                )
            )
            assert replay_issue is not None
            assert replay_issue.blocking is True
            assert replay_issue.occurrence_count == 2
            assert replay_issue.canonical_issue_key is not None
            assert await session.scalar(select(func.count()).select_from(Event)) == 0
            assert await session.scalar(select(func.count()).select_from(EventSourceReference)) == 0
            division_count = await session.scalar(select(func.count()).select_from(Division))
            assert division_count is not None
            assert division_count >= 2
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(FightSourceReference)
                    .where(FightSourceReference.source_id == source_id)
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Fight)
                    .join(FightSourceReference)
                    .where(FightSourceReference.source_id == source_id)
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(FightParticipant)
                    .join(
                        FightSourceReference,
                        FightSourceReference.fight_id == FightParticipant.fight_id,
                    )
                    .where(FightSourceReference.source_id == source_id)
                )
                == 4
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(FightParticipantIdentityEvidence)
                    .join(
                        FightParticipant,
                        FightParticipant.fight_participant_id
                        == FightParticipantIdentityEvidence.fight_participant_id,
                    )
                    .join(
                        FightSourceReference,
                        FightSourceReference.fight_id == FightParticipant.fight_id,
                    )
                    .where(FightSourceReference.source_id == source_id)
                )
                == 4
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(FightResult)
                    .where(FightResult.source_id == source_id)
                )
                == 2
            )
            fights = list(
                (
                    await session.scalars(
                        select(Fight)
                        .join(FightSourceReference)
                        .where(FightSourceReference.source_id == source_id)
                        .order_by(Fight.fight_date)
                    )
                ).all()
            )
            assert all(fight.event_id is None for fight in fights)
            assert all(fight.event_context_status == "not_observed" for fight in fights)
            assert all(fight.publication_state == "published" for fight in fights)
            winner = await session.scalar(
                select(FightResult.winner_participant_id).where(
                    FightResult.fight_id == published.fight_ids[0]
                )
            )
            assert winner is not None

            participant = await session.scalar(
                select(FightParticipant).where(
                    FightParticipant.fight_id == published.fight_ids[0],
                    FightParticipant.fight_participant_id != winner,
                )
            )
            assert participant is not None
            evidence = await session.scalar(
                select(FightParticipantIdentityEvidence).where(
                    FightParticipantIdentityEvidence.fight_participant_id
                    == participant.fight_participant_id
                )
            )
            assert evidence is not None
            await session.delete(evidence)
            await session.flush()
            await session.delete(participant)
            with pytest.raises(DBAPIError, match="exactly two participants"):
                await session.commit()
            await session.rollback()

            wrong_participant = await session.scalar(
                select(FightParticipant).where(FightParticipant.fight_id == published.fight_ids[1])
            )
            wrong_decision = _decision_id(records[0].record_key, "R_fighter", test_token)
            assert wrong_participant is not None
            session.add(
                FightParticipantIdentityEvidence(
                    fight_participant_id=wrong_participant.fight_participant_id,
                    identity_resolution_decision_id=wrong_decision,
                )
            )
            with pytest.raises(DBAPIError, match="applied matching decision"):
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_mapping_quarantine_is_durable_and_idempotent_before_catalog_writes(
    compose_database: None, tmp_path: Path
) -> None:
    assert compose_database is None
    ingestion = await ingest_local_kaggle_ultimate_dataset(
        incoming_directory=_incoming_fixture(tmp_path),
        raw_root=tmp_path / "raw",
        interim_root=tmp_path / "interim",
    )
    records = ingestion.execution.records
    test_token = uuid4().hex
    source_key = f"{KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY}-quarantine-{test_token}"
    mapping = canonicalize_kaggle_ultimate_records(
        records,
        reviewed_aliases=_aliases(records, test_token)[1:],
        taxonomy=_taxonomy(records),
        ingested_at=INGESTED_AT,
    )
    mapping = replace(
        mapping,
        accepted=tuple(
            replace(observation, source_identifier=source_key) for observation in mapping.accepted
        ),
    )
    assert mapping.quarantined_record_keys
    engine, factory = await _database_factory()
    try:
        async with factory() as session, session.begin():
            source = DataSource(
                stable_key=source_key,
                display_name="Catalog quarantine fixture source",
                source_type="fixture",
            )
            session.add(source)
            await session.flush()
            source_id = source.source_id

        repository = CanonicalCatalogRepository(factory)
        with pytest.raises(CanonicalCatalogPublicationBlocked) as blocked:
            await repository.publish_mapping(source_id=source_id, mapping=mapping)
        assert {issue.rule_id for issue in blocked.value.issues} == {
            "CAN-002.unresolved_fighter_alias"
        }
        with pytest.raises(CanonicalCatalogPublicationBlocked):
            await repository.publish_mapping(source_id=source_id, mapping=mapping)
        async with factory() as session:
            issue = await session.scalar(
                select(DataQualityIssue).where(
                    DataQualityIssue.source_id == source_id,
                    DataQualityIssue.rule_id == "CAN-002.unresolved_fighter_alias",
                )
            )
            assert issue is not None
            assert issue.occurrence_count == 2
            assert issue.evidence == {
                "raw_sha256": records[0].raw_reference.sha256,
                "source_record_key": records[0].record_key,
            }
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(FightSourceReference)
                    .where(FightSourceReference.source_id == source_id)
                )
                == 0
            )
    finally:
        await engine.dispose()
