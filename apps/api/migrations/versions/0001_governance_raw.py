"""Create source policy, immutable raw lineage, run, and quality tables.

Revision ID: 0001_governance_raw
Revises:
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_governance_raw"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "data_sources",
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("stable_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("audit_state", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("policy_terms_version", sa.String(length=128), nullable=True),
        sa.Column("retention_classification", sa.String(length=128), nullable=True),
        sa.Column("audit_evidence_ref", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rate_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("owner", sa.String(length=256), nullable=True),
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
        sa.CheckConstraint(
            "audit_state IN ('pending', 'approved', 'rejected')", name="audit_state"
        ),
        sa.CheckConstraint(
            "NOT enabled OR (audit_state = 'approved' AND policy_terms_version IS NOT NULL "
            "AND retention_classification IS NOT NULL AND approved_at IS NOT NULL "
            "AND audit_evidence_ref IS NOT NULL)",
            name="enabled_requires_approved_audit",
        ),
        sa.PrimaryKeyConstraint("source_id", name="pk_data_sources"),
        sa.UniqueConstraint("stable_key", name="uq_data_sources_stable_key"),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column(
            "ingestion_run_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=128), nullable=True),
        sa.Column("source_schema_version", sa.String(length=256), nullable=True),
        sa.Column("pipeline_version", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="requested"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quarantined_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("filtered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("previous_checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("initiated_by", sa.String(length=256), nullable=True),
        sa.CheckConstraint("attempt >= 0", name="attempt_nonnegative"),
        sa.CheckConstraint("input_count >= 0", name="input_count_nonnegative"),
        sa.CheckConstraint("accepted_count >= 0", name="accepted_count_nonnegative"),
        sa.CheckConstraint("quarantined_count >= 0", name="quarantined_count_nonnegative"),
        sa.CheckConstraint("filtered_count >= 0", name="filtered_count_nonnegative"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.source_id"],
            name="fk_ingestion_runs_source_id_data_sources",
        ),
        sa.PrimaryKeyConstraint("ingestion_run_id", name="pk_ingestion_runs"),
        sa.UniqueConstraint("source_id", "idempotency_key", name="uq_ingestion_runs_source_id"),
    )
    op.create_index("ix_ingestion_runs_status", "ingestion_runs", ["status"])
    op.create_index("ix_ingestion_runs_source_id", "ingestion_runs", ["source_id"])
    op.create_index("ix_ingestion_runs_published_at", "ingestion_runs", ["published_at"])
    op.create_table(
        "raw_objects",
        sa.Column(
            "raw_object_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_namespace", sa.String(length=128), nullable=False, server_default="raw"),
        sa.Column("object_uri", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_length", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=256), nullable=True),
        sa.Column("retention_classification", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("char_length(sha256) = 64", name="sha256_length"),
        sa.ForeignKeyConstraint(
            ["source_id"], ["data_sources.source_id"], name="fk_raw_objects_source_id_data_sources"
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.ingestion_run_id"],
            name="fk_raw_objects_ingestion_run_id_ingestion_runs",
        ),
        sa.PrimaryKeyConstraint("raw_object_id", name="pk_raw_objects"),
        sa.UniqueConstraint("storage_namespace", "sha256", name="uq_raw_objects_storage_namespace"),
    )
    op.create_index("ix_raw_objects_source_id", "raw_objects", ["source_id"])
    op.create_index("ix_raw_objects_created_at", "raw_objects", ["created_at"])
    op.create_table(
        "raw_retrievals",
        sa.Column(
            "raw_retrieval_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("raw_object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_locator_redacted", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("http_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("retrieval_code_version", sa.String(length=128), nullable=False),
        sa.Column("terms_policy_version", sa.String(length=128), nullable=False),
        sa.Column("secrecy_classification", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_object_id"],
            ["raw_objects.raw_object_id"],
            name="fk_raw_retrievals_raw_object_id_raw_objects",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.source_id"],
            name="fk_raw_retrievals_source_id_data_sources",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.ingestion_run_id"],
            name="fk_raw_retrievals_ingestion_run_id_ingestion_runs",
        ),
        sa.PrimaryKeyConstraint("raw_retrieval_id", name="pk_raw_retrievals"),
    )
    op.create_index("ix_raw_retrievals_source_id", "raw_retrievals", ["source_id"])
    op.create_index("ix_raw_retrievals_retrieved_at", "raw_retrievals", ["retrieved_at"])
    op.create_table(
        "data_quality_issues",
        sa.Column(
            "issue_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entity_type", sa.String(length=128), nullable=True),
        sa.Column("entity_id", sa.String(length=256), nullable=True),
        sa.Column("rule_id", sa.String(length=256), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("blocking", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("safe_summary", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.ingestion_run_id"],
            name="fk_data_quality_issues_ingestion_run_id_ingestion_runs",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.source_id"],
            name="fk_data_quality_issues_source_id_data_sources",
        ),
        sa.PrimaryKeyConstraint("issue_id", name="pk_data_quality_issues"),
    )
    op.create_index(
        "ix_data_quality_issues_blocking_status", "data_quality_issues", ["blocking", "status"]
    )
    op.create_index("ix_data_quality_issues_source_id", "data_quality_issues", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_data_quality_issues_source_id", table_name="data_quality_issues")
    op.drop_index("ix_data_quality_issues_blocking_status", table_name="data_quality_issues")
    op.drop_table("data_quality_issues")
    op.drop_index("ix_raw_retrievals_retrieved_at", table_name="raw_retrievals")
    op.drop_index("ix_raw_retrievals_source_id", table_name="raw_retrievals")
    op.drop_table("raw_retrievals")
    op.drop_index("ix_raw_objects_created_at", table_name="raw_objects")
    op.drop_index("ix_raw_objects_source_id", table_name="raw_objects")
    op.drop_table("raw_objects")
    op.drop_index("ix_ingestion_runs_published_at", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_source_id", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_status", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    op.drop_table("data_sources")
