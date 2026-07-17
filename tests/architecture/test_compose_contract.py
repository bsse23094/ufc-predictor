from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.architecture
def test_compose_declares_health_checked_local_dependencies() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "postgres:" in compose
    assert "redis:" in compose
    assert compose.count("healthcheck:") >= 2
    assert "postgres-data:" in compose
    assert "redis-data:" in compose
