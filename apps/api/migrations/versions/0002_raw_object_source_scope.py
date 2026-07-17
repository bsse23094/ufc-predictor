"""Scope raw-object catalog identities to their originating source.

Revision ID: 0002_raw_object_source_scope
Revises: 0001_governance_raw
Create Date: 2026-07-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_raw_object_source_scope"
down_revision: str | Sequence[str] | None = "0001_governance_raw"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Preserve source provenance when distinct sources retain identical bytes."""

    op.drop_constraint("uq_raw_objects_storage_namespace", "raw_objects", type_="unique")
    op.create_unique_constraint(
        "uq_raw_objects_source_namespace_sha",
        "raw_objects",
        ["source_id", "storage_namespace", "sha256"],
    )


def downgrade() -> None:
    """Restore the prior global catalog identity for intentionally supported downgrades."""

    op.drop_constraint("uq_raw_objects_source_namespace_sha", "raw_objects", type_="unique")
    op.create_unique_constraint(
        "uq_raw_objects_storage_namespace",
        "raw_objects",
        ["storage_namespace", "sha256"],
    )
