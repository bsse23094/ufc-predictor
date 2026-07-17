"""Relational canonical event, bout, participant, and result facts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ufc_api.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Promotion(Base):
    """A reviewed promotion catalog record; sources may omit it."""

    __tablename__ = "promotions"

    promotion_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_name_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
        server_default=func.now(),
    )


class Division(Base):
    """A code from a reviewed source-label taxonomy, never a parser default."""

    __tablename__ = "divisions"

    division_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    canonical_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )


class Event(Base):
    """An event only when a source or review supplies event-level facts."""

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("char_length(btrim(status)) > 0", name="status_nonblank"),
        Index("ix_events_scheduled_start_at", "scheduled_start_at"),
        Index("ix_events_promotion_scheduled_start", "promotion_id", "scheduled_start_at"),
        Index("ix_events_status", "status"),
    )

    event_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    promotion_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("promotions.promotion_id")
    )
    canonical_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduled_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(String(128))
    latest_schedule_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
        server_default=func.now(),
    )


class EventSourceReference(Base):
    """Immutable source/raw evidence for an event-level external identifier."""

    __tablename__ = "event_source_references"
    __table_args__ = (
        UniqueConstraint("source_id", "source_external_key", name="source_external_key"),
        Index("ix_event_source_references_event_id", "event_id"),
    )

    event_source_reference_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    event_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("events.event_id"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("data_sources.source_id"), nullable=False
    )
    raw_object_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("raw_objects.raw_object_id"), nullable=False
    )
    source_schema_version: Mapped[str] = mapped_column(String(256), nullable=False)
    source_external_key: Mapped[str] = mapped_column(String(512), nullable=False)
    source_record_key: Mapped[str | None] = mapped_column(String(512))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    system_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    system_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Fight(Base):
    """A canonical fight whose source may lack an event-level identifier."""

    __tablename__ = "fights"
    __table_args__ = (
        CheckConstraint("char_length(btrim(status)) > 0", name="status_nonblank"),
        CheckConstraint(
            "publication_state IN ('staged', 'published')", name="publication_state_allowed"
        ),
        CheckConstraint(
            "event_context_status IN ('not_observed', 'resolved')",
            name="event_context_status_allowed",
        ),
        CheckConstraint(
            "(event_id IS NULL AND event_context_status = 'not_observed') OR "
            "(event_id IS NOT NULL AND event_context_status = 'resolved')",
            name="event_context_matches_event_id",
        ),
        CheckConstraint("scheduled_rounds > 0", name="scheduled_rounds_positive"),
        Index("ix_fights_event_id", "event_id"),
        Index("ix_fights_fight_date", "fight_date"),
        Index("ix_fights_status_division", "status", "division_id"),
    )

    fight_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    event_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("events.event_id")
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    publication_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="staged", server_default="staged"
    )
    event_context_status: Mapped[str] = mapped_column(String(32), nullable=False)
    division_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("divisions.division_id"), nullable=False
    )
    scheduled_order: Mapped[int | None] = mapped_column(Integer)
    scheduled_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    round_length_seconds: Mapped[int | None] = mapped_column(Integer)
    fight_date: Mapped[date | None] = mapped_column(Date)
    scheduled_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ruleset_version: Mapped[str | None] = mapped_column(String(128))
    title_bout: Mapped[bool | None] = mapped_column()
    location: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
        server_default=func.now(),
    )


class FightSourceReference(Base):
    """Immutable source/raw reference for one source-shaped canonical fight fact."""

    __tablename__ = "fight_source_references"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "raw_object_id", "source_record_key", name="source_raw_record_key"
        ),
        UniqueConstraint(
            "source_id", "canonical_source_fight_key", name="source_canonical_fight_key"
        ),
        Index("ix_fight_source_references_fight_id", "fight_id"),
    )

    fight_source_reference_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    fight_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("fights.fight_id"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("data_sources.source_id"), nullable=False
    )
    raw_object_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("raw_objects.raw_object_id"), nullable=False
    )
    source_schema_version: Mapped[str] = mapped_column(String(256), nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(512), nullable=False)
    canonical_source_fight_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )


class FightParticipant(Base):
    """Outcome-independent canonical participant slot for one canonical fight."""

    __tablename__ = "fight_participants"
    __table_args__ = (
        CheckConstraint("canonical_slot IN (0, 1)", name="canonical_slot_allowed"),
        UniqueConstraint("fight_id", "fighter_id", name="fight_fighter"),
        UniqueConstraint("fight_id", "canonical_slot", name="fight_canonical_slot"),
        UniqueConstraint("fight_id", "fight_participant_id", name="fight_participant_pair"),
        Index("ix_fight_participants_fighter_id", "fighter_id"),
    )

    fight_participant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    fight_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("fights.fight_id"), nullable=False
    )
    fighter_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("fighters.fighter_id"), nullable=False
    )
    canonical_slot: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source_corner: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )


class FightParticipantIdentityEvidence(Base):
    """Applied identity decision that justifies one participant in one source fact."""

    __tablename__ = "fight_participant_identity_evidence"
    __table_args__ = (
        UniqueConstraint(
            "fight_participant_id", "identity_resolution_decision_id", name="participant_decision"
        ),
    )

    fight_participant_identity_evidence_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    fight_participant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("fight_participants.fight_participant_id"),
        nullable=False,
    )
    identity_resolution_decision_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("identity_resolution_decisions.identity_resolution_decision_id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )


class FightResult(Base):
    """Append-only mapped result fact, isolated from future feature inputs."""

    __tablename__ = "fight_results"
    __table_args__ = (
        CheckConstraint(
            "(outcome_type = 'decisive' AND winner_participant_id IS NOT NULL) OR "
            "(outcome_type IN ('draw', 'no_contest') AND winner_participant_id IS NULL)",
            name="outcome_winner_consistent",
        ),
        UniqueConstraint("fight_source_reference_id", name="source_reference"),
        ForeignKeyConstraint(
            ["fight_id", "winner_participant_id"],
            ["fight_participants.fight_id", "fight_participants.fight_participant_id"],
            name="winner_participant_belongs_to_fight",
        ),
        Index("ix_fight_results_fight_id", "fight_id"),
    )

    fight_result_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    fight_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("fights.fight_id"), nullable=False
    )
    fight_source_reference_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("fight_source_references.fight_source_reference_id"),
        nullable=False,
    )
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("data_sources.source_id"), nullable=False
    )
    raw_object_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("raw_objects.raw_object_id"), nullable=False
    )
    winner_participant_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    outcome_type: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_method_code: Mapped[str] = mapped_column(String(128), nullable=False)
    source_outcome_label: Mapped[str] = mapped_column(Text, nullable=False)
    source_method_label: Mapped[str] = mapped_column(Text, nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    system_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    system_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    taxonomy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    quality_state: Mapped[str] = mapped_column(String(64), nullable=False, default="mapped")
