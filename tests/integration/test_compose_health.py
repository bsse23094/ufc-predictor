from __future__ import annotations

import os
import subprocess
from collections.abc import Generator
from http.client import RemoteDisconnected
from pathlib import Path
from time import monotonic, sleep
from urllib.error import URLError
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _wait_for_health() -> None:
    """Wait only for Uvicorn's bounded local startup window after Compose reports running."""

    deadline = monotonic() + 15
    while monotonic() < deadline:
        try:
            with urlopen("http://127.0.0.1:8000/health", timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, RemoteDisconnected, URLError):
            sleep(0.25)
    raise AssertionError("API health endpoint did not become available after container startup")


@pytest.fixture(scope="module")
def compose_dependencies() -> Generator[None, None, None]:
    if os.environ.get("RUN_CONTAINER_TESTS") != "1":
        docker_info = subprocess.run(
            ["docker", "info"],
            cwd=ROOT,
            capture_output=True,
            timeout=10,
        )
        if docker_info.returncode != 0:
            pytest.skip(
                "Docker is unavailable; start Docker Desktop to run container integration tests"
            )

    try:
        subprocess.run(
            ["docker", "compose", "up", "-d", "--wait", "postgres", "redis"],
            cwd=ROOT,
            check=True,
            timeout=90,
        )
        yield
    finally:
        subprocess.run(
            ["docker", "compose", "--profile", "app", "down"],
            cwd=ROOT,
            check=False,
            timeout=60,
        )


@pytest.mark.integration
def test_compose_dependencies_become_healthy(compose_dependencies: None) -> None:
    assert compose_dependencies is None


@pytest.mark.integration
def test_governance_migration_upgrades_the_compose_database(compose_dependencies: None) -> None:
    assert compose_dependencies is None
    subprocess.run(
        [
            "uv",
            "run",
            "--project",
            "apps/api",
            "alembic",
            "-c",
            "apps/api/alembic.ini",
            "upgrade",
            "head",
        ],
        cwd=ROOT,
        check=True,
        timeout=60,
    )
    query = (
        "SELECT version_num FROM alembic_version; "
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;"
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "ufc_predictor",
            "-d",
            "ufc_predictor",
            "-At",
            "-c",
            query,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    rows = set(result.stdout.splitlines())
    assert "0010_canonical_quality_issues" in rows
    assert {
        "data_sources",
        "ingestion_runs",
        "raw_objects",
        "raw_retrievals",
        "data_quality_issues",
        "fighters",
        "fighter_aliases",
        "identity_resolution_decisions",
        "identity_resolution_applications",
        "fighter_alias_supersessions",
        "fighter_identity_merges",
        "fighter_identity_splits",
        "divisions",
        "events",
        "event_source_references",
        "fights",
        "fight_source_references",
        "fight_participants",
        "fight_participant_identity_evidence",
        "fight_results",
    } <= rows


@pytest.mark.integration
def test_application_profile_starts_from_the_built_images(compose_dependencies: None) -> None:
    """Catch runtime writes that a successful image build cannot reveal."""

    assert compose_dependencies is None
    subprocess.run(
        ["docker", "compose", "--profile", "app", "up", "-d", "--wait", "api", "web"],
        cwd=ROOT,
        check=True,
        timeout=120,
    )
    _wait_for_health()
