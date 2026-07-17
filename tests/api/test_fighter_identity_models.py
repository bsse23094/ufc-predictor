from __future__ import annotations

from pathlib import Path
from typing import cast

from sqlalchemy import CheckConstraint, Table

from ufc_api.fighters.models import (
    Fighter,
    FighterAlias,
    FighterAliasSupersession,
    FighterIdentityMerge,
    FighterIdentitySplit,
    IdentityResolutionApplication,
    IdentityResolutionDecision,
)


def test_identity_models_require_canonical_aliases_and_append_only_review_evidence() -> None:
    assert {
        "display_name",
        "identity_status",
        "merged_into_fighter_id",
        "row_version",
    } <= set(Fighter.__table__.columns.keys())
    assert {
        "fighter_id",
        "source_id",
        "raw_object_id",
        "normalized_value",
        "resolution_status",
        "evidence",
    } <= set(FighterAlias.__table__.columns.keys())
    assert {
        "review_key",
        "decision_type",
        "evidence",
        "actor",
        "decided_at",
        "rationale",
        "supersedes_decision_id",
    } <= set(IdentityResolutionDecision.__table__.columns.keys())
    assert {
        "decision_id",
        "canonical_fighter_id",
        "state",
        "quarantine_reason",
        "applied_by",
    } <= set(IdentityResolutionApplication.__table__.columns.keys())
    assert {
        "identity_resolution_application_id",
        "superseded_alias_id",
        "replacement_alias_id",
        "superseded_at",
    } <= set(FighterAliasSupersession.__table__.columns.keys())
    assert {
        "identity_resolution_application_id",
        "canonical_fighter_id",
        "merged_fighter_id",
        "merged_at",
    } <= set(FighterIdentityMerge.__table__.columns.keys())
    assert {
        "identity_resolution_application_id",
        "fighter_identity_merge_id",
        "restored_fighter_id",
        "split_at",
    } <= set(FighterIdentitySplit.__table__.columns.keys())


def test_fighter_self_merge_and_review_key_integrity_are_constrained() -> None:
    fighter_table = cast(Table, Fighter.__table__)
    decision_table = cast(Table, IdentityResolutionDecision.__table__)
    fighter_checks = {
        constraint.name
        for constraint in fighter_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    decision_checks = {
        constraint.name
        for constraint in decision_table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_fighters_merge_target_differs_from_self" in fighter_checks
    assert "ck_identity_resolution_decisions_review_key_sha256" in decision_checks
    assert "ck_identity_resolution_decisions_rationale_nonblank" in decision_checks


def test_catalog_identity_migration_creates_append_only_review_trigger() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = (root / "apps/api/migrations/versions/0005_catalog_identity.py").read_text(
        encoding="utf-8"
    )

    assert "identity_resolution_decisions" in migration
    assert "trg_identity_resolution_decisions_append_only" in migration
    assert "BEFORE UPDATE OR DELETE" in migration


def test_resolution_application_migration_creates_terminal_append_only_outcomes() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = (
        root / "apps/api/migrations/versions/0006_identity_resolution_application.py"
    ).read_text(encoding="utf-8")

    assert 'revision: str = "0006_identity_resolution_app"' in migration
    assert "identity_resolution_applications" in migration
    assert "uq_identity_resolution_applications_decision_id" in migration
    assert "trg_identity_resolution_applications_append_only" in migration
    assert "BEFORE UPDATE OR DELETE" in migration


def test_alias_supersession_migration_retains_append_only_correction_links() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = (root / "apps/api/migrations/versions/0007_alias_supersession.py").read_text(
        encoding="utf-8"
    )

    assert 'revision: str = "0007_alias_supersession"' in migration
    assert "fighter_alias_supersessions" in migration
    assert "uq_alias_supersessions_superseded_alias" in migration
    assert "trg_fighter_alias_supersessions_append_only" in migration
    assert "BEFORE UPDATE OR DELETE" in migration


def test_identity_merge_split_migration_guards_current_state_and_audit_history() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = (root / "apps/api/migrations/versions/0008_identity_merge_split.py").read_text(
        encoding="utf-8"
    )

    assert 'revision: str = "0008_identity_merge_split"' in migration
    assert "fighter_identity_merges" in migration
    assert "fighter_identity_splits" in migration
    assert "trg_fighters_guard_merge_transition" in migration
    assert "trg_fighter_aliases_guarded_closure" in migration
    assert "trg_fighter_identity_merges_append_only" in migration
    assert "trg_fighter_identity_splits_append_only" in migration


def test_canonical_bout_catalog_migration_requires_provenance_and_complete_fights() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = (root / "apps/api/migrations/versions/0009_canonical_bout_catalog.py").read_text(
        encoding="utf-8"
    )

    assert 'revision: str = "0009_canonical_bout_catalog"' in migration
    assert "fight_source_references" in migration
    assert "fight_participant_identity_evidence" in migration
    assert "fight_results" in migration
    assert "validate_published_canonical_fight" in migration
    assert "validate_fight_participant_identity_evidence" in migration


def test_canonical_quality_issue_migration_deduplicates_blocking_replays() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = (root / "apps/api/migrations/versions/0010_canonical_quality_issues.py").read_text(
        encoding="utf-8"
    )

    assert 'revision: str = "0010_canonical_quality_issues"' in migration
    assert "canonical_issue_key" in migration
    assert "uq_data_quality_issues_source_canonical_issue" in migration
