from __future__ import annotations

import json
from datetime import date
from hashlib import sha256
from pathlib import Path

import polars as pl
import pytest

from ufc_predictor.m3_materialization import (
    _PREFIGHT_PERFORMANCE_SCHEMA,
    _completed_duration_seconds,
    _prefight_performance_rows,
    materialize_m3_v6,
    resolve_m3_current_generation,
)

ROOT = Path(__file__).parents[2]
V6_DIR = ROOT / "data/quarantine/reviews/m3-corrections-v6"
ULTIMATE = ROOT / "data/incoming/ultimate-ufc-dataset/ufc-master.csv"
DATALAB = ROOT / "data/incoming/ufc-datalab/3268146c05211de9deab8b9b4c0bb4a954815f0b/stats_raw.csv"
METRICS = (
    "knockdowns",
    "significant_strikes_landed",
    "significant_strikes_attempted",
    "total_strikes_landed",
    "total_strikes_attempted",
    "takedowns_landed",
    "takedowns_attempted",
    "submission_attempts",
    "reversals",
    "control_seconds",
)


def _performance_row(
    bout: str, fight_date: date, fighter: str, opponent: str, **values: int | None
) -> dict[str, object]:
    row: dict[str, object] = {
        "canonical_bout_id": bout,
        "canonical_fighter_id": fighter,
        "opponent_canonical_fighter_id": opponent,
        "fight_date": fight_date,
    }
    row.update({metric: 0 for metric in METRICS})
    row.update(values)
    return row


def _performance(
    *,
    second_date: date = date(2020, 1, 2),
    a_second: dict[str, int | None] | None = None,
    a_third: dict[str, int | None] | None = None,
) -> pl.DataFrame:
    return pl.DataFrame(
        [
            _performance_row(
                "b1",
                date(2020, 1, 1),
                "a",
                "b",
                significant_strikes_landed=6,
                significant_strikes_attempted=12,
                total_strikes_landed=8,
                total_strikes_attempted=16,
                takedowns_landed=1,
                takedowns_attempted=2,
                submission_attempts=1,
                control_seconds=30,
            ),
            _performance_row(
                "b1",
                date(2020, 1, 1),
                "b",
                "a",
                significant_strikes_landed=3,
                significant_strikes_attempted=6,
                total_strikes_landed=4,
                total_strikes_attempted=8,
                takedowns_landed=0,
                takedowns_attempted=1,
            ),
            _performance_row("b2", second_date, "a", "c", **(a_second or {})),
            _performance_row(
                "b2",
                second_date,
                "c",
                "a",
                significant_strikes_landed=2,
                significant_strikes_attempted=4,
                total_strikes_landed=3,
                total_strikes_attempted=6,
                takedowns_landed=1,
                takedowns_attempted=2,
            ),
            _performance_row("b3", date(2020, 1, 3), "a", "d", **(a_third or {})),
            _performance_row("b3", date(2020, 1, 3), "d", "a"),
        ]
    )


def _historical(*, second_round: int | None = 2, second_time: str | None = "2:00") -> pl.DataFrame:
    return pl.DataFrame(
        [
            ("b1", 1, "1:00", 99),
            ("b2", second_round, second_time, 99),
            ("b3", 3, "5:00", 99),
        ],
        schema=[
            "canonical_bout_id",
            "canonical_finish_round",
            "canonical_finish_time",
            "scheduled_rounds",
        ],
        orient="row",
    )


def _snapshot(
    performance: pl.DataFrame, historical: pl.DataFrame, bout: str = "b3"
) -> dict[str, object]:
    return next(
        row
        for row in _prefight_performance_rows(performance, historical)
        if row["canonical_bout_id"] == bout and row["canonical_fighter_id"] == "a"
    )


def test_accuracy_defense_zero_and_missing_denominators_are_safe() -> None:
    normal = _snapshot(_performance(), _historical())
    assert normal["career_significant_strike_accuracy"] == pytest.approx(0.5)
    # The two prior opponents attempted 6 and 4 significant strikes and landed 3 and 2.
    assert normal["career_significant_strike_defense"] == pytest.approx(0.5)

    zero = _snapshot(
        _performance(
            a_second={"significant_strikes_landed": 0, "significant_strikes_attempted": 0}
        ),
        _historical(),
        "b2",
    )
    assert zero["career_significant_strike_accuracy"] == pytest.approx(0.5)
    only_zero = _snapshot(
        _performance().filter(pl.col("canonical_bout_id") != "b1"),
        _historical().filter(pl.col("canonical_bout_id") != "b1"),
    )
    assert only_zero["career_significant_strike_accuracy"] is None
    only_missing = _snapshot(
        _performance(
            a_second={
                "significant_strikes_landed": None,
                "significant_strikes_attempted": None,
            }
        ).filter(pl.col("canonical_bout_id") != "b1"),
        _historical().filter(pl.col("canonical_bout_id") != "b1"),
    )
    assert only_missing["career_significant_strike_accuracy"] is None

    missing = _snapshot(
        _performance(
            a_second={"significant_strikes_landed": None, "significant_strikes_attempted": None}
        ),
        _historical(),
        "b2",
    )
    assert missing["career_significant_strike_accuracy"] == pytest.approx(0.5)

    opponent_zero = _performance()
    opponent_zero = opponent_zero.with_columns(
        pl.when((pl.col("canonical_bout_id") == "b1") & (pl.col("canonical_fighter_id") == "b"))
        .then(pl.lit(0))
        .otherwise(pl.col("significant_strikes_attempted"))
        .alias("significant_strikes_attempted"),
        pl.when((pl.col("canonical_bout_id") == "b1") & (pl.col("canonical_fighter_id") == "b"))
        .then(pl.lit(0))
        .otherwise(pl.col("significant_strikes_landed"))
        .alias("significant_strikes_landed"),
    )
    assert (
        _snapshot(opponent_zero, _historical(), "b2")["career_significant_strike_defense"] is None
    )
    opponent_missing = opponent_zero.with_columns(
        pl.when((pl.col("canonical_bout_id") == "b1") & (pl.col("canonical_fighter_id") == "b"))
        .then(pl.lit(None))
        .otherwise(pl.col("significant_strikes_attempted"))
        .alias("significant_strikes_attempted")
    )
    assert (
        _snapshot(opponent_missing, _historical(), "b2")["career_significant_strike_defense"]
        is None
    )


def test_invalid_landed_attempts_fail_and_observed_zero_is_not_missing() -> None:
    invalid = _performance(
        a_second={"significant_strikes_landed": 1, "significant_strikes_attempted": 0}
    )
    with pytest.raises(ValueError, match="exceeds attempts"):
        _snapshot(invalid, _historical())
    row = _snapshot(_performance(a_second={"control_seconds": None}), _historical())
    assert row["career_control_seconds_observed_count"] == 1
    assert row["career_control_seconds_missing_count"] == 1
    assert row["career_control_seconds_sum"] == 30


def test_strict_cutoff_same_date_and_mutations_are_localized() -> None:
    baseline = _snapshot(_performance(), _historical())
    same_date = _snapshot(_performance(second_date=date(2020, 1, 3)), _historical())
    assert same_date["eligible_prior_performance_bouts"] == 1
    target_changed = _snapshot(
        _performance(
            a_third={"significant_strikes_landed": 999, "significant_strikes_attempted": 999}
        ),
        _historical(),
    )
    assert target_changed == baseline
    changed_target_duration = _historical().with_columns(
        pl.when(pl.col("canonical_bout_id") == "b3")
        .then(pl.lit("1:00"))
        .otherwise(pl.col("canonical_finish_time"))
        .alias("canonical_finish_time")
    )
    assert _snapshot(_performance(), changed_target_duration) == baseline
    future = pl.concat(
        [
            _performance(),
            pl.DataFrame(
                [
                    _performance_row("future", date(2030, 1, 1), "a", "z"),
                    _performance_row("future", date(2030, 1, 1), "z", "a"),
                ]
            ),
        ]
    )
    future_history = pl.concat(
        [
            _historical(),
            pl.DataFrame([("future", 3, "5:00", 5)], schema=_historical().schema, orient="row"),
        ]
    )
    assert _snapshot(future, future_history) == baseline
    changed_past = _performance().with_columns(
        pl.when((pl.col("canonical_bout_id") == "b1") & (pl.col("canonical_fighter_id") == "a"))
        .then(pl.lit(60))
        .otherwise(pl.col("significant_strikes_landed"))
        .alias("significant_strikes_landed"),
        pl.when((pl.col("canonical_bout_id") == "b1") & (pl.col("canonical_fighter_id") == "a"))
        .then(pl.lit(60))
        .otherwise(pl.col("significant_strikes_attempted"))
        .alias("significant_strikes_attempted"),
    )
    assert (
        _snapshot(changed_past, _historical())["career_significant_strike_accuracy"]
        != baseline["career_significant_strike_accuracy"]
    )
    unrelated = _snapshot(
        pl.concat(
            [
                _performance(),
                pl.DataFrame(
                    [
                        _performance_row("u", date(2019, 1, 1), "x", "y"),
                        _performance_row("u", date(2019, 1, 1), "y", "x"),
                    ]
                ),
            ]
        ),
        pl.concat(
            [
                _historical(),
                pl.DataFrame([("u", 1, "1:00", 3)], schema=_historical().schema, orient="row"),
            ]
        ),
    )
    assert unrelated == baseline


def test_pace_uses_summed_valid_completed_duration_and_not_scheduled_duration() -> None:
    row = _snapshot(
        _performance(
            a_second={
                "significant_strikes_landed": 12,
                "significant_strikes_attempted": 12,
                "takedowns_attempted": 4,
                "submission_attempts": 2,
                "control_seconds": 90,
            }
        ),
        _historical(),
    )
    assert row["career_valid_duration_observed_count"] == 2
    assert row["career_excluded_duration_prior_bout_count"] == 0
    assert row["career_significant_strikes_landed_per_minute"] == pytest.approx(18 * 60 / 480)
    assert row["career_takedown_attempts_per_15_minutes"] == pytest.approx(6 * 900 / 480)
    assert row["career_submission_attempts_per_15_minutes"] == pytest.approx(3 * 900 / 480)
    assert row["career_control_seconds_per_fight_minute"] == pytest.approx(120 / 480)

    excluded = _snapshot(_performance(), _historical(second_round=None, second_time=None))
    assert excluded["career_valid_duration_observed_count"] == 1
    assert excluded["career_excluded_duration_prior_bout_count"] == 1
    assert excluded["career_significant_strikes_landed_per_minute"] == pytest.approx(6.0)
    assert (
        _completed_duration_seconds({"canonical_finish_round": 1, "canonical_finish_time": "0:00"})
        is None
    )
    assert (
        _completed_duration_seconds({"canonical_finish_round": -1, "canonical_finish_time": "1:00"})
        is None
    )
    assert (
        _completed_duration_seconds(
            {"canonical_finish_round": 1, "canonical_finish_time": "broken"}
        )
        is None
    )
    # The deliberately absurd scheduled value is ignored: no finishing duration means no pace.
    assert (
        _completed_duration_seconds(
            {"canonical_finish_round": None, "canonical_finish_time": None, "scheduled_rounds": 99}
        )
        is None
    )


def test_synthetic_output_is_deterministic_finite_and_has_no_forbidden_fields(
    tmp_path: Path,
) -> None:
    performance = _performance(a_second={"control_seconds": None})
    historical = _historical()
    rows = _prefight_performance_rows(performance, historical)
    shuffled = _prefight_performance_rows(
        performance.sample(fraction=1, shuffle=True, seed=7),
        historical.sample(fraction=1, shuffle=True, seed=9),
    )
    first = pl.DataFrame(rows, schema=_PREFIGHT_PERFORMANCE_SCHEMA).sort(
        ["target_fight_date", "canonical_bout_id", "canonical_fighter_id"]
    )
    second = pl.DataFrame(shuffled, schema=_PREFIGHT_PERFORMANCE_SCHEMA).sort(
        ["target_fight_date", "canonical_bout_id", "canonical_fighter_id"]
    )
    first_path, second_path = tmp_path / "first.parquet", tmp_path / "second.parquet"
    first.write_parquet(first_path)
    second.write_parquet(second_path)
    assert (
        sha256(first_path.read_bytes()).hexdigest() == sha256(second_path.read_bytes()).hexdigest()
    )
    rates = [name for name in first.columns if name.endswith(("_accuracy", "_defense"))]
    assert first.select(
        pl.all_horizontal([pl.col(name).drop_nulls().is_finite().all() for name in rates])
    ).row(0)
    assert first.select(
        pl.all_horizontal(
            [
                ((pl.col(name).drop_nulls() >= 0) & (pl.col(name).drop_nulls() <= 1)).all()
                for name in rates
            ]
        )
    ).row(0)
    forbidden = ("odds", "rank", "profile", "difference", "source_order", "target_bout")
    assert not [name for name in first.columns if any(term in name for term in forbidden)]


@pytest.fixture(scope="module")
def generation(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("m3-phase3b2b")
    materialize_m3_v6(ultimate_csv=ULTIMATE, datalab_csv=DATALAB, v6_dir=V6_DIR, output_dir=output)
    return resolve_m3_current_generation(output)


def test_production_phase_3b2b_invariants_and_manifest(generation: Path) -> None:
    snapshots = pl.read_parquet(generation / "m3_prefight_performance_history.parquet")
    performance = pl.read_parquet(generation / "m3_fighter_bout_performance.parquet")
    provenance = pl.read_parquet(generation / "m3_normalized_provenance.parquet")
    assert snapshots.height == 18136
    assert snapshots.select(["canonical_bout_id", "canonical_fighter_id"]).unique().height == 18136
    assert snapshots.group_by("canonical_bout_id").len().select(pl.col("len").eq(2).all()).item()
    assert (
        provenance.filter(pl.col("output_artifact") == "m3_prefight_performance_history.parquet")[
            "output_row_key"
        ].n_unique()
        == 18136
    )
    assert provenance.select(["output_artifact", "output_row_key"]).unique().height == 150162
    rates = [name for name in snapshots.columns if name.endswith(("_accuracy", "_defense"))]
    assert (
        snapshots.select(
            pl.any_horizontal(
                [
                    pl.col(name).is_not_null() & ~pl.col(name).is_finite()
                    for name in snapshots.columns
                    if snapshots.schema[name] == pl.Float64
                ]
            ).any()
        ).item()
        is False
    )
    assert (
        snapshots.select(
            pl.any_horizontal(
                [
                    pl.col(name).is_not_null() & ((pl.col(name) < 0) | (pl.col(name) > 1))
                    for name in rates
                ]
            ).any()
        ).item()
        is False
    )
    expected = (
        performance.select(
            ["canonical_bout_id", "canonical_fighter_id", pl.col("fight_date").alias("target")]
        )
        .join(
            performance.select(["canonical_fighter_id", pl.col("fight_date").alias("prior")]),
            on="canonical_fighter_id",
            how="left",
        )
        .filter(pl.col("prior") < pl.col("target"))
        .group_by(["canonical_bout_id", "canonical_fighter_id"])
        .len()
        .rename({"len": "expected"})
    )
    assert (
        snapshots.join(expected, on=["canonical_bout_id", "canonical_fighter_id"], how="left")
        .with_columns(pl.col("expected").fill_null(0))
        .select((pl.col("eligible_prior_performance_bouts") == pl.col("expected")).all())
        .item()
    )
    manifest = json.loads((generation / "m3_phase2_manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase_3b2b"]["cutoff_policy"] == "strict_fight_date_lt_target_date_v1"
    assert manifest["artifacts"]["m3_prefight_performance_history.parquet"]["row_count"] == 18136
    accepted = dict(
        zip(
            (
                "m3_semantic_bout_groups.parquet",
                "m3_source_bout_crosswalk.parquet",
                "m3_canonical_fighters.parquet",
                "m3_canonical_fighter_aliases.parquet",
                "m3_taxonomy_authorities.parquet",
                "m3_bout_reconciliation.parquet",
                "m3_reviewed_exclusions.parquet",
                "m3_duplicate_collapses.parquet",
                "m3_canonical_historical_bouts.parquet",
                "m3_prefight_fighter_history.parquet",
                "m3_fighter_bout_performance.parquet",
            ),
            (
                "7561e3950e86ad4bea4c18dd0293f157c006ca315763ddfa22a9aa91a1936bb8",
                "170842cc7822f66547f1626a24b709a784d562ba3f1b133519372c811612fdb3",
                "f66412e3cd3489c657a68c341d8fe7a324264bd8659f080dc40d50ccaec91c89",
                "57fc90bec39b9d5b90d2cf535a997666b8c8cd9a0cd77183116d5197f3dfda8c",
                "2a418a84ca15bea62069bde976a627f38228fe76de0ea4b48c6d0d5a44442372",
                "749930e613ee021514a0eef8a7b22bd2a37e283e90a5433d0674d796c4821be8",
                "3d7becb0cdc2658e3974dbddb5d823e97264d3054eeb035ba1a33768ac39e8b4",
                "8f81c701828ba4fca99d3dbcdd1f046e652001bf304fa268db3c250c18784b99",
                "178bc227a890dde347888ad1d22eff89d09759ca436d239c9dd494b87334b2cc",
                "602dd7fbf4ec01ea9b17c570e1f58764101d9f532a42b2a1389320d631566fe8",
                "d16cb22d59220043dcc41349186c3e3a42624bbc36002ccb6351fc5aa413cbb6",
            ),
            strict=True,
        )
    )
    assert {
        name: sha256((generation / name).read_bytes()).hexdigest() for name in accepted
    } == accepted
