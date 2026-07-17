"""Make canonical catalog quarantine reports durable and idempotent.

Revision ID: 0010_canonical_quality_issues
Revises: 0009_canonical_bout_catalog
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_canonical_quality_issues"
down_revision: str | Sequence[str] | None = "0009_canonical_bout_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a source-scoped key so canonical quarantine replays aggregate safely."""
    op.add_column(
        "data_quality_issues", sa.Column("canonical_issue_key", sa.String(length=64), nullable=True)
    )
    op.create_index(
        "uq_data_quality_issues_source_canonical_issue",
        "data_quality_issues",
        ["source_id", "canonical_issue_key"],
        unique=True,
        postgresql_where=sa.text("canonical_issue_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove the isolated canonical-report idempotency key."""
    op.drop_index("uq_data_quality_issues_source_canonical_issue", table_name="data_quality_issues")
    op.drop_column("data_quality_issues", "canonical_issue_key")
