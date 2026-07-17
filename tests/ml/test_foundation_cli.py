from __future__ import annotations

from typer.testing import CliRunner

from ufc_predictor.cli import app


def test_info_reports_disabled_sources() -> None:
    result = CliRunner().invoke(app, ["info"])

    assert result.exit_code == 0
    assert "enabled_sources=none" in result.stdout
    assert (
        "network ingestion is disabled; audited local-file commands remain explicit"
        in result.stdout
    )
