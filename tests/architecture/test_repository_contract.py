from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.architecture
def test_data_and_model_zones_keep_only_committed_markers() -> None:
    expected_files = {
        "data/README.md",
        "data/raw/.gitkeep",
        "data/quarantine/.gitkeep",
        "data/interim/.gitkeep",
        "data/processed/.gitkeep",
        "models/README.md",
        "models/.gitkeep",
    }
    assert all((ROOT / relative_path).is_file() for relative_path in expected_files)


@pytest.mark.architecture
def test_gitignore_covers_raw_data_model_and_secret_policy() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("/data/raw/*", "/models/*", ".env", "*.joblib", "*.duckdb"):
        assert pattern in gitignore


@pytest.mark.architecture
def test_source_audit_remains_explicitly_pre_implementation() -> None:
    audit = (ROOT / "docs/architecture/DATA_SOURCE_AUDIT.md").read_text(encoding="utf-8")
    assert "no source availability or field is asserted until verified" in audit


@pytest.mark.architecture
def test_migration_task_uses_the_api_alembic_configuration_from_repository_root() -> None:
    justfile = (ROOT / "justfile").read_text(encoding="utf-8")
    alembic_config = (ROOT / "apps/api/alembic.ini").read_text(encoding="utf-8")

    assert "uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head" in justfile
    assert "script_location = %(here)s/migrations" in alembic_config
    assert "prepend_sys_path = %(here)s/src" in alembic_config
