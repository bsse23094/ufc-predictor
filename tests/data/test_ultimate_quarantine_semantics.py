from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from ufc_predictor.features.model_ready import (
    assert_pre_fight_feature_schema,
    forbidden_source_columns,
)
from ufc_predictor.ingestion.kaggle_ultimate import classify_leakage_column


def test_every_unsafe_ultimate_source_field_is_absent_from_restricted_output(
    tmp_path: Path,
) -> None:
    source_columns = (
        "R_fighter",
        "B_fighter",
        "date",
        "location",
        "win_dif",
        "R_ev",
        "B_ev",
        "Winner",
        "finish",
        "finish_details",
        "finish_round",
        "finish_round_time",
        "total_fight_time_secs",
        "R_avg_SIG_STR_landed",
        "B_avg_SIG_STR_landed",
    )
    unsafe = {
        column
        for column in source_columns
        if classify_leakage_column(column).value != "safe_context_not_yet_feature_approved"
    }
    restricted = pl.DataFrame(
        {
            "fight_date": ["2024-01-01"],
            "fighter_one_source_name": ["Alpha"],
            "fighter_two_source_name": ["Beta"],
            "quarantined_column_names": [sorted(unsafe)],
        }
    )
    output_path = tmp_path / "restricted.parquet"
    restricted.write_parquet(output_path)
    output = pl.read_parquet(output_path)

    assert unsafe.isdisjoint(output.columns)
    assert {column for column in unsafe if column.endswith("_dif")} <= set(
        output["quarantined_column_names"][0]
    )
    assert {
        "R_ev",
        "B_ev",
        "Winner",
        "finish",
        "finish_details",
        "finish_round",
        "finish_round_time",
        "total_fight_time_secs",
    } <= set(output["quarantined_column_names"][0])


def test_model_ready_schema_rejects_every_requested_source_leakage_field() -> None:
    unsafe = (
        "win_dif",
        "R_ev",
        "B_ev",
        "Winner",
        "finish",
        "finish_details",
        "finish_round",
        "finish_round_time",
        "total_fight_time_secs",
        "R_avg_SIG_STR_landed",
        "B_avg_SIG_STR_landed",
    )
    assert forbidden_source_columns(unsafe) == tuple(sorted(unsafe))
    with pytest.raises(ValueError, match="forbidden source fields"):
        assert_pre_fight_feature_schema(unsafe)
    assert_pre_fight_feature_schema(
        ("red_prior_ufc_bouts", "blue_prior_ufc_bouts", "difference_win_rate")
    )
