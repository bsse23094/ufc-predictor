"""Persist the declared licence alongside every durable source policy.

Revision ID: 0004_dataset_license_policy
Revises: 0003_kaggle_local_provenance
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_dataset_license_policy"
down_revision: str | Sequence[str] | None = "0003_kaggle_local_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add an additive declared-licence field without altering raw evidence."""

    op.add_column(
        "data_sources", sa.Column("dataset_license", sa.String(length=128), nullable=True)
    )


def downgrade() -> None:
    """Remove the additive declared-licence field for supported local downgrades."""

    op.drop_column("data_sources", "dataset_license")
