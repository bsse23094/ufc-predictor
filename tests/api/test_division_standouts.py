"""Historical form board reads accepted bouts with defensible sample thresholds."""

from __future__ import annotations

import pytest

from ufc_api.data.parquet_catalog import M3_DIR
from ufc_api.fighters.standouts import division_standouts


def test_standouts_have_recent_divisional_records() -> None:
    if not (M3_DIR / "m3_canonical_historical_bouts.parquet").is_file():
        pytest.skip("accepted local M3 materialization unavailable")
    board = division_standouts()
    assert board["as_of_date"] >= board["window_start"]
    assert len(board["divisions"]) >= 8
    for division in board["divisions"]:
        assert 1 <= len(division["fighters"]) <= 4
        scores = [fighter["form_score"] for fighter in division["fighters"]]
        assert scores == sorted(scores, reverse=True)
        for fighter in division["fighters"]:
            assert fighter["wins"] + fighter["losses"] >= 3
            assert fighter["last_bout_date"] >= board["window_start"]
