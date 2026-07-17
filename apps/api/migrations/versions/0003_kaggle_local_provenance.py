"""Record local licensed-file provenance required by the Kaggle ingestion source.

Revision ID: 0003_kaggle_local_provenance
Revises: 0002_raw_object_source_scope
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_kaggle_local_provenance"
down_revision: str | Sequence[str] | None = "0002_raw_object_source_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable lineage fields without rewriting existing raw evidence."""

    op.add_column("data_sources", sa.Column("attribution", sa.Text(), nullable=True))
    op.add_column(
        "raw_retrievals", sa.Column("original_filename", sa.String(length=256), nullable=True)
    )
    op.add_column(
        "raw_retrievals",
        sa.Column("source_schema_version", sa.String(length=256), nullable=True),
    )


def downgrade() -> None:
    """Remove the additive metadata fields for supported local downgrades."""

    op.drop_column("raw_retrievals", "source_schema_version")
    op.drop_column("raw_retrievals", "original_filename")
    op.drop_column("data_sources", "attribution")
