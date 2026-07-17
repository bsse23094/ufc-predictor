from __future__ import annotations

from pathlib import Path
from typing import cast

from sqlalchemy import Table, UniqueConstraint

from ufc_api.data.models import (
    DataQualityIssue,
    DataSource,
    IngestionRunRecord,
    RawObject,
    RawRetrieval,
)


def test_data_governance_models_preserve_policy_and_raw_lineage() -> None:
    assert {
        "audit_state",
        "dataset_license",
        "policy_terms_version",
        "audit_evidence_ref",
        "enabled",
        "attribution",
    } <= set(DataSource.__table__.columns.keys())
    assert {"idempotency_key", "previous_checkpoint", "new_checkpoint", "accepted_count"} <= set(
        IngestionRunRecord.__table__.columns.keys()
    )
    assert {"sha256", "object_uri", "retention_classification"} <= set(
        RawObject.__table__.columns.keys()
    )
    assert {
        "raw_object_id",
        "source_locator_redacted",
        "terms_policy_version",
        "original_filename",
        "source_schema_version",
    } <= set(RawRetrieval.__table__.columns.keys())
    assert {"rule_id", "blocking", "safe_summary"} <= set(DataQualityIssue.__table__.columns.keys())


def test_governance_migration_is_present_and_source_enablement_is_constrained() -> None:
    root = Path(__file__).resolve().parents[2]
    migration_path = root / "apps/api/migrations/versions/0001_governance_raw.py"
    migration = migration_path.read_text(encoding="utf-8")

    assert "enabled_requires_approved_audit" in migration
    assert "raw_retrievals" in migration
    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in migration


def test_governance_models_preserve_idempotency_and_content_identity_constraints() -> None:
    run_table = cast(Table, IngestionRunRecord.__table__)
    raw_table = cast(Table, RawObject.__table__)
    run_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in run_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    raw_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in raw_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("source_id", "idempotency_key") in run_constraints
    assert ("source_id", "storage_namespace", "sha256") in raw_constraints
