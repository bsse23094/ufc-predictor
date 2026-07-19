from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from ufc_predictor.m3_materialization import (
    _control_seconds,
    _parse_count,
    _parse_pair,
    resolve_m3_current_generation,
)

ROOT = Path(__file__).parents[2]


def _reconcile_metric(ultimate: int | None, datalab: int | None) -> tuple[int | None, str]:
    """Small executable version of the documented field-level policy."""
    if ultimate is None and datalab is None:
        return None, "unavailable"
    if ultimate is None:
        return datalab, "ufc_datalab_only"
    if datalab is None:
        return ultimate, "ultimate_only"
    if ultimate == datalab:
        return ultimate, "source_agreement"
    return None, "source_conflict"


def test_performance_grain_side_assignment_and_post_bout_boundary() -> None:
    generation = resolve_m3_current_generation(ROOT / "data/processed/m3-v6")
    performance = pl.read_parquet(generation / "m3_fighter_bout_performance.parquet")
    historical = pl.read_parquet(generation / "m3_canonical_historical_bouts.parquet")
    assert performance.height == 18136
    assert (
        performance.select(["canonical_bout_id", "canonical_fighter_id"]).unique().height == 18136
    )
    assert performance.group_by("canonical_bout_id").len().select(pl.col("len").eq(2).all()).item()
    assert set(performance["field_classification"]) == {"post_bout_performance_observation"}
    assert (
        performance.filter(
            pl.col("canonical_fighter_id") == pl.col("opponent_canonical_fighter_id")
        ).height
        == 0
    )
    assert performance.filter(pl.col("ufc_datalab_source_row_id") == "row-8604").height == 0
    assert {"row-5170", "row-5658"}.isdisjoint(
        set(performance["ultimate_source_row_id"].drop_nulls())
    )
    assert (
        performance.join(
            historical.select("canonical_bout_id"), on="canonical_bout_id", how="anti"
        ).height
        == 0
    )


def test_parsers_and_missingness_are_explicit() -> None:
    assert _parse_count("0") == 0 and _parse_count("---") is None
    assert _parse_pair("12 of 30") == (12, 30) and _parse_pair("---") == (None, None)
    assert _control_seconds("1:45") == 105 and _control_seconds("--") is None
    for value in ("x", "4.2"):
        try:
            _parse_count(value)
        except ValueError:
            pass
        else:
            raise AssertionError("malformed count did not fail")


def test_synthetic_field_reconciliation_preserves_missing_zero_and_conflicts() -> None:
    assert _reconcile_metric(7, 7) == (7, "source_agreement")
    assert _reconcile_metric(7, 9) == (None, "source_conflict")
    assert _reconcile_metric(4, None) == (4, "ultimate_only")
    assert _reconcile_metric(None, 5) == (5, "ufc_datalab_only")
    assert _reconcile_metric(0, None) == (0, "ultimate_only")
    assert _reconcile_metric(None, None) == (None, "unavailable")
    value, status = _reconcile_metric(2, 3)
    assert status != "source_conflict" or value is None


@pytest.mark.parametrize("value", ["31 of 30", "one of 2", "1 of x"])
def test_invalid_landed_attempted_and_count_values_fail_deterministically(value: str) -> None:
    with pytest.raises(ValueError):
        _parse_pair(value)
    with pytest.raises(ValueError):
        _parse_count("-1")
    with pytest.raises(ValueError):
        _parse_count("1.0")


@pytest.mark.parametrize("value", ["1:60", "-1:02", "garbage"])
def test_control_time_normalization_rejects_malformed_values(value: str) -> None:
    with pytest.raises(ValueError):
        _control_seconds(value)
    assert _control_seconds("") is None
    assert _control_seconds("1:2") == 62


def test_production_rows_keep_fighter_sides_isolated_and_exclude_forbidden_fields() -> None:
    generation = resolve_m3_current_generation(ROOT / "data/processed/m3-v6")
    performance = pl.read_parquet(generation / "m3_fighter_bout_performance.parquet")
    bout_id = performance.filter(pl.col("ufc_datalab_source_row_id").is_not_null())[
        "canonical_bout_id"
    ][0]
    dual = performance.filter(pl.col("canonical_bout_id") == bout_id)
    assert dual.height == 2
    assert dual["canonical_fighter_id"][0] != dual["canonical_fighter_id"][1]
    assert dual["source_side"][0] != dual["source_side"][1]
    assert set(dual["source_side"]) == {"red", "blue"}
    forbidden = ("odds", "rank", "difference", "profile", "processed", "current_")
    assert not [name for name in performance.columns if any(term in name for term in forbidden)]
    assert set(performance["field_classification"]) == {"post_bout_performance_observation"}
