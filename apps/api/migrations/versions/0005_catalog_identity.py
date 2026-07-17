"""Create canonical-fighter aliases and append-only identity-review decisions.

Revision ID: 0005_catalog_identity
Revises: 0004_dataset_license_policy
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_catalog_identity"
down_revision: str | Sequence[str] | None = "0004_dataset_license_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the M3 identity catalog without assigning identities from candidates."""

    op.create_table(
        "fighters",
        sa.Column(
            "fighter_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "identity_status",
            sa.String(length=64),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column("merged_into_fighter_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
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
        sa.CheckConstraint("char_length(btrim(display_name)) > 0", name="display_name_nonblank"),
        sa.CheckConstraint(
            "char_length(btrim(identity_status)) > 0", name="identity_status_nonblank"
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "merged_into_fighter_id IS NULL OR merged_into_fighter_id <> fighter_id",
            name="merge_target_differs_from_self",
        ),
        sa.ForeignKeyConstraint(
            ["merged_into_fighter_id"],
            ["fighters.fighter_id"],
            name="fk_fighters_merged_into_fighter_id_fighters",
        ),
        sa.PrimaryKeyConstraint("fighter_id", name="pk_fighters"),
    )
    op.create_index("ix_fighters_identity_status", "fighters", ["identity_status"])
    op.create_table(
        "fighter_aliases",
        sa.Column(
            "fighter_alias_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("fighter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias_type", sa.String(length=64), nullable=False),
        sa.Column("alias_value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column("provider_external_id", sa.String(length=256), nullable=True),
        sa.Column(
            "resolution_status", sa.String(length=64), nullable=False, server_default="reviewed"
        ),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "system_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("system_to", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("char_length(btrim(alias_type)) > 0", name="alias_type_nonblank"),
        sa.CheckConstraint("char_length(btrim(alias_value)) > 0", name="alias_value_nonblank"),
        sa.CheckConstraint(
            "char_length(btrim(normalized_value)) > 0", name="normalized_value_nonblank"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_in_range",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
            name="valid_interval_ordered",
        ),
        sa.ForeignKeyConstraint(
            ["fighter_id"], ["fighters.fighter_id"], name="fk_fighter_aliases_fighter_id_fighters"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.source_id"],
            name="fk_fighter_aliases_source_id_data_sources",
        ),
        sa.ForeignKeyConstraint(
            ["raw_object_id"],
            ["raw_objects.raw_object_id"],
            name="fk_fighter_aliases_raw_object_id_raw_objects",
        ),
        sa.PrimaryKeyConstraint("fighter_alias_id", name="pk_fighter_aliases"),
    )
    op.create_index("ix_fighter_aliases_fighter_id", "fighter_aliases", ["fighter_id"])
    op.create_index(
        "ix_fighter_aliases_source_normalized",
        "fighter_aliases",
        ["source_id", "normalized_value"],
    )
    op.create_index(
        "ix_fighter_aliases_resolution_status", "fighter_aliases", ["resolution_status"]
    )
    op.create_index(
        "uq_fighter_aliases_source_external",
        "fighter_aliases",
        ["source_id", "alias_type", "provider_external_id"],
        unique=True,
        postgresql_where=sa.text("provider_external_id IS NOT NULL"),
    )
    op.create_table(
        "identity_resolution_decisions",
        sa.Column(
            "identity_resolution_decision_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("review_key", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("decision_type", sa.String(length=64), nullable=False),
        sa.Column("proposed_fighter_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_fighter_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("supersedes_decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actor", sa.String(length=256), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("char_length(btrim(review_key)) = 64", name="review_key_sha256"),
        sa.CheckConstraint("char_length(btrim(entity_type)) > 0", name="entity_type_nonblank"),
        sa.CheckConstraint("char_length(btrim(decision_type)) > 0", name="decision_type_nonblank"),
        sa.CheckConstraint("char_length(btrim(actor)) > 0", name="actor_nonblank"),
        sa.CheckConstraint("char_length(btrim(rationale)) > 0", name="rationale_nonblank"),
        sa.ForeignKeyConstraint(
            ["proposed_fighter_id"],
            ["fighters.fighter_id"],
            name="fk_identity_resolution_decisions_proposed_fighter_id_fighters",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_fighter_id"],
            ["fighters.fighter_id"],
            name="fk_identity_resolution_decisions_resolved_fighter_id_fighters",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_decision_id"],
            ["identity_resolution_decisions.identity_resolution_decision_id"],
            name="fk_identity_decisions_supersedes",
        ),
        sa.PrimaryKeyConstraint(
            "identity_resolution_decision_id", name="pk_identity_resolution_decisions"
        ),
    )
    op.create_index(
        "ix_identity_resolution_decisions_review_key",
        "identity_resolution_decisions",
        ["review_key"],
    )
    op.create_index(
        "ix_identity_resolution_decisions_proposed_fighter_id",
        "identity_resolution_decisions",
        ["proposed_fighter_id"],
    )
    op.create_index(
        "ix_identity_resolution_decisions_resolved_fighter_id",
        "identity_resolution_decisions",
        ["resolved_fighter_id"],
    )
    op.execute(
        """
        CREATE FUNCTION prevent_identity_resolution_decision_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'identity resolution decisions are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_identity_resolution_decisions_append_only
        BEFORE UPDATE OR DELETE ON identity_resolution_decisions
        FOR EACH ROW EXECUTE FUNCTION prevent_identity_resolution_decision_mutation()
        """
    )


def downgrade() -> None:
    """Remove the isolated M3 catalog-identity schema in reverse dependency order."""

    op.execute(
        "DROP TRIGGER trg_identity_resolution_decisions_append_only "
        "ON identity_resolution_decisions"
    )
    op.execute("DROP FUNCTION prevent_identity_resolution_decision_mutation()")
    op.drop_index(
        "ix_identity_resolution_decisions_resolved_fighter_id",
        table_name="identity_resolution_decisions",
    )
    op.drop_index(
        "ix_identity_resolution_decisions_proposed_fighter_id",
        table_name="identity_resolution_decisions",
    )
    op.drop_index(
        "ix_identity_resolution_decisions_review_key", table_name="identity_resolution_decisions"
    )
    op.drop_table("identity_resolution_decisions")
    op.drop_index("uq_fighter_aliases_source_external", table_name="fighter_aliases")
    op.drop_index("ix_fighter_aliases_resolution_status", table_name="fighter_aliases")
    op.drop_index("ix_fighter_aliases_source_normalized", table_name="fighter_aliases")
    op.drop_index("ix_fighter_aliases_fighter_id", table_name="fighter_aliases")
    op.drop_table("fighter_aliases")
    op.drop_index("ix_fighters_identity_status", table_name="fighters")
    op.drop_table("fighters")
