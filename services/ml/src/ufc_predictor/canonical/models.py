"""Typed, provenance-complete canonical bout observations.

These are canonical-source facts, not feature rows.  In particular, their
outcome/method fields remain separated from future pre-fight feature inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from ufc_predictor.canonical.taxonomy import CanonicalOutcomeType, ObservedLabel
from ufc_predictor.ingestion.base import RawReference


@dataclass(frozen=True, slots=True)
class ReviewedCanonicalAlias:
    """An exact source occurrence already linked to one canonical fighter by review."""

    source_identifier: str
    source_schema_version: str
    raw_sha256: str
    source_record_key: str
    source_field: str
    alias_value: str
    fighter_id: UUID
    identity_resolution_decision_id: UUID

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.source_identifier,
                self.source_schema_version,
                self.source_record_key,
                self.source_field,
                self.alias_value,
            )
        ):
            raise ValueError("reviewed alias requires complete source evidence")
        if len(self.raw_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.raw_sha256
        ):
            raise ValueError("reviewed alias requires a lowercase raw SHA-256")


@dataclass(frozen=True, slots=True)
class CanonicalFightObservation:
    """One mapped historical bout, retaining source facts and raw lineage."""

    canonical_source_fight_key: str
    source_identifier: str
    source_schema_version: str
    source_record_key: str
    raw_reference: RawReference
    fighter_one_id: UUID
    fighter_two_id: UUID
    fight_date: date
    scheduled_rounds: int
    canonical_division_code: str
    source_division_label: str
    location: str | None
    country: str | None
    title_bout: bool | None
    outcome_type: CanonicalOutcomeType
    winner_fighter_id: UUID | None
    source_outcome_label: str
    canonical_method_code: str
    source_method_label: str
    ingested_at: datetime
    identity_resolution_decision_ids: tuple[UUID, UUID]
    taxonomy_version: str

    def __post_init__(self) -> None:
        if not self.canonical_source_fight_key or not self.source_record_key:
            raise ValueError("canonical source fight key and source record key are required")
        if self.fighter_one_id == self.fighter_two_id:
            raise ValueError("a canonical fight requires two distinct fighters")
        if self.scheduled_rounds < 1:
            raise ValueError("scheduled_rounds must be positive")
        if not all(
            value.strip()
            for value in (
                self.canonical_division_code,
                self.source_division_label,
                self.source_outcome_label,
                self.canonical_method_code,
                self.source_method_label,
                self.taxonomy_version,
            )
        ):
            raise ValueError("canonical observation has incomplete taxonomy fields")
        if self.ingested_at.tzinfo is None or self.ingested_at.utcoffset() is None:
            raise ValueError("ingested_at must be timezone-aware")
        if self.outcome_type is CanonicalOutcomeType.DECISIVE:
            if self.winner_fighter_id not in {self.fighter_one_id, self.fighter_two_id}:
                raise ValueError("a decisive result must name one fight participant as winner")
        elif self.winner_fighter_id is not None:
            raise ValueError("a draw or no contest must not name a winner")


@dataclass(frozen=True, slots=True)
class CanonicalMappingIssue:
    """An auditable quarantine reason for one source-shaped record."""

    rule_id: str
    source_record_key: str
    raw_sha256: str
    summary: str


@dataclass(frozen=True, slots=True)
class CanonicalMappingResult:
    """Complete accounting for records entering the canonical mapping boundary."""

    accepted: tuple[CanonicalFightObservation, ...]
    quarantined_record_keys: tuple[str, ...]
    issues: tuple[CanonicalMappingIssue, ...]
    observed_labels: tuple[ObservedLabel, ...]

    def __post_init__(self) -> None:
        if len(self.quarantined_record_keys) != len(set(self.quarantined_record_keys)):
            raise ValueError("canonical mapping quarantine keys must be unique")
        accepted_keys = {record.source_record_key for record in self.accepted}
        quarantined_keys = set(self.quarantined_record_keys)
        if accepted_keys & quarantined_keys:
            raise ValueError("a source record cannot be both accepted and quarantined")
        issue_keys = {issue.source_record_key for issue in self.issues}
        if issue_keys != quarantined_keys:
            raise ValueError("each canonical mapping quarantine requires an issue")

    @property
    def input_count(self) -> int:
        """Return accounted source rows at this boundary."""

        return len(self.accepted) + len(self.quarantined_record_keys)
