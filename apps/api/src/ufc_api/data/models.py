"""Persistence owned by the data-governance and ingestion boundary.

These tables hold policy, immutable-object lineage, run accounting, and quality
issues.  They intentionally contain no source-specific schema or provider data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ufc_api.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DataSource(Base):
    """Audited source policy; credentials are stored only in the secret manager."""

    __tablename__ = "data_sources"
    __table_args__ = (
        CheckConstraint("audit_state IN ('pending', 'approved', 'rejected')", name="audit_state"),
        CheckConstraint(
            "NOT enabled OR ("
            "audit_state = 'approved' AND policy_terms_version IS NOT NULL "
            "AND retention_classification IS NOT NULL AND approved_at IS NOT NULL "
            "AND audit_evidence_ref IS NOT NULL)",
            name="enabled_requires_approved_audit",
        ),
    )

    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    stable_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    dataset_license: Mapped[str | None] = mapped_column(String(128))
    policy_terms_version: Mapped[str | None] = mapped_column(String(128))
    retention_classification: Mapped[str | None] = mapped_column(String(128))
    audit_evidence_ref: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    rate_policy: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    attribution: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
        server_default=func.now(),
    )


class IngestionRunRecord(Base):
    """Idempotent, auditable processing attempt with explicit row accounting."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        UniqueConstraint("source_id", "idempotency_key", name="uq_ingestion_runs_source_id"),
        CheckConstraint("attempt >= 0", name="attempt_nonnegative"),
        CheckConstraint("input_count >= 0", name="input_count_nonnegative"),
        CheckConstraint("accepted_count >= 0", name="accepted_count_nonnegative"),
        CheckConstraint("quarantined_count >= 0", name="quarantined_count_nonnegative"),
        CheckConstraint("filtered_count >= 0", name="filtered_count_nonnegative"),
    )

    ingestion_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("data_sources.source_id"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(128))
    source_schema_version: Mapped[str | None] = mapped_column(String(256))
    pipeline_version: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="requested")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    accepted_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    quarantined_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    filtered_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    previous_checkpoint: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    new_checkpoint: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error_summary: Mapped[str | None] = mapped_column(Text)
    initiated_by: Mapped[str | None] = mapped_column(String(256))


class RawObject(Base):
    """Content-addressed raw bytes; raw content is never overwritten or normalized."""

    __tablename__ = "raw_objects"
    __table_args__ = (
        CheckConstraint("char_length(sha256) = 64", name="sha256_length"),
        UniqueConstraint(
            "source_id",
            "storage_namespace",
            "sha256",
            name="uq_raw_objects_source_namespace_sha",
        ),
    )

    raw_object_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("data_sources.source_id"), nullable=False
    )
    ingestion_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("ingestion_runs.ingestion_run_id"), nullable=False
    )
    storage_namespace: Mapped[str] = mapped_column(
        String(128), nullable=False, default="raw", server_default="raw"
    )
    object_uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(256))
    retention_classification: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )


class RawRetrieval(Base):
    """Append-only retrieval event so repeated identical bytes remain observable."""

    __tablename__ = "raw_retrievals"

    raw_retrieval_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    raw_object_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("raw_objects.raw_object_id"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("data_sources.source_id"), nullable=False
    )
    ingestion_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("ingestion_runs.ingestion_run_id"), nullable=False
    )
    source_locator_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer)
    http_metadata: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    retrieval_code_version: Mapped[str] = mapped_column(String(128), nullable=False)
    terms_policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    secrecy_classification: Mapped[str] = mapped_column(String(128), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(256))
    source_schema_version: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )


class DataQualityIssue(Base):
    """Durable issue record; resolution history belongs to a later administration domain."""

    __tablename__ = "data_quality_issues"

    issue_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    ingestion_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("ingestion_runs.ingestion_run_id")
    )
    source_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("data_sources.source_id")
    )
    entity_type: Mapped[str | None] = mapped_column(String(128))
    entity_id: Mapped[str | None] = mapped_column(String(256))
    rule_id: Mapped[str] = mapped_column(String(256), nullable=False)
    canonical_issue_key: Mapped[str | None] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    blocking: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    safe_summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    occurrence_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=func.now()
    )
