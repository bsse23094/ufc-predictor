"""Create relational canonical event, fight, participant, and result facts.

Revision ID: 0009_canonical_bout_catalog
Revises: 0008_identity_merge_split
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_canonical_bout_catalog"
down_revision: str | Sequence[str] | None = "0008_identity_merge_split"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the M3 relational catalog without inventing unavailable event data."""
    op.create_table(
        "promotions",
        sa.Column(
            "promotion_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("canonical_name_key", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("promotion_id", name="pk_promotions"),
        sa.UniqueConstraint("canonical_name_key", name="uq_promotions_canonical_name_key"),
    )
    op.create_table(
        "divisions",
        sa.Column(
            "division_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("canonical_code", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("division_id", name="pk_divisions"),
        sa.UniqueConstraint("canonical_code", name="uq_divisions_canonical_code"),
    )
    op.create_table(
        "events",
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("promotion_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("canonical_name", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("country", sa.String(length=128), nullable=True),
        sa.Column("latest_schedule_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("char_length(btrim(status)) > 0", name="status_nonblank"),
        sa.ForeignKeyConstraint(
            ["promotion_id"], ["promotions.promotion_id"], name="fk_events_promotion_id_promotions"
        ),
        sa.PrimaryKeyConstraint("event_id", name="pk_events"),
    )
    op.create_index("ix_events_scheduled_start_at", "events", ["scheduled_start_at"])
    op.create_index(
        "ix_events_promotion_scheduled_start", "events", ["promotion_id", "scheduled_start_at"]
    )
    op.create_index("ix_events_status", "events", ["status"])
    op.create_table(
        "event_source_references",
        sa.Column(
            "event_source_reference_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_schema_version", sa.String(length=256), nullable=False),
        sa.Column("source_external_key", sa.String(length=512), nullable=False),
        sa.Column("source_record_key", sa.String(length=512), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_to", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.event_id"], name="fk_event_source_references_event_id_events"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.source_id"],
            name="fk_event_source_references_source_id_data_sources",
        ),
        sa.ForeignKeyConstraint(
            ["raw_object_id"],
            ["raw_objects.raw_object_id"],
            name="fk_event_source_references_raw_object_id_raw_objects",
        ),
        sa.PrimaryKeyConstraint("event_source_reference_id", name="pk_event_source_references"),
        sa.UniqueConstraint(
            "source_id",
            "source_external_key",
            name="uq_event_source_references_source_external_key",
        ),
    )
    op.create_index("ix_event_source_references_event_id", "event_source_references", ["event_id"])
    op.create_table(
        "fights",
        sa.Column(
            "fight_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column(
            "publication_state", sa.String(length=32), nullable=False, server_default="staged"
        ),
        sa.Column("event_context_status", sa.String(length=32), nullable=False),
        sa.Column("division_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scheduled_order", sa.Integer(), nullable=True),
        sa.Column("scheduled_rounds", sa.Integer(), nullable=False),
        sa.Column("round_length_seconds", sa.Integer(), nullable=True),
        sa.Column("fight_date", sa.Date(), nullable=True),
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ruleset_version", sa.String(length=128), nullable=True),
        sa.Column("title_bout", sa.Boolean(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("country", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("char_length(btrim(status)) > 0", name="status_nonblank"),
        sa.CheckConstraint(
            "publication_state IN ('staged', 'published')", name="publication_state_allowed"
        ),
        sa.CheckConstraint(
            "event_context_status IN ('not_observed', 'resolved')",
            name="event_context_status_allowed",
        ),
        sa.CheckConstraint(
            "(event_id IS NULL AND event_context_status = 'not_observed') OR "
            "(event_id IS NOT NULL AND event_context_status = 'resolved')",
            name="event_context_matches_event_id",
        ),
        sa.CheckConstraint("scheduled_rounds > 0", name="scheduled_rounds_positive"),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.event_id"], name="fk_fights_event_id_events"
        ),
        sa.ForeignKeyConstraint(
            ["division_id"], ["divisions.division_id"], name="fk_fights_division_id_divisions"
        ),
        sa.PrimaryKeyConstraint("fight_id", name="pk_fights"),
    )
    op.create_index("ix_fights_event_id", "fights", ["event_id"])
    op.create_index("ix_fights_fight_date", "fights", ["fight_date"])
    op.create_index("ix_fights_status_division", "fights", ["status", "division_id"])
    op.create_table(
        "fight_source_references",
        sa.Column(
            "fight_source_reference_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("fight_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_schema_version", sa.String(length=256), nullable=False),
        sa.Column("source_record_key", sa.String(length=512), nullable=False),
        sa.Column("canonical_source_fight_key", sa.String(length=1024), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("taxonomy_version", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["fight_id"], ["fights.fight_id"], name="fk_fight_source_references_fight_id_fights"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.source_id"],
            name="fk_fight_source_references_source_id_data_sources",
        ),
        sa.ForeignKeyConstraint(
            ["raw_object_id"],
            ["raw_objects.raw_object_id"],
            name="fk_fight_source_references_raw_object_id_raw_objects",
        ),
        sa.PrimaryKeyConstraint("fight_source_reference_id", name="pk_fight_source_references"),
        sa.UniqueConstraint(
            "source_id",
            "raw_object_id",
            "source_record_key",
            name="uq_fight_source_references_source_raw_record_key",
        ),
        sa.UniqueConstraint(
            "source_id",
            "canonical_source_fight_key",
            name="uq_fight_source_references_source_canonical_fight_key",
        ),
    )
    op.create_index("ix_fight_source_references_fight_id", "fight_source_references", ["fight_id"])
    op.create_table(
        "fight_participants",
        sa.Column(
            "fight_participant_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("fight_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fighter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_slot", sa.SmallInteger(), nullable=False),
        sa.Column("source_corner", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("canonical_slot IN (0, 1)", name="canonical_slot_allowed"),
        sa.ForeignKeyConstraint(
            ["fight_id"], ["fights.fight_id"], name="fk_fight_participants_fight_id_fights"
        ),
        sa.ForeignKeyConstraint(
            ["fighter_id"],
            ["fighters.fighter_id"],
            name="fk_fight_participants_fighter_id_fighters",
        ),
        sa.PrimaryKeyConstraint("fight_participant_id", name="pk_fight_participants"),
        sa.UniqueConstraint("fight_id", "fighter_id", name="uq_fight_participants_fight_fighter"),
        sa.UniqueConstraint(
            "fight_id", "canonical_slot", name="uq_fight_participants_fight_canonical_slot"
        ),
        sa.UniqueConstraint(
            "fight_id", "fight_participant_id", name="uq_fight_participants_fight_participant_pair"
        ),
    )
    op.create_index("ix_fight_participants_fighter_id", "fight_participants", ["fighter_id"])
    op.create_table(
        "fight_participant_identity_evidence",
        sa.Column(
            "fight_participant_identity_evidence_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("fight_participant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("identity_resolution_decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["fight_participant_id"],
            ["fight_participants.fight_participant_id"],
            name="fk_fp_identity_evidence_participant",
        ),
        sa.ForeignKeyConstraint(
            ["identity_resolution_decision_id"],
            ["identity_resolution_decisions.identity_resolution_decision_id"],
            name="fk_fp_identity_evidence_decision",
        ),
        sa.PrimaryKeyConstraint(
            "fight_participant_identity_evidence_id", name="pk_fight_participant_identity_evidence"
        ),
        sa.UniqueConstraint(
            "fight_participant_id",
            "identity_resolution_decision_id",
            name="uq_fight_participant_identity_evidence_participant_decision",
        ),
    )
    op.create_table(
        "fight_results",
        sa.Column(
            "fight_result_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("fight_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fight_source_reference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("winner_participant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("outcome_type", sa.String(length=64), nullable=False),
        sa.Column("canonical_method_code", sa.String(length=128), nullable=False),
        sa.Column("source_outcome_label", sa.Text(), nullable=False),
        sa.Column("source_method_label", sa.Text(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("taxonomy_version", sa.String(length=128), nullable=False),
        sa.Column("quality_state", sa.String(length=64), nullable=False, server_default="mapped"),
        sa.CheckConstraint(
            "(outcome_type = 'decisive' AND winner_participant_id IS NOT NULL) OR "
            "(outcome_type IN ('draw', 'no_contest') AND winner_participant_id IS NULL)",
            name="outcome_winner_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["fight_id"], ["fights.fight_id"], name="fk_fight_results_fight_id_fights"
        ),
        sa.ForeignKeyConstraint(
            ["fight_source_reference_id"],
            ["fight_source_references.fight_source_reference_id"],
            name="fk_fight_results_source_reference_id_fight_source_references",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.source_id"],
            name="fk_fight_results_source_id_data_sources",
        ),
        sa.ForeignKeyConstraint(
            ["raw_object_id"],
            ["raw_objects.raw_object_id"],
            name="fk_fight_results_raw_object_id_raw_objects",
        ),
        sa.ForeignKeyConstraint(
            ["fight_id", "winner_participant_id"],
            ["fight_participants.fight_id", "fight_participants.fight_participant_id"],
            name="fk_fight_results_winner_participant_belongs_to_fight",
        ),
        sa.PrimaryKeyConstraint("fight_result_id", name="pk_fight_results"),
        sa.UniqueConstraint("fight_source_reference_id", name="uq_fight_results_source_reference"),
    )
    op.create_index("ix_fight_results_fight_id", "fight_results", ["fight_id"])
    op.execute(
        """
        CREATE FUNCTION validate_fight_participant_identity_evidence()
        RETURNS trigger AS $$
        BEGIN
            PERFORM 1
            FROM fight_participants AS participant
            JOIN identity_resolution_applications AS application
                ON application.decision_id = NEW.identity_resolution_decision_id
            WHERE participant.fight_participant_id = NEW.fight_participant_id
                AND application.state = 'applied'
                AND application.canonical_fighter_id = participant.fighter_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'participant identity evidence requires an applied matching decision';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_fight_participant_identity_evidence_applied
        BEFORE INSERT OR UPDATE ON fight_participant_identity_evidence
        FOR EACH ROW EXECUTE FUNCTION validate_fight_participant_identity_evidence()
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_published_canonical_fight()
        RETURNS trigger AS $$
        DECLARE
            target_fight_id UUID;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                target_fight_id := OLD.fight_id;
            ELSE
                target_fight_id := NEW.fight_id;
            END IF;
            IF EXISTS (
                SELECT 1 FROM fights
                WHERE fight_id = target_fight_id AND publication_state = 'published'
            ) THEN
                IF (
                    SELECT count(*) FROM fight_participants WHERE fight_id = target_fight_id
                ) <> 2 THEN
                    RAISE EXCEPTION
                        'a published canonical fight requires exactly two participants';
                END IF;
                IF (
                    SELECT count(*) FROM fight_results
                    WHERE fight_id = target_fight_id AND system_to IS NULL
                ) <> 1 THEN
                    RAISE EXCEPTION
                        'a published canonical fight requires exactly one current result';
                END IF;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_fights_validate_published
        AFTER INSERT OR UPDATE OF publication_state ON fights
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_published_canonical_fight()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_fight_participants_validate_published
        AFTER INSERT OR UPDATE OR DELETE ON fight_participants
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_published_canonical_fight()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_fight_results_validate_published
        AFTER INSERT OR UPDATE OR DELETE ON fight_results
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_published_canonical_fight()
        """
    )


def downgrade() -> None:
    """Remove the isolated relational M3 catalog boundary in dependency order."""
    op.execute("DROP TRIGGER trg_fight_results_validate_published ON fight_results")
    op.execute("DROP TRIGGER trg_fight_participants_validate_published ON fight_participants")
    op.execute("DROP TRIGGER trg_fights_validate_published ON fights")
    op.execute("DROP FUNCTION validate_published_canonical_fight()")
    op.execute(
        "DROP TRIGGER trg_fight_participant_identity_evidence_applied "
        "ON fight_participant_identity_evidence"
    )
    op.execute("DROP FUNCTION validate_fight_participant_identity_evidence()")
    op.drop_index("ix_fight_results_fight_id", table_name="fight_results")
    op.drop_table("fight_results")
    op.drop_table("fight_participant_identity_evidence")
    op.drop_index("ix_fight_participants_fighter_id", table_name="fight_participants")
    op.drop_table("fight_participants")
    op.drop_index("ix_fight_source_references_fight_id", table_name="fight_source_references")
    op.drop_table("fight_source_references")
    op.drop_index("ix_fights_status_division", table_name="fights")
    op.drop_index("ix_fights_fight_date", table_name="fights")
    op.drop_index("ix_fights_event_id", table_name="fights")
    op.drop_table("fights")
    op.drop_index("ix_event_source_references_event_id", table_name="event_source_references")
    op.drop_table("event_source_references")
    op.drop_index("ix_events_status", table_name="events")
    op.drop_index("ix_events_promotion_scheduled_start", table_name="events")
    op.drop_index("ix_events_scheduled_start_at", table_name="events")
    op.drop_table("events")
    op.drop_table("divisions")
    op.drop_table("promotions")
