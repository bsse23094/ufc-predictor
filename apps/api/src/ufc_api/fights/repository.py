"""Transactional publication of fully mapped canonical bout facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ufc_api.data.models import DataQualityIssue, DataSource, RawObject
from ufc_api.fighters.models import Fighter, IdentityResolutionApplication
from ufc_api.fights.models import (
    Division,
    Fight,
    FightParticipant,
    FightParticipantIdentityEvidence,
    FightResult,
    FightSourceReference,
)
from ufc_predictor.canonical.models import CanonicalFightObservation, CanonicalMappingResult
from ufc_predictor.canonical.validation import CanonicalMappingBlocked, require_publishable_mapping


@dataclass(frozen=True, slots=True)
class CanonicalCatalogLoadResult:
    """Stable ids and replay status for a complete canonical mapping publication."""

    fight_ids: tuple[UUID, ...]
    replayed_record_keys: tuple[str, ...]

    @property
    def accepted_count(self) -> int:
        return len(self.fight_ids)


@dataclass(frozen=True, slots=True)
class CanonicalCatalogIssue:
    """A source-record-specific canonical publication block safe to store durably."""

    rule_id: str
    source_record_key: str
    raw_sha256: str
    summary: str


class CanonicalCatalogPublicationBlocked(RuntimeError):
    """Raised after canonical blocks have been durably recorded for review."""

    def __init__(self, issues: tuple[CanonicalCatalogIssue, ...]) -> None:
        self.issues = issues
        super().__init__("canonical catalog publication blocked; review durable quality issues")


class _CanonicalCatalogLoadFailure(RuntimeError):
    """Internal rollback signal carrying one safe, durable issue."""

    def __init__(self, issue: CanonicalCatalogIssue) -> None:
        self.issue = issue
        super().__init__(issue.summary)


class CanonicalCatalogRepository:
    """Load a zero-quarantine canonical mapping result without source inference."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def publish_mapping(
        self,
        *,
        source_id: UUID,
        mapping: CanonicalMappingResult,
    ) -> CanonicalCatalogLoadResult:
        """Publish every mapped record atomically or reject the complete slice.

        The approved Kaggle mapping has no event identifier.  Such facts remain
        explicitly event-unresolved in PostgreSQL; this method never groups rows
        by date/location or manufactures an event reference.
        """
        try:
            require_publishable_mapping(mapping)
        except CanonicalMappingBlocked as blocked:
            issues = tuple(
                CanonicalCatalogIssue(
                    rule_id=issue.rule_id,
                    source_record_key=issue.source_record_key,
                    raw_sha256=issue.raw_sha256,
                    summary=issue.summary,
                )
                for issue in blocked.issues
            )
            await self._record_issues(source_id, issues)
            raise CanonicalCatalogPublicationBlocked(issues) from blocked

        try:
            async with self._session_factory() as session, session.begin():
                source = await session.scalar(
                    select(DataSource).where(DataSource.source_id == source_id).with_for_update()
                )
                if source is None:
                    raise ValueError(f"canonical catalog source does not exist: {source_id}")
                fight_ids: list[UUID] = []
                replayed_record_keys: list[str] = []
                for observation in mapping.accepted:
                    if observation.source_identifier != source.stable_key:
                        raise _CanonicalCatalogLoadFailure(
                            _issue(
                                observation,
                                "CAN-005.source_identifier_mismatch",
                                "mapped source identifier does not match the durable source record",
                            )
                        )
                    existing = await session.scalar(
                        select(FightSourceReference).where(
                            FightSourceReference.source_id == source_id,
                            FightSourceReference.canonical_source_fight_key
                            == observation.canonical_source_fight_key,
                        )
                    )
                    if existing is not None:
                        await self._verify_replay(session, existing, observation)
                        fight_ids.append(existing.fight_id)
                        replayed_record_keys.append(observation.source_record_key)
                        continue
                    fight_ids.append(
                        await self._insert_observation(session, source_id, observation)
                    )
                return CanonicalCatalogLoadResult(tuple(fight_ids), tuple(replayed_record_keys))
        except _CanonicalCatalogLoadFailure as blocked:
            await self._record_issues(source_id, (blocked.issue,))
            raise CanonicalCatalogPublicationBlocked((blocked.issue,)) from blocked

    async def _insert_observation(
        self,
        session: AsyncSession,
        source_id: UUID,
        observation: CanonicalFightObservation,
    ) -> UUID:
        raw_object = await session.scalar(
            select(RawObject).where(
                RawObject.source_id == source_id,
                RawObject.sha256 == observation.raw_reference.sha256,
            )
        )
        if raw_object is None or raw_object.object_uri != observation.raw_reference.object_uri:
            raise _CanonicalCatalogLoadFailure(
                _issue(
                    observation,
                    "CAN-005.raw_reference_missing",
                    "mapped raw reference is not present for the selected source",
                )
            )
        fighters = await self._resolved_fighters(session, observation)
        decisions = await self._applied_decisions(session, observation, fighters)
        division = await session.scalar(
            select(Division).where(Division.canonical_code == observation.canonical_division_code)
        )
        if division is None:
            division = Division(canonical_code=observation.canonical_division_code)
            session.add(division)
            await session.flush()

        fight = Fight(
            event_id=None,
            event_context_status="not_observed",
            status="completed",
            division_id=division.division_id,
            scheduled_rounds=observation.scheduled_rounds,
            fight_date=observation.fight_date,
            title_bout=observation.title_bout,
            location=observation.location,
            country=observation.country,
        )
        session.add(fight)
        await session.flush()
        source_reference = FightSourceReference(
            fight_id=fight.fight_id,
            source_id=source_id,
            raw_object_id=raw_object.raw_object_id,
            source_schema_version=observation.source_schema_version,
            source_record_key=observation.source_record_key,
            canonical_source_fight_key=observation.canonical_source_fight_key,
            ingested_at=observation.ingested_at,
            taxonomy_version=observation.taxonomy_version,
        )
        session.add(source_reference)
        await session.flush()
        participants = {
            observation.fighter_one_id: FightParticipant(
                fight_id=fight.fight_id, fighter_id=observation.fighter_one_id, canonical_slot=0
            ),
            observation.fighter_two_id: FightParticipant(
                fight_id=fight.fight_id, fighter_id=observation.fighter_two_id, canonical_slot=1
            ),
        }
        session.add_all(participants.values())
        await session.flush()
        session.add_all(
            FightParticipantIdentityEvidence(
                fight_participant_id=participants[fighter_id].fight_participant_id,
                identity_resolution_decision_id=decision_id,
            )
            for fighter_id, decision_id in decisions.items()
        )
        winner_participant_id = (
            None
            if observation.winner_fighter_id is None
            else participants[observation.winner_fighter_id].fight_participant_id
        )
        session.add(
            FightResult(
                fight_id=fight.fight_id,
                fight_source_reference_id=source_reference.fight_source_reference_id,
                source_id=source_id,
                raw_object_id=raw_object.raw_object_id,
                winner_participant_id=winner_participant_id,
                outcome_type=observation.outcome_type.value,
                canonical_method_code=observation.canonical_method_code,
                source_outcome_label=observation.source_outcome_label,
                source_method_label=observation.source_method_label,
                effective_date=observation.fight_date,
                ingested_at=observation.ingested_at,
                system_from=observation.ingested_at,
                taxonomy_version=observation.taxonomy_version,
            )
        )
        await session.flush()
        fight.publication_state = "published"
        await session.flush()
        return fight.fight_id

    async def _resolved_fighters(
        self, session: AsyncSession, observation: CanonicalFightObservation
    ) -> frozenset[UUID]:
        fighter_ids = {observation.fighter_one_id, observation.fighter_two_id}
        fighters = list(
            (
                await session.scalars(
                    select(Fighter).where(Fighter.fighter_id.in_(fighter_ids)).with_for_update()
                )
            ).all()
        )
        if len(fighters) != 2 or any(
            fighter.merged_into_fighter_id is not None for fighter in fighters
        ):
            raise _CanonicalCatalogLoadFailure(
                _issue(
                    observation,
                    "CAN-005.unavailable_canonical_fighter",
                    "mapped participants are not active canonical fighters",
                )
            )
        return frozenset(fighter.fighter_id for fighter in fighters)

    async def _applied_decisions(
        self,
        session: AsyncSession,
        observation: CanonicalFightObservation,
        fighter_ids: frozenset[UUID],
    ) -> dict[UUID, UUID]:
        applications = list(
            (
                await session.scalars(
                    select(IdentityResolutionApplication).where(
                        IdentityResolutionApplication.decision_id.in_(
                            observation.identity_resolution_decision_ids
                        ),
                        IdentityResolutionApplication.state == "applied",
                    )
                )
            ).all()
        )
        by_fighter = {
            application.canonical_fighter_id: application.decision_id
            for application in applications
            if application.canonical_fighter_id is not None
        }
        if set(by_fighter) != fighter_ids or len(by_fighter) != 2:
            raise _CanonicalCatalogLoadFailure(
                _issue(
                    observation,
                    "CAN-005.unapplied_identity_decision",
                    "mapped participants lack matching applied identity decisions",
                )
            )
        return {fighter_id: decision_id for fighter_id, decision_id in by_fighter.items()}

    async def _verify_replay(
        self,
        session: AsyncSession,
        reference: FightSourceReference,
        observation: CanonicalFightObservation,
    ) -> None:
        if (
            reference.source_record_key != observation.source_record_key
            or reference.source_schema_version != observation.source_schema_version
            or reference.taxonomy_version != observation.taxonomy_version
        ):
            raise _CanonicalCatalogLoadFailure(
                _issue(
                    observation,
                    "CAN-006.conflicting_catalog_replay",
                    "existing canonical source reference conflicts with the replayed observation",
                )
            )
        raw_object = await session.scalar(
            select(RawObject).where(RawObject.raw_object_id == reference.raw_object_id)
        )
        if (
            raw_object is None
            or raw_object.sha256 != observation.raw_reference.sha256
            or raw_object.object_uri != observation.raw_reference.object_uri
        ):
            raise _CanonicalCatalogLoadFailure(
                _issue(
                    observation,
                    "CAN-006.conflicting_catalog_replay",
                    "existing canonical source reference has different raw provenance",
                )
            )
        fight = await session.scalar(select(Fight).where(Fight.fight_id == reference.fight_id))
        if fight is None or fight.publication_state != "published":
            raise _CanonicalCatalogLoadFailure(
                _issue(
                    observation,
                    "CAN-006.unpublished_catalog_replay",
                    "existing canonical source reference points to an unpublished fight",
                )
            )
        division = await session.scalar(
            select(Division).where(Division.division_id == fight.division_id)
        )
        if (
            division is None
            or division.canonical_code != observation.canonical_division_code
            or fight.scheduled_rounds != observation.scheduled_rounds
            or fight.fight_date != observation.fight_date
            or fight.title_bout != observation.title_bout
            or fight.location != observation.location
            or fight.country != observation.country
        ):
            raise _CanonicalCatalogLoadFailure(
                _issue(
                    observation,
                    "CAN-006.conflicting_catalog_replay",
                    "existing canonical fight context conflicts with the replayed observation",
                )
            )
        participant_ids = set(
            (
                await session.scalars(
                    select(FightParticipant.fighter_id).where(
                        FightParticipant.fight_id == fight.fight_id
                    )
                )
            ).all()
        )
        if participant_ids != {observation.fighter_one_id, observation.fighter_two_id}:
            raise _CanonicalCatalogLoadFailure(
                _issue(
                    observation,
                    "CAN-006.conflicting_catalog_replay",
                    "existing canonical fight participants conflict with the replayed observation",
                )
            )
        result = await session.scalar(
            select(FightResult).where(
                FightResult.fight_source_reference_id == reference.fight_source_reference_id
            )
        )
        winner_fighter_id = None
        if result is not None and result.winner_participant_id is not None:
            winner_fighter_id = await session.scalar(
                select(FightParticipant.fighter_id).where(
                    FightParticipant.fight_participant_id == result.winner_participant_id
                )
            )
        if (
            result is None
            or result.outcome_type != observation.outcome_type.value
            or result.canonical_method_code != observation.canonical_method_code
            or result.source_outcome_label != observation.source_outcome_label
            or result.source_method_label != observation.source_method_label
            or result.taxonomy_version != observation.taxonomy_version
            or winner_fighter_id != observation.winner_fighter_id
        ):
            raise _CanonicalCatalogLoadFailure(
                _issue(
                    observation,
                    "CAN-006.conflicting_catalog_replay",
                    "existing canonical result conflicts with the replayed observation",
                )
            )

    async def _record_issues(
        self, source_id: UUID, issues: tuple[CanonicalCatalogIssue, ...]
    ) -> None:
        """Upsert reviewable canonical blocks without retrying the failed publication."""
        if not issues:
            raise ValueError("a blocked canonical publication requires durable issues")
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            source_exists = await session.scalar(
                select(DataSource.source_id).where(DataSource.source_id == source_id)
            )
            if source_exists is None:
                raise ValueError(f"canonical catalog source does not exist: {source_id}")
            for issue in issues:
                issue_key = _issue_key(source_id, issue)
                statement = (
                    insert(DataQualityIssue)
                    .values(
                        source_id=source_id,
                        entity_type="canonical_source_record",
                        entity_id=issue.source_record_key[:256],
                        rule_id=issue.rule_id,
                        canonical_issue_key=issue_key,
                        severity="blocking",
                        blocking=True,
                        safe_summary=issue.summary[:2_000],
                        evidence={
                            "raw_sha256": issue.raw_sha256,
                            "source_record_key": issue.source_record_key,
                        },
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    .on_conflict_do_update(
                        index_elements=["source_id", "canonical_issue_key"],
                        index_where=DataQualityIssue.canonical_issue_key.is_not(None),
                        set_={
                            "occurrence_count": DataQualityIssue.occurrence_count + 1,
                            "last_seen_at": now,
                        },
                    )
                )
                await session.execute(statement)


def _issue(
    observation: CanonicalFightObservation, rule_id: str, summary: str
) -> CanonicalCatalogIssue:
    return CanonicalCatalogIssue(
        rule_id=rule_id,
        source_record_key=observation.source_record_key,
        raw_sha256=observation.raw_reference.sha256,
        summary=summary,
    )


def _issue_key(source_id: UUID, issue: CanonicalCatalogIssue) -> str:
    payload = "\x1f".join(
        (str(source_id), issue.rule_id, issue.source_record_key, issue.raw_sha256)
    ).encode("utf-8")
    return sha256(payload).hexdigest()
