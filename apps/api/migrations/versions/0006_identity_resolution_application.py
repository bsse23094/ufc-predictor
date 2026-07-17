"""Add append-only reviewed-identity application outcomes.

Revision ID: 0006_identity_resolution_app
Revises: 0005_catalog_identity
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_identity_resolution_app"
down_revision: str | Sequence[str] | None = "0005_catalog_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Ensure each explicit review decision is applied or quarantined exactly once."""

    op.create_table(
        "identity_resolution_applications",
        sa.Column(
            "identity_resolution_application_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_fighter_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("quarantine_reason", sa.Text(), nullable=True),
        sa.Column("applied_by", sa.String(length=256), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "state IN ('applied', 'quarantined')", name="state_is_terminal_resolution_outcome"
        ),
        sa.CheckConstraint(
            "(state = 'applied' AND canonical_fighter_id IS NOT NULL "
            "AND quarantine_reason IS NULL) OR "
            "(state = 'quarantined' AND canonical_fighter_id IS NULL "
            "AND quarantine_reason IS NOT NULL)",
            name="state_matches_resolution_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["identity_resolution_decisions.identity_resolution_decision_id"],
            name="fk_identity_applications_decision",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_fighter_id"],
            ["fighters.fighter_id"],
            name="fk_identity_applications_fighter",
        ),
        sa.PrimaryKeyConstraint(
            "identity_resolution_application_id", name="pk_identity_resolution_applications"
        ),
        sa.UniqueConstraint("decision_id", name="uq_identity_resolution_applications_decision_id"),
    )
    op.create_index(
        "ix_identity_resolution_applications_state", "identity_resolution_applications", ["state"]
    )
    op.execute(
        """
        CREATE FUNCTION prevent_identity_resolution_application_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'identity resolution applications are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_identity_resolution_applications_append_only
        BEFORE UPDATE OR DELETE ON identity_resolution_applications
        FOR EACH ROW EXECUTE FUNCTION prevent_identity_resolution_application_mutation()
        """
    )


def downgrade() -> None:
    """Remove the isolated identity-resolution application table."""

    op.execute(
        "DROP TRIGGER trg_identity_resolution_applications_append_only "
        "ON identity_resolution_applications"
    )
    op.execute("DROP FUNCTION prevent_identity_resolution_application_mutation()")
    op.drop_index(
        "ix_identity_resolution_applications_state", table_name="identity_resolution_applications"
    )
    op.drop_table("identity_resolution_applications")
