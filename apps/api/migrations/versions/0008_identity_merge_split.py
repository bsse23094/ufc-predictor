"""Add audited, guarded canonical fighter merge and split operations.

Revision ID: 0008_identity_merge_split
Revises: 0007_alias_supersession
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_identity_merge_split"
down_revision: str | Sequence[str] | None = "0007_alias_supersession"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Retain reviewed canonical transitions and reject un-audited alias mutation."""

    op.create_table(
        "fighter_identity_merges",
        sa.Column(
            "fighter_identity_merge_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "identity_resolution_application_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("canonical_fighter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merged_fighter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_by", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "canonical_fighter_id <> merged_fighter_id", name="merge_fighters_must_differ"
        ),
        sa.ForeignKeyConstraint(
            ["identity_resolution_application_id"],
            ["identity_resolution_applications.identity_resolution_application_id"],
            name="fk_fighter_identity_merges_application",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_fighter_id"],
            ["fighters.fighter_id"],
            name="fk_fighter_identity_merges_canonical",
        ),
        sa.ForeignKeyConstraint(
            ["merged_fighter_id"],
            ["fighters.fighter_id"],
            name="fk_fighter_identity_merges_merged",
        ),
        sa.PrimaryKeyConstraint("fighter_identity_merge_id", name="pk_fighter_identity_merges"),
        sa.UniqueConstraint(
            "identity_resolution_application_id",
            name="uq_fighter_identity_merges_identity_resolution_application_id",
        ),
    )
    op.create_index(
        "ix_fighter_identity_merges_canonical",
        "fighter_identity_merges",
        ["canonical_fighter_id"],
    )
    op.create_index(
        "ix_fighter_identity_merges_merged",
        "fighter_identity_merges",
        ["merged_fighter_id"],
    )
    op.create_table(
        "fighter_identity_splits",
        sa.Column(
            "fighter_identity_split_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "identity_resolution_application_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("fighter_identity_merge_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_fighter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restored_fighter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("split_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_by", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "canonical_fighter_id <> restored_fighter_id", name="split_fighters_must_differ"
        ),
        sa.ForeignKeyConstraint(
            ["identity_resolution_application_id"],
            ["identity_resolution_applications.identity_resolution_application_id"],
            name="fk_fighter_identity_splits_application",
        ),
        sa.ForeignKeyConstraint(
            ["fighter_identity_merge_id"],
            ["fighter_identity_merges.fighter_identity_merge_id"],
            name="fk_fighter_identity_splits_merge",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_fighter_id"],
            ["fighters.fighter_id"],
            name="fk_fighter_identity_splits_canonical",
        ),
        sa.ForeignKeyConstraint(
            ["restored_fighter_id"],
            ["fighters.fighter_id"],
            name="fk_fighter_identity_splits_restored",
        ),
        sa.PrimaryKeyConstraint("fighter_identity_split_id", name="pk_fighter_identity_splits"),
        sa.UniqueConstraint(
            "identity_resolution_application_id",
            name="uq_fighter_identity_splits_identity_resolution_application_id",
        ),
        sa.UniqueConstraint(
            "fighter_identity_merge_id", name="uq_fighter_identity_splits_fighter_identity_merge_id"
        ),
    )
    op.create_index(
        "ix_fighter_identity_splits_canonical",
        "fighter_identity_splits",
        ["canonical_fighter_id"],
    )
    op.create_index(
        "ix_fighter_identity_splits_restored",
        "fighter_identity_splits",
        ["restored_fighter_id"],
    )
    op.execute(
        """
        CREATE FUNCTION prevent_fighter_alias_identity_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'fighter aliases are append-only; close and supersede them instead';
            END IF;
            IF NEW.system_to IS NOT DISTINCT FROM OLD.system_to
                OR OLD.system_to IS NOT NULL
                OR NEW.system_to IS NULL
                OR NEW.fighter_id IS DISTINCT FROM OLD.fighter_id
                OR NEW.source_id IS DISTINCT FROM OLD.source_id
                OR NEW.raw_object_id IS DISTINCT FROM OLD.raw_object_id
                OR NEW.alias_type IS DISTINCT FROM OLD.alias_type
                OR NEW.alias_value IS DISTINCT FROM OLD.alias_value
                OR NEW.normalized_value IS DISTINCT FROM OLD.normalized_value
                OR NEW.provider_external_id IS DISTINCT FROM OLD.provider_external_id
                OR NEW.resolution_status IS DISTINCT FROM OLD.resolution_status
                OR NEW.confidence IS DISTINCT FROM OLD.confidence
                OR NEW.evidence IS DISTINCT FROM OLD.evidence
                OR NEW.valid_from IS DISTINCT FROM OLD.valid_from
                OR NEW.valid_to IS DISTINCT FROM OLD.valid_to
                OR NEW.observed_at IS DISTINCT FROM OLD.observed_at
                OR NEW.ingested_at IS DISTINCT FROM OLD.ingested_at
                OR NEW.system_from IS DISTINCT FROM OLD.system_from THEN
                RAISE EXCEPTION 'fighter aliases may only be closed for a reviewed supersession';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_fighter_aliases_guarded_closure
        BEFORE UPDATE OR DELETE ON fighter_aliases
        FOR EACH ROW EXECUTE FUNCTION prevent_fighter_alias_identity_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_fighter_merge_transition()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.merged_into_fighter_id IS NULL AND NEW.identity_status = 'merged' THEN
                RAISE EXCEPTION 'a merged fighter must retain a canonical merge target';
            END IF;
            IF TG_OP = 'INSERT' AND NEW.merged_into_fighter_id IS NOT NULL THEN
                RAISE EXCEPTION 'fighters must be merged through a reviewed merge application';
            END IF;
            IF TG_OP = 'UPDATE'
                AND NEW.merged_into_fighter_id IS DISTINCT FROM OLD.merged_into_fighter_id THEN
                IF NEW.merged_into_fighter_id IS NOT NULL THEN
                    IF OLD.merged_into_fighter_id IS NOT NULL
                        OR NEW.identity_status <> 'merged' THEN
                        RAISE EXCEPTION 'a merged fighter cannot be retargeted';
                    END IF;
                    PERFORM 1
                    FROM fighters AS target
                    WHERE target.fighter_id = NEW.merged_into_fighter_id
                        AND target.merged_into_fighter_id IS NULL;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'a merge target must be an active canonical fighter';
                    END IF;
                    PERFORM 1
                    FROM fighter_identity_merges AS merge_record
                    JOIN identity_resolution_applications AS application
                        ON application.identity_resolution_application_id
                            = merge_record.identity_resolution_application_id
                    WHERE merge_record.merged_fighter_id = NEW.fighter_id
                        AND merge_record.canonical_fighter_id = NEW.merged_into_fighter_id
                        AND application.state = 'applied'
                        AND application.canonical_fighter_id = NEW.merged_into_fighter_id
                        AND NOT EXISTS (
                            SELECT 1
                            FROM fighter_identity_splits AS split_record
                            WHERE split_record.fighter_identity_merge_id
                                = merge_record.fighter_identity_merge_id
                        );
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'merge transition requires applied audit record';
                    END IF;
                ELSE
                    IF OLD.merged_into_fighter_id IS NULL OR NEW.identity_status = 'merged' THEN
                        RAISE EXCEPTION 'a merged fighter can only be restored by a reviewed split';
                    END IF;
                    PERFORM 1
                    FROM fighter_identity_merges AS merge_record
                    JOIN fighter_identity_splits AS split_record
                        ON split_record.fighter_identity_merge_id
                            = merge_record.fighter_identity_merge_id
                    JOIN identity_resolution_applications AS application
                        ON application.identity_resolution_application_id
                            = split_record.identity_resolution_application_id
                    WHERE merge_record.merged_fighter_id = NEW.fighter_id
                        AND merge_record.canonical_fighter_id = OLD.merged_into_fighter_id
                        AND split_record.restored_fighter_id = NEW.fighter_id
                        AND split_record.canonical_fighter_id = OLD.merged_into_fighter_id
                        AND application.state = 'applied';
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'split transition requires applied audit record';
                    END IF;
                END IF;
            END IF;
            IF NEW.merged_into_fighter_id IS NOT NULL AND NEW.identity_status <> 'merged' THEN
                RAISE EXCEPTION 'a merged fighter must retain merged identity status';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_fighters_guard_merge_transition
        BEFORE INSERT OR UPDATE ON fighters
        FOR EACH ROW EXECUTE FUNCTION guard_fighter_merge_transition()
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_fighter_identity_merge_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'fighter identity merges are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_fighter_identity_merges_append_only
        BEFORE UPDATE OR DELETE ON fighter_identity_merges
        FOR EACH ROW EXECUTE FUNCTION prevent_fighter_identity_merge_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_fighter_identity_split_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'fighter identity splits are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_fighter_identity_splits_append_only
        BEFORE UPDATE OR DELETE ON fighter_identity_splits
        FOR EACH ROW EXECUTE FUNCTION prevent_fighter_identity_split_mutation()
        """
    )


def downgrade() -> None:
    """Remove the isolated reviewed-merge/split safeguards in dependency order."""

    op.execute("DROP TRIGGER trg_fighter_identity_splits_append_only ON fighter_identity_splits")
    op.execute("DROP FUNCTION prevent_fighter_identity_split_mutation()")
    op.execute("DROP TRIGGER trg_fighter_identity_merges_append_only ON fighter_identity_merges")
    op.execute("DROP FUNCTION prevent_fighter_identity_merge_mutation()")
    op.execute("DROP TRIGGER trg_fighters_guard_merge_transition ON fighters")
    op.execute("DROP FUNCTION guard_fighter_merge_transition()")
    op.execute("DROP TRIGGER trg_fighter_aliases_guarded_closure ON fighter_aliases")
    op.execute("DROP FUNCTION prevent_fighter_alias_identity_mutation()")
    op.drop_index("ix_fighter_identity_splits_restored", table_name="fighter_identity_splits")
    op.drop_index("ix_fighter_identity_splits_canonical", table_name="fighter_identity_splits")
    op.drop_table("fighter_identity_splits")
    op.drop_index("ix_fighter_identity_merges_merged", table_name="fighter_identity_merges")
    op.drop_index("ix_fighter_identity_merges_canonical", table_name="fighter_identity_merges")
    op.drop_table("fighter_identity_merges")
