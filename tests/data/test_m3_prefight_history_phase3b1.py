from __future__ import annotations

import json
from datetime import date
from hashlib import sha256
from pathlib import Path

import polars as pl
import pytest

from ufc_predictor.m3_materialization import (
    _PREFIGHT_CUTOFF_POLICY,
    _PREFIGHT_FEATURE_POLICIES,
    _PUBLISHED_ARTIFACTS,
    _artifact_row_key,
    _prefight_fighter_history_rows,
    materialize_m3_v6,
    resolve_m3_current_generation,
)

ROOT = Path(__file__).parents[2]
V6_DIR = ROOT / "data/quarantine/reviews/m3-corrections-v6"
ULTIMATE = ROOT / "data/incoming/ultimate-ufc-dataset/ufc-master.csv"
DATALAB = ROOT / "data/incoming/ufc-datalab/3268146c05211de9deab8b9b4c0bb4a954815f0b/stats_raw.csv"


def _materialize(output_dir: Path, failure_injection: str | None = None) -> dict[str, object]:
    return materialize_m3_v6(
        ultimate_csv=ULTIMATE,
        datalab_csv=DATALAB,
        v6_dir=V6_DIR,
        output_dir=output_dir,
        failure_injection=failure_injection,
    )


@pytest.fixture(scope="module")
def generation(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("m3-phase3b1")
    _materialize(output)
    return resolve_m3_current_generation(output)


def _snapshots(generation: Path) -> pl.DataFrame:
    return pl.read_parquet(generation / "m3_prefight_fighter_history.parquet")


def _synthetic_bouts() -> pl.DataFrame:
    return pl.DataFrame(
        [
            ("b1", date(2020, 1, 1), "a", "b", "a", "b", False, False, "KO/TKO"),
            ("b2", date(2020, 1, 2), "a", "c", None, None, False, True, "Decision"),
            ("b3", date(2020, 1, 3), "a", "d", None, None, True, False, "Overturned"),
            ("b4", date(2020, 1, 4), "a", "e", "a", "e", False, False, "Submission"),
        ],
        schema=[
            "canonical_bout_id",
            "fight_date",
            "canonical_fighter_a_id",
            "canonical_fighter_b_id",
            "winner_canonical_fighter_id",
            "loser_canonical_fighter_id",
            "is_no_contest",
            "is_draw",
            "canonical_finish_method",
        ],
        orient="row",
    )


def _synthetic_snapshot(bouts: pl.DataFrame, bout_id: str, fighter_id: str) -> dict[str, object]:
    return next(
        row
        for row in _prefight_fighter_history_rows(bouts)
        if row["canonical_bout_id"] == bout_id and row["canonical_fighter_id"] == fighter_id
    )


def test_production_snapshot_grain_identity_and_strict_history(generation: Path) -> None:
    snapshots = _snapshots(generation)
    bouts = pl.read_parquet(generation / "m3_canonical_historical_bouts.parquet")
    fighters = set(
        pl.read_parquet(generation / "m3_canonical_fighters.parquet")["canonical_fighter_id"]
    )
    assert snapshots.height == 18136
    assert snapshots.select(["canonical_bout_id", "canonical_fighter_id"]).unique().height == 18136
    assert snapshots.group_by("canonical_bout_id").len().select(pl.col("len").eq(2).all()).item()
    assert set(snapshots["canonical_fighter_id"]) <= fighters
    assert set(snapshots["opponent_canonical_fighter_id"]) <= fighters
    assert (
        snapshots.filter(
            pl.col("canonical_fighter_id") == pl.col("opponent_canonical_fighter_id")
        ).height
        == 0
    )
    assert set(snapshots["cutoff_policy_id"]) == {_PREFIGHT_CUTOFF_POLICY}
    long_history = pl.concat(
        [
            bouts.select(
                pl.col("canonical_bout_id"),
                pl.col("fight_date").alias("history_date"),
                pl.col("canonical_fighter_a_id").alias("canonical_fighter_id"),
            ),
            bouts.select(
                pl.col("canonical_bout_id"),
                pl.col("fight_date").alias("history_date"),
                pl.col("canonical_fighter_b_id").alias("canonical_fighter_id"),
            ),
        ]
    )
    expected = (
        snapshots.select(["canonical_bout_id", "canonical_fighter_id", "target_fight_date"])
        .join(long_history, on="canonical_fighter_id", how="left")
        .filter(pl.col("history_date") < pl.col("target_fight_date"))
        .group_by(["canonical_bout_id", "canonical_fighter_id"])
        .len()
        .rename({"len": "expected_prior_bouts"})
    )
    actual = snapshots.join(expected, on=["canonical_bout_id", "canonical_fighter_id"], how="left")
    assert (
        actual.with_columns(pl.col("expected_prior_bouts").fill_null(0))
        .select((pl.col("prior_bouts") == pl.col("expected_prior_bouts")).all())
        .item()
    )


def test_cold_starts_rates_windows_streaks_and_finish_counts_are_explicit() -> None:
    bouts = _synthetic_bouts()
    debut = _synthetic_snapshot(bouts, "b1", "a")
    assert debut["cold_start"] is True
    assert debut["prior_bouts"] == 0 and debut["days_since_previous_bout"] is None
    assert debut["prior_win_rate"] is None and debut["prior_finish_win_rate"] is None
    target = _synthetic_snapshot(bouts, "b4", "a")
    assert (target["prior_bouts"], target["prior_wins"], target["prior_losses"]) == (3, 1, 0)
    assert (target["prior_draws"], target["prior_no_contests"], target["prior_decisive_bouts"]) == (
        1,
        1,
        1,
    )
    assert target["prior_win_rate"] == 1.0 and target["prior_loss_rate"] == 0.0
    assert target["days_since_previous_bout"] == 1
    assert target["prior_bouts_180_days"] == target["prior_bouts_365_days"] == 3
    assert target["recent_five_observed_bouts"] == 3
    assert target["current_win_streak"] == target["current_loss_streak"] == 0
    assert target["current_unbeaten_streak"] == target["current_winless_streak"] == 0
    assert target["prior_knockout_tko_wins"] == 1
    assert target["prior_finish_win_rate"] == 1.0
    assert _PREFIGHT_FEATURE_POLICIES["zero_denominator_rates"] == "null"


def test_same_date_current_future_and_localized_mutations_obey_the_leakage_boundary() -> None:
    bouts = _synthetic_bouts()
    same_date = pl.concat(
        [
            bouts,
            bouts.filter(pl.col("canonical_bout_id") == "b4").with_columns(
                pl.lit("b5").alias("canonical_bout_id")
            ),
        ]
    )
    assert (
        _synthetic_snapshot(same_date, "b4", "a")["prior_bouts"]
        == _synthetic_snapshot(bouts, "b4", "a")["prior_bouts"]
    )
    changed_target = bouts.with_columns(
        pl.when(pl.col("canonical_bout_id") == "b4")
        .then(pl.lit("e"))
        .otherwise(pl.col("winner_canonical_fighter_id"))
        .alias("winner_canonical_fighter_id"),
        pl.when(pl.col("canonical_bout_id") == "b4")
        .then(pl.lit("a"))
        .otherwise(pl.col("loser_canonical_fighter_id"))
        .alias("loser_canonical_fighter_id"),
    )
    assert _synthetic_snapshot(changed_target, "b4", "a") == _synthetic_snapshot(bouts, "b4", "a")
    future = pl.concat(
        [
            bouts,
            pl.DataFrame(
                [("future", date(2030, 1, 1), "a", "z", "a", "z", False, False, "Decision")],
                schema=bouts.schema,
                orient="row",
            ),
        ]
    )
    assert _synthetic_snapshot(future, "b4", "a") == _synthetic_snapshot(bouts, "b4", "a")
    changed_past = bouts.with_columns(
        pl.when(pl.col("canonical_bout_id") == "b1")
        .then(pl.lit("b"))
        .otherwise(pl.col("winner_canonical_fighter_id"))
        .alias("winner_canonical_fighter_id"),
        pl.when(pl.col("canonical_bout_id") == "b1")
        .then(pl.lit("a"))
        .otherwise(pl.col("loser_canonical_fighter_id"))
        .alias("loser_canonical_fighter_id"),
    )
    assert _synthetic_snapshot(changed_past, "b4", "a")["prior_wins"] == 0
    assert _synthetic_snapshot(changed_past, "b4", "e") == _synthetic_snapshot(bouts, "b4", "e")


def test_leakage_schema_provenance_manifest_and_replay(generation: Path, tmp_path: Path) -> None:
    snapshots = _snapshots(generation)
    forbidden = ("odds", "rank", "dif", "sig_str", "total_str", "_td", "_kd", "corner")
    assert not [
        name for name in snapshots.columns if any(value in name.casefold() for value in forbidden)
    ]
    assert snapshots.select(
        pl.all()
        .exclude(
            [
                "days_since_previous_bout",
                "prior_win_rate",
                "prior_loss_rate",
                "recent_five_win_rate",
                "prior_finish_win_rate",
            ]
        )
        .is_not_null()
        .all()
    ).row(0)
    provenance = pl.read_parquet(generation / "m3_normalized_provenance.parquet")
    snapshot_provenance = provenance.filter(
        pl.col("output_artifact") == "m3_prefight_fighter_history.parquet"
    )
    assert snapshot_provenance["output_row_key"].n_unique() == 18136
    assert provenance.select(["output_artifact", "output_row_key"]).unique().height == 150162
    manifest = json.loads((generation / "m3_phase2_manifest.json").read_text(encoding="utf-8"))
    metadata = manifest["artifacts"]["m3_prefight_fighter_history.parquet"]
    assert metadata["row_count"] == 18136
    assert metadata["column_count"] == snapshots.width
    assert (
        metadata["sha256"]
        == sha256((generation / "m3_prefight_fighter_history.parquet").read_bytes()).hexdigest()
    )
    assert manifest["phase_3b1"]["feature_policies"] == _PREFIGHT_FEATURE_POLICIES
    _materialize(tmp_path)
    before = resolve_m3_current_generation(tmp_path)
    hashes = {path.name: sha256(path.read_bytes()).hexdigest() for path in before.iterdir()}
    _materialize(tmp_path)
    assert resolve_m3_current_generation(tmp_path) == before
    assert {path.name: sha256(path.read_bytes()).hexdigest() for path in before.iterdir()} == hashes
    with pytest.raises(RuntimeError, match="injected failure"):
        _materialize(tmp_path, "after_validation_before_commit")
    assert {path.name: sha256(path.read_bytes()).hexdigest() for path in before.iterdir()} == hashes
    assert "m3_prefight_fighter_history.parquet" in {name for name, _ in _PUBLISHED_ARTIFACTS}
    assert _artifact_row_key("m3_prefight_fighter_history.parquet", snapshots.row(0, named=True))
