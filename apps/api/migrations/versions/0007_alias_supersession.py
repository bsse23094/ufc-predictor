"""Add append-only bitemporal reviewed-alias supersessions.

Revision ID: 0007_alias_supersession
Revises: 0006_identity_resolution_app
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_alias_supersession"
down_revision: str | Sequence[str] | None = "0006_identity_resolution_app"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Retain immutable alias-correction links while closing old current aliases."""

    op.create_table(
        "fighter_alias_supersessions",
        sa.Column(
            "fighter_alias_supersession_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "identity_resolution_application_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("superseded_alias_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("replacement_alias_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_by", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "superseded_alias_id <> replacement_alias_id", name="aliases_must_differ"
        ),
        sa.ForeignKeyConstraint(
            ["identity_resolution_application_id"],
            ["identity_resolution_applications.identity_resolution_application_id"],
            name="fk_alias_supersessions_application",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_alias_id"],
            ["fighter_aliases.fighter_alias_id"],
            name="fk_alias_supersessions_superseded_alias",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_alias_id"],
            ["fighter_aliases.fighter_alias_id"],
            name="fk_alias_supersessions_replacement_alias",
        ),
        sa.PrimaryKeyConstraint(
            "fighter_alias_supersession_id", name="pk_fighter_alias_supersessions"
        ),
        sa.UniqueConstraint("superseded_alias_id", name="uq_alias_supersessions_superseded_alias"),
        sa.UniqueConstraint(
            "replacement_alias_id", name="uq_alias_supersessions_replacement_alias"
        ),
    )
    op.create_index(
        "ix_fighter_alias_supersessions_application_id",
        "fighter_alias_supersessions",
        ["identity_resolution_application_id"],
    )
    op.execute(
        """
        CREATE FUNCTION prevent_fighter_alias_supersession_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'fighter alias supersessions are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_fighter_alias_supersessions_append_only
        BEFORE UPDATE OR DELETE ON fighter_alias_supersessions
        FOR EACH ROW EXECUTE FUNCTION prevent_fighter_alias_supersession_mutation()
        """
    )


def downgrade() -> None:
    """Remove only the correction ledger introduced by this migration."""

    op.execute(
        "DROP TRIGGER trg_fighter_alias_supersessions_append_only ON fighter_alias_supersessions"
    )
    op.execute("DROP FUNCTION prevent_fighter_alias_supersession_mutation()")
    op.drop_index(
        "ix_fighter_alias_supersessions_application_id",
        table_name="fighter_alias_supersessions",
    )
    op.drop_table("fighter_alias_supersessions")
