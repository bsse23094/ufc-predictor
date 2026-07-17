"""Durable persistence for append-only fighter-identity review evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ufc_api.data.models import DataSource, RawObject
from ufc_api.fighters.models import (
    Fighter,
    FighterAlias,
    FighterAliasSupersession,
    FighterIdentityMerge,
    FighterIdentitySplit,
    IdentityResolutionApplication,
    IdentityResolutionDecision,
)
from ufc_predictor.identity.resolver import ReviewedFighterMerge, ReviewedFighterSplit
from ufc_predictor.identity.review import IdentityReviewDecision, IdentityReviewQueueItem


class ResolutionApplicationState(StrEnum):
    """Terminal, immutable outcomes for an explicit review decision."""

    APPLIED = "applied"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class ReviewedAliasInput:
    """A reviewed source alias that must exactly match retained decision evidence."""

    source_id: UUID
    raw_object_id: UUID
    source_record_key: str
    source_field: str
    alias_value: str
    normalized_value: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ResolutionApplicationResult:
    """An idempotent application result with no implicit resolution fallback."""

    application_id: UUID
    state: ResolutionApplicationState
    fighter_alias_ids: tuple[UUID, ...]
    quarantine_reason: str | None


@dataclass(frozen=True, slots=True)
class ReviewedFighterMergeResult:
    """The immutable result of applying one reviewed canonical-fighter merge."""

    application_id: UUID
    state: ResolutionApplicationState
    fighter_identity_merge_id: UUID | None
    quarantine_reason: str | None


@dataclass(frozen=True, slots=True)
class ReviewedFighterSplitResult:
    """The immutable result of applying one reviewed canonical-fighter split."""

    application_id: UUID
    state: ResolutionApplicationState
    fighter_identity_split_id: UUID | None
    quarantine_reason: str | None


class FighterIdentityRepository:
    """Persist human review records without resolving or mutating a fighter identity."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_review_decision(
        self,
        *,
        item: IdentityReviewQueueItem,
        decision: IdentityReviewDecision,
        supersedes_decision_id: UUID | None = None,
    ) -> UUID:
        """Append a reviewed candidate decision with both source occurrences as evidence."""

        if item.review_key != decision.review_key:
            raise ValueError("review decision does not belong to the queue item")
        score = item.score
        first = score.candidate_pair.first
        second = score.candidate_pair.second
        async with self._session_factory() as session, session.begin():
            if supersedes_decision_id is not None:
                superseded = await session.scalar(
                    select(IdentityResolutionDecision)
                    .where(
                        IdentityResolutionDecision.identity_resolution_decision_id
                        == supersedes_decision_id
                    )
                    .with_for_update()
                )
                if superseded is None:
                    raise ValueError(
                        "superseded identity review decision does not exist: "
                        f"{supersedes_decision_id}"
                    )
            record = IdentityResolutionDecision(
                review_key=item.review_key,
                entity_type="fighter_alias_candidate",
                decision_type=decision.decision.value,
                supersedes_decision_id=supersedes_decision_id,
                evidence={
                    "scorer_version": score.scorer_version,
                    "score": score.score,
                    "recommendation": score.recommendation.value,
                    "evidence": list(score.evidence),
                    "first": _candidate_evidence(first),
                    "second": _candidate_evidence(second),
                },
                actor=decision.decided_by,
                decided_at=decision.decided_at,
                rationale=decision.rationale,
            )
            session.add(record)
            await session.flush()
            return record.identity_resolution_decision_id

    async def apply_proposed_link(
        self,
        *,
        decision_id: UUID,
        canonical_fighter_id: UUID,
        aliases: Sequence[ReviewedAliasInput],
        applied_by: str,
    ) -> ResolutionApplicationResult:
        """Apply one explicit link proposal or durably quarantine inconsistent evidence."""

        if not applied_by.strip():
            raise ValueError("applied_by is required")
        async with self._session_factory() as session, session.begin():
            decision = await session.scalar(
                select(IdentityResolutionDecision)
                .where(IdentityResolutionDecision.identity_resolution_decision_id == decision_id)
                .with_for_update()
            )
            if decision is None:
                raise ValueError(f"identity review decision does not exist: {decision_id}")
            existing = await session.scalar(
                select(IdentityResolutionApplication)
                .where(IdentityResolutionApplication.decision_id == decision_id)
                .with_for_update()
            )
            if existing is not None:
                return _application_result(existing)

            if decision.decision_type != "propose_link":
                return await self._quarantine(
                    session,
                    decision_id=decision_id,
                    applied_by=applied_by,
                    reason="only propose_link decisions may create canonical aliases",
                )
            fighter = await session.scalar(
                select(Fighter).where(Fighter.fighter_id == canonical_fighter_id).with_for_update()
            )
            if fighter is None or fighter.merged_into_fighter_id is not None:
                return await self._quarantine(
                    session,
                    decision_id=decision_id,
                    applied_by=applied_by,
                    reason="the selected canonical fighter is unavailable for resolution",
                )

            expected = _decision_alias_evidence(decision.evidence)
            if expected is None:
                return await self._quarantine(
                    session,
                    decision_id=decision_id,
                    applied_by=applied_by,
                    reason="review decision has malformed alias evidence",
                )
            resolved = await self._validate_alias_inputs(session, aliases, expected)
            if resolved is None:
                return await self._quarantine(
                    session,
                    decision_id=decision_id,
                    applied_by=applied_by,
                    reason="reviewed aliases do not exactly match retained source evidence",
                )
            if await self._has_current_alias(session, resolved):
                return await self._quarantine(
                    session,
                    decision_id=decision_id,
                    applied_by=applied_by,
                    reason="a current alias already has the same source evidence",
                )

            created_aliases = [
                FighterAlias(
                    fighter_id=canonical_fighter_id,
                    source_id=alias.source_id,
                    raw_object_id=alias.raw_object_id,
                    alias_type="fighter_name",
                    alias_value=alias.alias_value,
                    normalized_value=alias.normalized_value,
                    resolution_status="resolved_by_review",
                    evidence={
                        "identity_resolution_decision_id": str(decision_id),
                        "source_record_key": alias.source_record_key,
                        "source_field": alias.source_field,
                    },
                    observed_at=alias.observed_at,
                )
                for alias in resolved
            ]
            session.add_all(created_aliases)
            application = IdentityResolutionApplication(
                decision_id=decision_id,
                canonical_fighter_id=canonical_fighter_id,
                state=ResolutionApplicationState.APPLIED.value,
                applied_by=applied_by,
                applied_at=_utc_now(),
            )
            session.add(application)
            await session.flush()
            return ResolutionApplicationResult(
                application_id=application.identity_resolution_application_id,
                state=ResolutionApplicationState.APPLIED,
                fighter_alias_ids=tuple(alias.fighter_alias_id for alias in created_aliases),
                quarantine_reason=None,
            )

    async def merge_reviewed_fighters(
        self,
        *,
        request: ReviewedFighterMerge,
        applied_by: str,
    ) -> ReviewedFighterMergeResult:
        """Merge two reviewed identities without reparenting their source aliases."""

        if not applied_by.strip():
            raise ValueError("applied_by is required")
        async with self._session_factory() as session, session.begin():
            decision = await self._locked_decision(session, request.decision_id)
            existing = await self._locked_application(session, request.decision_id)
            if existing is not None:
                return await self._stored_merge_result(session, existing)
            if (
                decision.decision_type != "propose_merge"
                or decision.supersedes_decision_id is not None
            ):
                quarantined = await self._quarantine(
                    session,
                    decision_id=request.decision_id,
                    applied_by=applied_by,
                    reason="a merge requires an original propose_merge review decision",
                )
                return _merge_quarantine_result(quarantined)

            canonical = await self._locked_fighter(session, request.canonical_fighter_id)
            merged = await self._locked_fighter(session, request.merged_fighter_id)
            if (
                canonical is None
                or merged is None
                or canonical.merged_into_fighter_id is not None
                or merged.merged_into_fighter_id is not None
            ):
                quarantined = await self._quarantine(
                    session,
                    decision_id=request.decision_id,
                    applied_by=applied_by,
                    reason="both selected fighters must be active before a reviewed merge",
                )
                return _merge_quarantine_result(quarantined)

            reviewed_aliases = await self._reviewed_aliases_for_decision(session, decision)
            if reviewed_aliases is None or {alias.fighter_id for alias in reviewed_aliases} != {
                request.canonical_fighter_id,
                request.merged_fighter_id,
            }:
                quarantined = await self._quarantine(
                    session,
                    decision_id=request.decision_id,
                    applied_by=applied_by,
                    reason=(
                        "merge review evidence does not identify one current alias for each fighter"
                    ),
                )
                return _merge_quarantine_result(quarantined)

            applied_at = _utc_now()
            application = IdentityResolutionApplication(
                decision_id=request.decision_id,
                canonical_fighter_id=request.canonical_fighter_id,
                state=ResolutionApplicationState.APPLIED.value,
                applied_by=applied_by,
                applied_at=applied_at,
            )
            session.add(application)
            await session.flush()
            merge = FighterIdentityMerge(
                identity_resolution_application_id=application.identity_resolution_application_id,
                canonical_fighter_id=request.canonical_fighter_id,
                merged_fighter_id=request.merged_fighter_id,
                merged_at=applied_at,
                applied_by=applied_by,
            )
            session.add(merge)
            await session.flush()
            merged.merged_into_fighter_id = request.canonical_fighter_id
            merged.identity_status = "merged"
            merged.row_version += 1
            await session.flush()
            return ReviewedFighterMergeResult(
                application_id=application.identity_resolution_application_id,
                state=ResolutionApplicationState.APPLIED,
                fighter_identity_merge_id=merge.fighter_identity_merge_id,
                quarantine_reason=None,
            )

    async def split_reviewed_fighters(
        self,
        *,
        request: ReviewedFighterSplit,
        applied_by: str,
    ) -> ReviewedFighterSplitResult:
        """Restore one specifically merged fighter with a superseding review decision.

        A split restores the canonical identity edge only.  It never rewrites or
        transfers aliases; any alias correction remains an explicit bitemporal
        reviewed-alias operation.
        """

        if not applied_by.strip():
            raise ValueError("applied_by is required")
        async with self._session_factory() as session, session.begin():
            decision = await self._locked_decision(session, request.decision_id)
            existing = await self._locked_application(session, request.decision_id)
            if existing is not None:
                return await self._stored_split_result(session, existing)
            if decision.decision_type != "propose_split" or decision.supersedes_decision_id is None:
                quarantined = await self._quarantine(
                    session,
                    decision_id=request.decision_id,
                    applied_by=applied_by,
                    reason=(
                        "a split requires a propose_split decision that supersedes its merge review"
                    ),
                )
                return _split_quarantine_result(quarantined)

            canonical = await self._locked_fighter(session, request.canonical_fighter_id)
            restored = await self._locked_fighter(session, request.restored_fighter_id)
            if (
                canonical is None
                or restored is None
                or canonical.merged_into_fighter_id is not None
                or restored.merged_into_fighter_id != request.canonical_fighter_id
            ):
                quarantined = await self._quarantine(
                    session,
                    decision_id=request.decision_id,
                    applied_by=applied_by,
                    reason="the requested split does not match the current canonical merge state",
                )
                return _split_quarantine_result(quarantined)

            reviewed_aliases = await self._reviewed_aliases_for_decision(session, decision)
            if reviewed_aliases is None or {alias.fighter_id for alias in reviewed_aliases} != {
                request.canonical_fighter_id,
                request.restored_fighter_id,
            }:
                quarantined = await self._quarantine(
                    session,
                    decision_id=request.decision_id,
                    applied_by=applied_by,
                    reason=(
                        "split review evidence does not identify one current alias for each fighter"
                    ),
                )
                return _split_quarantine_result(quarantined)

            merge = await self._current_merge(
                session,
                canonical_fighter_id=request.canonical_fighter_id,
                merged_fighter_id=request.restored_fighter_id,
            )
            if merge is None:
                quarantined = await self._quarantine(
                    session,
                    decision_id=request.decision_id,
                    applied_by=applied_by,
                    reason="split review does not supersede the active reviewed merge",
                )
                return _split_quarantine_result(quarantined)
            if not await self._merge_has_superseded_review(
                session, merge, decision.supersedes_decision_id
            ):
                quarantined = await self._quarantine(
                    session,
                    decision_id=request.decision_id,
                    applied_by=applied_by,
                    reason="split review does not supersede the active reviewed merge",
                )
                return _split_quarantine_result(quarantined)

            applied_at = _utc_now()
            application = IdentityResolutionApplication(
                decision_id=request.decision_id,
                canonical_fighter_id=request.canonical_fighter_id,
                state=ResolutionApplicationState.APPLIED.value,
                applied_by=applied_by,
                applied_at=applied_at,
            )
            session.add(application)
            await session.flush()
            split = FighterIdentitySplit(
                identity_resolution_application_id=application.identity_resolution_application_id,
                fighter_identity_merge_id=merge.fighter_identity_merge_id,
                canonical_fighter_id=request.canonical_fighter_id,
                restored_fighter_id=request.restored_fighter_id,
                split_at=applied_at,
                applied_by=applied_by,
            )
            session.add(split)
            await session.flush()
            restored.merged_into_fighter_id = None
            restored.identity_status = "resolved_by_review"
            restored.row_version += 1
            await session.flush()
            return ReviewedFighterSplitResult(
                application_id=application.identity_resolution_application_id,
                state=ResolutionApplicationState.APPLIED,
                fighter_identity_split_id=split.fighter_identity_split_id,
                quarantine_reason=None,
            )

    async def supersede_reviewed_aliases(
        self,
        *,
        decision_id: UUID,
        canonical_fighter_id: UUID,
        aliases: Sequence[ReviewedAliasInput],
        superseded_alias_ids: Sequence[UUID],
        applied_by: str,
    ) -> ResolutionApplicationResult:
        """Correct reviewed aliases without rewriting the prior alias or decision history."""

        if not applied_by.strip():
            raise ValueError("applied_by is required")
        async with self._session_factory() as session, session.begin():
            decision = await session.scalar(
                select(IdentityResolutionDecision)
                .where(IdentityResolutionDecision.identity_resolution_decision_id == decision_id)
                .with_for_update()
            )
            if decision is None:
                raise ValueError(f"identity review decision does not exist: {decision_id}")
            existing = await session.scalar(
                select(IdentityResolutionApplication)
                .where(IdentityResolutionApplication.decision_id == decision_id)
                .with_for_update()
            )
            if existing is not None:
                return _application_result(existing)
            if decision.decision_type != "propose_link" or decision.supersedes_decision_id is None:
                return await self._quarantine(
                    session,
                    decision_id=decision_id,
                    applied_by=applied_by,
                    reason=(
                        "a correction requires a propose_link decision that supersedes prior review"
                    ),
                )
            fighter = await session.scalar(
                select(Fighter).where(Fighter.fighter_id == canonical_fighter_id).with_for_update()
            )
            if fighter is None or fighter.merged_into_fighter_id is not None:
                return await self._quarantine(
                    session,
                    decision_id=decision_id,
                    applied_by=applied_by,
                    reason="the selected canonical fighter is unavailable for correction",
                )
            expected = _decision_alias_evidence(decision.evidence)
            if expected is None:
                return await self._quarantine(
                    session,
                    decision_id=decision_id,
                    applied_by=applied_by,
                    reason="correction review decision has malformed alias evidence",
                )
            resolved = await self._validate_alias_inputs(session, aliases, expected)
            if resolved is None:
                return await self._quarantine(
                    session,
                    decision_id=decision_id,
                    applied_by=applied_by,
                    reason="corrected aliases do not exactly match retained source evidence",
                )
            superseded = await self._validated_superseded_aliases(
                session,
                superseded_decision_id=decision.supersedes_decision_id,
                aliases=resolved,
                superseded_alias_ids=superseded_alias_ids,
                replacement_fighter_id=canonical_fighter_id,
            )
            if superseded is None:
                return await self._quarantine(
                    session,
                    decision_id=decision_id,
                    applied_by=applied_by,
                    reason="superseded aliases are not the current aliases from the prior review",
                )

            applied_at = _utc_now()
            for alias in superseded:
                alias.system_to = applied_at
            replacements = [
                FighterAlias(
                    fighter_id=canonical_fighter_id,
                    source_id=alias.source_id,
                    raw_object_id=alias.raw_object_id,
                    alias_type="fighter_name",
                    alias_value=alias.alias_value,
                    normalized_value=alias.normalized_value,
                    resolution_status="corrected_by_review",
                    evidence={
                        "identity_resolution_decision_id": str(decision_id),
                        "supersedes_decision_id": str(decision.supersedes_decision_id),
                        "source_record_key": alias.source_record_key,
                        "source_field": alias.source_field,
                    },
                    observed_at=alias.observed_at,
                )
                for alias in resolved
            ]
            session.add_all(replacements)
            application = IdentityResolutionApplication(
                decision_id=decision_id,
                canonical_fighter_id=canonical_fighter_id,
                state=ResolutionApplicationState.APPLIED.value,
                applied_by=applied_by,
                applied_at=applied_at,
            )
            session.add(application)
            await session.flush()
            replacement_by_lineage = {
                (
                    alias.source_id,
                    alias.raw_object_id,
                    alias.alias_value,
                    alias.normalized_value,
                ): alias
                for alias in replacements
            }
            session.add_all(
                FighterAliasSupersession(
                    identity_resolution_application_id=application.identity_resolution_application_id,
                    superseded_alias_id=old_alias.fighter_alias_id,
                    replacement_alias_id=replacement_by_lineage[
                        (
                            old_alias.source_id,
                            old_alias.raw_object_id,
                            old_alias.alias_value,
                            old_alias.normalized_value,
                        )
                    ].fighter_alias_id,
                    superseded_at=applied_at,
                    applied_by=applied_by,
                )
                for old_alias in superseded
            )
            await session.flush()
            return ResolutionApplicationResult(
                application_id=application.identity_resolution_application_id,
                state=ResolutionApplicationState.APPLIED,
                fighter_alias_ids=tuple(alias.fighter_alias_id for alias in replacements),
                quarantine_reason=None,
            )

    async def _locked_decision(
        self, session: AsyncSession, decision_id: UUID
    ) -> IdentityResolutionDecision:
        decision = await session.scalar(
            select(IdentityResolutionDecision)
            .where(IdentityResolutionDecision.identity_resolution_decision_id == decision_id)
            .with_for_update()
        )
        if decision is None:
            raise ValueError(f"identity review decision does not exist: {decision_id}")
        return decision

    async def _locked_application(
        self, session: AsyncSession, decision_id: UUID
    ) -> IdentityResolutionApplication | None:
        return cast(
            IdentityResolutionApplication | None,
            await session.scalar(
                select(IdentityResolutionApplication)
                .where(IdentityResolutionApplication.decision_id == decision_id)
                .with_for_update()
            ),
        )

    async def _locked_fighter(self, session: AsyncSession, fighter_id: UUID) -> Fighter | None:
        return cast(
            Fighter | None,
            await session.scalar(
                select(Fighter).where(Fighter.fighter_id == fighter_id).with_for_update()
            ),
        )

    async def _reviewed_aliases_for_decision(
        self, session: AsyncSession, decision: IdentityResolutionDecision
    ) -> tuple[FighterAlias, ...] | None:
        expected = _decision_alias_evidence(decision.evidence)
        if expected is None:
            return None
        records = (
            await session.execute(
                select(
                    FighterAlias,
                    DataSource.stable_key,
                    RawObject.sha256,
                    RawObject.source_id,
                )
                .join(DataSource, FighterAlias.source_id == DataSource.source_id)
                .join(RawObject, FighterAlias.raw_object_id == RawObject.raw_object_id)
                .where(
                    FighterAlias.alias_type == "fighter_name",
                    FighterAlias.system_to.is_(None),
                )
                .with_for_update()
            )
        ).all()
        matches: list[FighterAlias] = []
        matched_lineages: set[tuple[str, str, str, str, str, str]] = set()
        for alias, source_key, raw_sha256, raw_source_id in records:
            if alias.source_id != raw_source_id:
                return None
            evidence = alias.evidence
            if (
                alias.resolution_status not in {"resolved_by_review", "corrected_by_review"}
                or not isinstance(evidence, Mapping)
                or not isinstance(evidence.get("identity_resolution_decision_id"), str)
            ):
                continue
            source_record_key = evidence.get("source_record_key")
            source_field = evidence.get("source_field")
            if not isinstance(source_record_key, str) or not isinstance(source_field, str):
                continue
            lineage = (
                source_key,
                raw_sha256,
                source_record_key,
                source_field,
                alias.alias_value,
                alias.normalized_value,
            )
            if lineage in expected:
                matches.append(alias)
                matched_lineages.add(lineage)
        if len(matches) != len(expected):
            return None
        return tuple(matches) if matched_lineages == expected else None

    async def _current_merge(
        self,
        session: AsyncSession,
        *,
        canonical_fighter_id: UUID,
        merged_fighter_id: UUID,
    ) -> FighterIdentityMerge | None:
        return cast(
            FighterIdentityMerge | None,
            await session.scalar(
                select(FighterIdentityMerge)
                .outerjoin(
                    FighterIdentitySplit,
                    FighterIdentitySplit.fighter_identity_merge_id
                    == FighterIdentityMerge.fighter_identity_merge_id,
                )
                .where(
                    FighterIdentityMerge.canonical_fighter_id == canonical_fighter_id,
                    FighterIdentityMerge.merged_fighter_id == merged_fighter_id,
                    FighterIdentitySplit.fighter_identity_split_id.is_(None),
                )
                .order_by(FighterIdentityMerge.merged_at.desc())
                .with_for_update(of=FighterIdentityMerge)
            ),
        )

    async def _merge_has_superseded_review(
        self,
        session: AsyncSession,
        merge: FighterIdentityMerge,
        superseded_decision_id: UUID,
    ) -> bool:
        application = await session.scalar(
            select(IdentityResolutionApplication)
            .where(
                IdentityResolutionApplication.identity_resolution_application_id
                == merge.identity_resolution_application_id
            )
            .with_for_update()
        )
        return application is not None and application.decision_id == superseded_decision_id

    async def _stored_merge_result(
        self, session: AsyncSession, application: IdentityResolutionApplication
    ) -> ReviewedFighterMergeResult:
        if application.state == ResolutionApplicationState.QUARANTINED.value:
            return _merge_quarantine_result(_application_result(application))
        merge = await session.scalar(
            select(FighterIdentityMerge)
            .where(
                FighterIdentityMerge.identity_resolution_application_id
                == application.identity_resolution_application_id
            )
            .with_for_update()
        )
        if merge is None:
            raise ValueError(
                "review decision was already applied by a different identity operation"
            )
        return ReviewedFighterMergeResult(
            application_id=application.identity_resolution_application_id,
            state=ResolutionApplicationState.APPLIED,
            fighter_identity_merge_id=merge.fighter_identity_merge_id,
            quarantine_reason=None,
        )

    async def _stored_split_result(
        self, session: AsyncSession, application: IdentityResolutionApplication
    ) -> ReviewedFighterSplitResult:
        if application.state == ResolutionApplicationState.QUARANTINED.value:
            return _split_quarantine_result(_application_result(application))
        split = await session.scalar(
            select(FighterIdentitySplit)
            .where(
                FighterIdentitySplit.identity_resolution_application_id
                == application.identity_resolution_application_id
            )
            .with_for_update()
        )
        if split is None:
            raise ValueError(
                "review decision was already applied by a different identity operation"
            )
        return ReviewedFighterSplitResult(
            application_id=application.identity_resolution_application_id,
            state=ResolutionApplicationState.APPLIED,
            fighter_identity_split_id=split.fighter_identity_split_id,
            quarantine_reason=None,
        )

    async def _validate_alias_inputs(
        self,
        session: AsyncSession,
        aliases: Sequence[ReviewedAliasInput],
        expected: set[tuple[str, str, str, str, str, str]],
    ) -> tuple[ReviewedAliasInput, ...] | None:
        if len(aliases) != len(expected):
            return None
        actual: set[tuple[str, str, str, str, str, str]] = set()
        for alias in aliases:
            if alias.observed_at.tzinfo is None or alias.observed_at.utcoffset() is None:
                return None
            source = await session.scalar(
                select(DataSource).where(DataSource.source_id == alias.source_id).with_for_update()
            )
            raw_object = await session.scalar(
                select(RawObject)
                .where(RawObject.raw_object_id == alias.raw_object_id)
                .with_for_update()
            )
            if source is None or raw_object is None or raw_object.source_id != source.source_id:
                return None
            actual.add(
                (
                    source.stable_key,
                    raw_object.sha256,
                    alias.source_record_key,
                    alias.source_field,
                    alias.alias_value,
                    alias.normalized_value,
                )
            )
        if actual != expected:
            return None
        if any(not alias.normalized_value.strip() for alias in aliases):
            return None
        return tuple(aliases)

    async def _has_current_alias(
        self,
        session: AsyncSession,
        aliases: Sequence[ReviewedAliasInput],
    ) -> bool:
        for alias in aliases:
            existing = await session.scalar(
                select(FighterAlias)
                .where(
                    FighterAlias.source_id == alias.source_id,
                    FighterAlias.raw_object_id == alias.raw_object_id,
                    FighterAlias.alias_type == "fighter_name",
                    FighterAlias.alias_value == alias.alias_value,
                    FighterAlias.normalized_value == alias.normalized_value,
                    FighterAlias.system_to.is_(None),
                )
                .with_for_update()
            )
            if existing is not None:
                return True
        return False

    async def _validated_superseded_aliases(
        self,
        session: AsyncSession,
        *,
        superseded_decision_id: UUID,
        aliases: Sequence[ReviewedAliasInput],
        superseded_alias_ids: Sequence[UUID],
        replacement_fighter_id: UUID,
    ) -> tuple[FighterAlias, ...] | None:
        if len(aliases) != len(superseded_alias_ids) or len(set(superseded_alias_ids)) != len(
            aliases
        ):
            return None
        prior_application = await session.scalar(
            select(IdentityResolutionApplication)
            .where(IdentityResolutionApplication.decision_id == superseded_decision_id)
            .with_for_update()
        )
        if (
            prior_application is None
            or prior_application.state != ResolutionApplicationState.APPLIED.value
            or prior_application.canonical_fighter_id is None
            or prior_application.canonical_fighter_id == replacement_fighter_id
        ):
            return None
        expected_by_lineage = {
            (alias.source_id, alias.raw_object_id, alias.alias_value, alias.normalized_value): alias
            for alias in aliases
        }
        superseded: list[FighterAlias] = []
        for alias_id in superseded_alias_ids:
            alias = await session.scalar(
                select(FighterAlias)
                .where(FighterAlias.fighter_alias_id == alias_id)
                .with_for_update()
            )
            if (
                alias is None
                or alias.system_to is not None
                or alias.fighter_id != prior_application.canonical_fighter_id
                or alias.alias_type != "fighter_name"
            ):
                return None
            input_alias = expected_by_lineage.pop(
                (alias.source_id, alias.raw_object_id, alias.alias_value, alias.normalized_value),
                None,
            )
            if input_alias is None or not _alias_records_prior_decision(
                alias, superseded_decision_id
            ):
                return None
            superseded.append(alias)
        return tuple(superseded) if not expected_by_lineage else None

    async def _quarantine(
        self,
        session: AsyncSession,
        *,
        decision_id: UUID,
        applied_by: str,
        reason: str,
    ) -> ResolutionApplicationResult:
        application = IdentityResolutionApplication(
            decision_id=decision_id,
            state=ResolutionApplicationState.QUARANTINED.value,
            quarantine_reason=reason,
            applied_by=applied_by,
            applied_at=_utc_now(),
        )
        session.add(application)
        await session.flush()
        return ResolutionApplicationResult(
            application_id=application.identity_resolution_application_id,
            state=ResolutionApplicationState.QUARANTINED,
            fighter_alias_ids=(),
            quarantine_reason=reason,
        )


def _candidate_evidence(candidate: object) -> dict[str, str]:
    """Serialize only the retained source alias and raw-object lineage evidence."""

    from ufc_predictor.identity.normalize import FighterAliasCandidate

    if not isinstance(candidate, FighterAliasCandidate):
        raise TypeError("review evidence must contain a fighter alias candidate")
    return {
        "source_identifier": candidate.source_identifier,
        "source_record_key": candidate.source_record_key,
        "source_raw_sha256": candidate.source_raw_sha256,
        "source_field": candidate.source_field,
        "original_alias": candidate.alias.original_value,
        "normalized_alias": candidate.alias.normalized_value,
    }


def _decision_alias_evidence(
    evidence: Mapping[str, object],
) -> set[tuple[str, str, str, str, str, str]] | None:
    aliases: set[tuple[str, str, str, str, str, str]] = set()
    for key in ("first", "second"):
        value = evidence.get(key)
        if not isinstance(value, Mapping):
            return None
        source_identifier = value.get("source_identifier")
        raw_sha256 = value.get("source_raw_sha256")
        source_record_key = value.get("source_record_key")
        source_field = value.get("source_field")
        original_alias = value.get("original_alias")
        normalized_alias = value.get("normalized_alias")
        if not (
            isinstance(source_identifier, str)
            and source_identifier
            and isinstance(raw_sha256, str)
            and raw_sha256
            and isinstance(source_record_key, str)
            and source_record_key
            and isinstance(source_field, str)
            and source_field
            and isinstance(original_alias, str)
            and original_alias
            and isinstance(normalized_alias, str)
            and normalized_alias
        ):
            return None
        aliases.add(
            (
                source_identifier,
                raw_sha256,
                source_record_key,
                source_field,
                original_alias,
                normalized_alias,
            )
        )
    return aliases if len(aliases) == 2 else None


def _application_result(application: IdentityResolutionApplication) -> ResolutionApplicationResult:
    """Return a stored terminal outcome without reapplying its decision."""

    return ResolutionApplicationResult(
        application_id=application.identity_resolution_application_id,
        state=ResolutionApplicationState(application.state),
        fighter_alias_ids=(),
        quarantine_reason=application.quarantine_reason,
    )


def _merge_quarantine_result(
    application: ResolutionApplicationResult,
) -> ReviewedFighterMergeResult:
    """Adapt a stored quarantined application to the merge-specific result contract."""

    return ReviewedFighterMergeResult(
        application_id=application.application_id,
        state=application.state,
        fighter_identity_merge_id=None,
        quarantine_reason=application.quarantine_reason,
    )


def _split_quarantine_result(
    application: ResolutionApplicationResult,
) -> ReviewedFighterSplitResult:
    """Adapt a stored quarantined application to the split-specific result contract."""

    return ReviewedFighterSplitResult(
        application_id=application.application_id,
        state=application.state,
        fighter_identity_split_id=None,
        quarantine_reason=application.quarantine_reason,
    )


def _alias_records_prior_decision(alias: FighterAlias, decision_id: UUID) -> bool:
    """Confirm that an old alias came from the decision a correction supersedes."""

    evidence = alias.evidence
    if not isinstance(evidence, Mapping):
        return False
    return evidence.get("identity_resolution_decision_id") == str(decision_id)


def _utc_now() -> datetime:
    return datetime.now(UTC)
