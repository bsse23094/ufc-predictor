"""Canonical-fighter and identity-review persistence owned by the fighters domain."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from ufc_api.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Fighter(Base):
    """A canonical fighter record that is not created by candidate scoring."""

    __tablename__ = "fighters"
    __table_args__ = (
        CheckConstraint("char_length(btrim(display_name)) > 0", name="display_name_nonblank"),
        CheckConstraint("char_length(btrim(identity_status)) > 0", name="identity_status_nonblank"),
        CheckConstraint("row_version >= 1", name="row_version_positive"),
        CheckConstraint(
            "merged_into_fighter_id IS NULL OR merged_into_fighter_id <> fighter_id",
            name="merge_target_differs_from_self",
        ),
        Index("ix_fighters_identity_status", "identity_status"),
    )

    fighter_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    identity_status: Mapped[str] = mapped_column(
        String(64), nullable=False, default="pending_review", server_default="pending_review"
    )
    merged_into_fighter_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("fighters.fighter_id")
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
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


class FighterAlias(Base):
    """A reviewed source alias for a canonical fighter, always raw-traceable."""

    __tablename__ = "fighter_aliases"
    __table_args__ = (
        CheckConstraint("char_length(btrim(alias_type)) > 0", name="alias_type_nonblank"),
        CheckConstraint("char_length(btrim(alias_value)) > 0", name="alias_value_nonblank"),
        CheckConstraint(
            "char_length(btrim(normalized_value)) > 0", name="normalized_value_nonblank"
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_in_range",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name="valid_interval_ordered",
        ),
        Index("ix_fighter_aliases_fighter_id", "fighter_id"),
        Index("ix_fighter_aliases_source_normalized", "source_id", "normalized_value"),
        Index("ix_fighter_aliases_resolution_status", "resolution_status"),
        Index(
            "uq_fighter_aliases_source_external",
            "source_id",
            "alias_type",
            "provider_external_id",
            unique=True,
            postgresql_where=text("provider_external_id IS NOT NULL"),
        ),
    )

    fighter_alias_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    fighter_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("fighters.fighter_id"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("data_sources.source_id"), nullable=False
    )
    raw_object_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("raw_objects.raw_object_id"), nullable=False
    )
    alias_type: Mapped[str] = mapped_column(String(64), nullable=False)
    alias_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    provider_external_id: Mapped[str | None] = mapped_column(String(256))
    resolution_status: Mapped[str] = mapped_column(
        String(64), nullable=False, default="reviewed", server_default="reviewed"
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    evidence: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )
    system_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )
    system_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FighterAliasSupersession(Base):
    """Append-only bitemporal correction link between reviewed source aliases."""

    __tablename__ = "fighter_alias_supersessions"
    __table_args__ = (
        CheckConstraint("superseded_alias_id <> replacement_alias_id", name="aliases_must_differ"),
        Index(
            "ix_fighter_alias_supersessions_application_id", "identity_resolution_application_id"
        ),
    )

    fighter_alias_supersession_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    identity_resolution_application_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("identity_resolution_applications.identity_resolution_application_id"),
        nullable=False,
    )
    superseded_alias_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("fighter_aliases.fighter_alias_id"),
        nullable=False,
        unique=True,
    )
    replacement_alias_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("fighter_aliases.fighter_alias_id"),
        nullable=False,
        unique=True,
    )
    superseded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applied_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )


class FighterIdentityMerge(Base):
    """Append-only record that one reviewed fighter identity now resolves to another."""

    __tablename__ = "fighter_identity_merges"
    __table_args__ = (
        CheckConstraint(
            "canonical_fighter_id <> merged_fighter_id", name="merge_fighters_must_differ"
        ),
        Index("ix_fighter_identity_merges_canonical", "canonical_fighter_id"),
        Index("ix_fighter_identity_merges_merged", "merged_fighter_id"),
    )

    fighter_identity_merge_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    identity_resolution_application_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("identity_resolution_applications.identity_resolution_application_id"),
        nullable=False,
        unique=True,
    )
    canonical_fighter_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("fighters.fighter_id"), nullable=False
    )
    merged_fighter_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("fighters.fighter_id"), nullable=False
    )
    merged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applied_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )


class FighterIdentitySplit(Base):
    """Append-only record restoring one specifically merged fighter identity."""

    __tablename__ = "fighter_identity_splits"
    __table_args__ = (
        CheckConstraint(
            "canonical_fighter_id <> restored_fighter_id", name="split_fighters_must_differ"
        ),
        Index("ix_fighter_identity_splits_canonical", "canonical_fighter_id"),
        Index("ix_fighter_identity_splits_restored", "restored_fighter_id"),
    )

    fighter_identity_split_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    identity_resolution_application_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("identity_resolution_applications.identity_resolution_application_id"),
        nullable=False,
        unique=True,
    )
    fighter_identity_merge_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("fighter_identity_merges.fighter_identity_merge_id"),
        nullable=False,
        unique=True,
    )
    canonical_fighter_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("fighters.fighter_id"), nullable=False
    )
    restored_fighter_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("fighters.fighter_id"), nullable=False
    )
    split_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applied_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )


class IdentityResolutionDecision(Base):
    """Append-only human review evidence; a resolver owns any later application."""

    __tablename__ = "identity_resolution_decisions"
    __table_args__ = (
        CheckConstraint("char_length(btrim(review_key)) = 64", name="review_key_sha256"),
        CheckConstraint("char_length(btrim(entity_type)) > 0", name="entity_type_nonblank"),
        CheckConstraint("char_length(btrim(decision_type)) > 0", name="decision_type_nonblank"),
        CheckConstraint("char_length(btrim(actor)) > 0", name="actor_nonblank"),
        CheckConstraint("char_length(btrim(rationale)) > 0", name="rationale_nonblank"),
        Index("ix_identity_resolution_decisions_review_key", "review_key"),
        Index("ix_identity_resolution_decisions_proposed_fighter_id", "proposed_fighter_id"),
        Index("ix_identity_resolution_decisions_resolved_fighter_id", "resolved_fighter_id"),
    )

    identity_resolution_decision_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    review_key: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(64), nullable=False)
    proposed_fighter_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("fighters.fighter_id")
    )
    resolved_fighter_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("fighters.fighter_id")
    )
    supersedes_decision_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("identity_resolution_decisions.identity_resolution_decision_id"),
    )
    evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    actor: Mapped[str] = mapped_column(String(256), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )


class IdentityResolutionApplication(Base):
    """Append-only outcome of applying one explicit review decision, if permitted."""

    __tablename__ = "identity_resolution_applications"
    __table_args__ = (
        CheckConstraint(
            "state IN ('applied', 'quarantined')", name="state_is_terminal_resolution_outcome"
        ),
        CheckConstraint(
            "(state = 'applied' AND canonical_fighter_id IS NOT NULL "
            "AND quarantine_reason IS NULL) OR "
            "(state = 'quarantined' AND canonical_fighter_id IS NULL "
            "AND quarantine_reason IS NOT NULL)",
            name="state_matches_resolution_outcome",
        ),
        Index("ix_identity_resolution_applications_state", "state"),
    )

    identity_resolution_application_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    decision_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("identity_resolution_decisions.identity_resolution_decision_id"),
        nullable=False,
        unique=True,
    )
    canonical_fighter_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("fighters.fighter_id")
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    quarantine_reason: Mapped[str | None] = mapped_column(Text)
    applied_by: Mapped[str] = mapped_column(String(256), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )
