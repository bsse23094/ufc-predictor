from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import pytest

from ufc_predictor.training.m4_baselines import ACCEPTED_M3_GENERATION_ID
from ufc_predictor.training.m4_opponent_strength import (
    INITIAL_ELO,
    build_pairwise_opponent_strength,
    build_prefight_opponent_strength,
    run_m4_opponent_strength_training,
    swap_phase3b1_rows,
)
from ufc_predictor.training.m4_symmetry import symmetric_probability

ROOT = Path(__file__).parents[2]


def _bout(
    bout_id: str,
    day: str,
    fighter_a: str,
    fighter_b: str,
    *,
    winner: str | None = None,
    draw: bool = False,
    no_contest: bool = False,
) -> dict[str, object]:
    return {
        "canonical_bout_id": bout_id,
        "fight_date": day,
        "canonical_fighter_a_id": fighter_a,
        "canonical_fighter_b_id": fighter_b,
        "winner_canonical_fighter_id": winner,
        "is_no_contest": no_contest,
        "is_draw": draw,
    }


def test_prefight_ratings_are_frozen_by_date_and_row_order_invariant() -> None:
    history = pd.DataFrame(
        [
            _bout("same-b", "2020-01-01", "a", "c", winner="a"),
            _bout("same-a", "2020-01-01", "a", "b", winner="a"),
            _bout("later", "2020-01-02", "a", "d", winner="a"),
        ]
    )
    classes = {"same-a": "lightweight", "same-b": "lightweight", "later": "lightweight"}
    normal = build_prefight_opponent_strength(history, weight_classes=classes)
    reordered = build_prefight_opponent_strength(
        history.sample(frac=1.0, random_state=7), weight_classes=classes
    )
    pd.testing.assert_frame_equal(normal, reordered)
    same_date = normal[normal["fight_date"] == pd.Timestamp("2020-01-01")]
    assert set(same_date["pre_fight_overall_elo"]) == {INITIAL_ELO}
    later = normal[
        (normal["canonical_bout_id"] == "later") & (normal["canonical_fighter_id"] == "a")
    ]
    assert later.iloc[0]["pre_fight_overall_elo"] > INITIAL_ELO
    assert later.iloc[0]["pre_fight_rated_bout_count"] == 2.0


def test_draw_no_contest_weight_class_and_historical_opponent_policy() -> None:
    history = pd.DataFrame(
        [
            _bout("win", "2020-01-01", "a", "b", winner="a"),
            _bout("draw", "2020-01-02", "a", "c", draw=True),
            _bout("nc", "2020-01-03", "a", "d", no_contest=True),
            _bout("later", "2020-01-04", "a", "e", winner="a"),
        ]
    )
    classes = {
        "win": "lightweight",
        "draw": "welterweight",
        "nc": "lightweight",
        "later": "welterweight",
    }
    snapshots = build_prefight_opponent_strength(history, weight_classes=classes)
    draw_a = snapshots[
        (snapshots["canonical_bout_id"] == "draw") & (snapshots["canonical_fighter_id"] == "a")
    ].iloc[0]
    nc_a = snapshots[
        (snapshots["canonical_bout_id"] == "nc") & (snapshots["canonical_fighter_id"] == "a")
    ].iloc[0]
    later_a = snapshots[
        (snapshots["canonical_bout_id"] == "later") & (snapshots["canonical_fighter_id"] == "a")
    ].iloc[0]
    assert draw_a["pre_fight_weight_class_rated_bout_count"] == 0.0
    assert nc_a["pre_fight_rated_bout_count"] == 2.0
    assert later_a["pre_fight_rated_bout_count"] == 2.0  # no-contest did not update/count
    assert later_a["pre_fight_average_opponent_elo_career"] == pytest.approx(INITIAL_ELO)
    assert later_a["pre_fight_weight_class_elo"] == pytest.approx(INITIAL_ELO)


def test_target_snapshots_ignore_current_and_future_outcomes() -> None:
    prefix = [
        _bout("first", "2020-01-01", "a", "b", winner="a"),
        _bout("target", "2020-01-02", "a", "c", winner="a"),
    ]
    changed = pd.DataFrame(
        [
            prefix[0],
            _bout("target", "2020-01-02", "a", "c", winner="c"),
            _bout("future", "2020-01-03", "a", "d", winner="d"),
        ]
    )
    classes = {"first": "lightweight", "target": "lightweight", "future": "lightweight"}
    baseline = build_prefight_opponent_strength(pd.DataFrame(prefix), weight_classes=classes)
    with_future = build_prefight_opponent_strength(changed, weight_classes=classes)
    baseline_target = baseline[baseline["canonical_bout_id"] == "target"].reset_index(drop=True)
    future_target = with_future[with_future["canonical_bout_id"] == "target"].reset_index(drop=True)
    pd.testing.assert_frame_equal(baseline_target, future_target)


def test_draw_updates_and_no_contest_does_not_update() -> None:
    history = pd.DataFrame(
        [
            _bout("win", "2020-01-01", "a", "b", winner="a"),
            _bout("draw", "2020-01-02", "a", "c", draw=True),
            _bout("nc", "2020-01-03", "a", "d", no_contest=True),
            _bout("later", "2020-01-04", "a", "e", winner="a"),
        ]
    )
    snapshots = build_prefight_opponent_strength(
        history, weight_classes={name: "lightweight" for name in history["canonical_bout_id"]}
    )
    draw_a = snapshots.query("canonical_bout_id == 'draw' and canonical_fighter_id == 'a'").iloc[0]
    nc_a = snapshots.query("canonical_bout_id == 'nc' and canonical_fighter_id == 'a'").iloc[0]
    later_a = snapshots.query("canonical_bout_id == 'later' and canonical_fighter_id == 'a'").iloc[
        0
    ]
    assert draw_a["pre_fight_overall_elo"] > INITIAL_ELO
    assert nc_a["pre_fight_overall_elo"] < draw_a["pre_fight_overall_elo"]
    assert nc_a["pre_fight_rated_bout_count"] == 2.0
    assert later_a["pre_fight_overall_elo"] == pytest.approx(nc_a["pre_fight_overall_elo"])
    assert later_a["pre_fight_rated_bout_count"] == 2.0


def test_cold_start_weight_class_isolation_and_historical_opponent_capture() -> None:
    history = pd.DataFrame(
        [
            _bout("first", "2020-01-01", "a", "b", winner="a"),
            _bout("b_later", "2020-01-02", "b", "c", winner="b"),
            _bout("target", "2020-01-03", "a", "d", winner="a"),
            _bout("welter", "2020-01-04", "a", "e", winner="a"),
        ]
    )
    snapshots = build_prefight_opponent_strength(
        history,
        weight_classes={
            "first": "lightweight",
            "b_later": "lightweight",
            "target": "lightweight",
            "welter": "welterweight",
        },
    )
    first_a = snapshots.query("canonical_bout_id == 'first' and canonical_fighter_id == 'a'").iloc[
        0
    ]
    b_later = snapshots.query(
        "canonical_bout_id == 'b_later' and canonical_fighter_id == 'b'"
    ).iloc[0]
    target_a = snapshots.query(
        "canonical_bout_id == 'target' and canonical_fighter_id == 'a'"
    ).iloc[0]
    welter_a = snapshots.query(
        "canonical_bout_id == 'welter' and canonical_fighter_id == 'a'"
    ).iloc[0]
    assert first_a["pre_fight_overall_elo"] == INITIAL_ELO
    assert target_a["pre_fight_average_opponent_elo_career"] == pytest.approx(INITIAL_ELO)
    assert target_a["pre_fight_average_opponent_elo_career"] != b_later["pre_fight_overall_elo"]
    assert welter_a["pre_fight_weight_class_elo"] == INITIAL_ELO
    assert welter_a["pre_fight_current_weight_class_first_bout"] == 1.0


def test_pairwise_swap_mapping_and_symmetrized_probability() -> None:
    history = pd.DataFrame([_bout("one", "2020-01-01", "a", "b", winner="a")])
    snapshots = build_prefight_opponent_strength(history, weight_classes={"one": "lightweight"})
    model_ready = pd.DataFrame(
        [
            {
                "canonical_bout_id": "one",
                "fight_date": "2020-01-01",
                "canonical_fighter_a_id": "a",
                "canonical_fighter_b_id": "b",
                "target_fighter_a_won": 1,
            }
        ]
    )
    model_ready["fight_date"] = pd.to_datetime(model_ready["fight_date"])
    pairwise = build_pairwise_opponent_strength(snapshots, model_ready)
    frame = model_ready.merge(
        pairwise,
        on=["canonical_bout_id", "fight_date", "canonical_fighter_a_id", "canonical_fighter_b_id"],
    )
    features = (
        *(name for name in pairwise.columns if name.startswith(("a_", "b_", "diff_"))),
        "elo_expected_probability_a",
    )
    swapped = swap_phase3b1_rows(
        frame, feature_columns=features, target_column="target_fighter_a_won"
    )
    assert swapped["target_fighter_a_won"].iloc[0] == 0
    assert swapped["a_pre_fight_overall_elo"].iloc[0] == frame["b_pre_fight_overall_elo"].iloc[0]
    assert (
        swapped["diff_pre_fight_overall_elo"].iloc[0]
        == -frame["diff_pre_fight_overall_elo"].iloc[0]
    )
    assert swapped["elo_expected_probability_a"].iloc[0] == pytest.approx(
        1.0 - frame["elo_expected_probability_a"].iloc[0]
    )
    forward, reverse = np.array([0.2, 0.7]), np.array([0.6, 0.3])
    assert np.allclose(
        symmetric_probability(forward, reverse),
        1.0 - symmetric_probability(reverse, forward),
        atol=1e-15,
    )


@pytest.fixture(scope="module")
def phase3b1_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("m4-phase3b1-output")
    run_m4_opponent_strength_training(
        m3_root=ROOT / "data/processed/m3-v6",
        phase1_root=ROOT / "data/processed/m4-baselines",
        phase2_root=ROOT / "data/processed/m4-phase2-symmetry",
        phase3a_root=ROOT / "data/processed/m4-phase3a-xgboost",
        output_root=root,
    )
    return root / ACCEPTED_M3_GENERATION_ID


def test_phase3b1_reuses_phase3a_splits_and_protects_prior_artifacts(phase3b1_output: Path) -> None:
    contract = json.loads((phase3b1_output / "m4_phase3b1_feature_contract.json").read_text())
    manifest = json.loads((phase3b1_output / "m4_phase3b1_training_manifest.json").read_text())
    predictions = pl.read_parquet(phase3b1_output / "m4_phase3b1_predictions.parquet")
    pairwise = pl.read_parquet(phase3b1_output / "m4_phase3b1_pairwise_opponent_strength.parquet")
    phase3a = pl.read_parquet(
        ROOT
        / "data/processed/m4-phase3a-xgboost"
        / ACCEPTED_M3_GENERATION_ID
        / "m4_phase3a_predictions.parquet"
    )
    benchmark = set(
        predictions.filter(pl.col("evaluation_partition") == "inspected_locked_benchmark")[
            "canonical_bout_id"
        ].to_list()
    )
    phase3a_benchmark = set(
        phase3a.filter(pl.col("evaluation_partition") == "locked_benchmark")[
            "canonical_bout_id"
        ].to_list()
    )
    assert benchmark == phase3a_benchmark
    phase3a_folds = pl.read_parquet(
        ROOT
        / "data/processed/m4-phase3a-xgboost"
        / ACCEPTED_M3_GENERATION_ID
        / "m4_phase3a_rolling_folds.parquet"
    )
    control_predictions = predictions.filter(
        (pl.col("evaluation_partition") == "rolling_validation")
        & (pl.col("candidate_id") == "base_130__phase3a_shallow_xgboost")
    )
    for fold_id in phase3a_folds["fold_id"].unique().to_list():
        expected = set(
            phase3a_folds.filter((pl.col("fold_id") == fold_id) & (pl.col("role") == "validation"))[
                "canonical_bout_id"
            ].to_list()
        )
        actual = set(
            control_predictions.filter(pl.col("fold_id") == fold_id)["canonical_bout_id"].to_list()
        )
        assert actual == expected
    assert contract["phase3a_split_identity_verified"] is True
    assert contract["rating_policy_id"].endswith("same_date_batch.v1")
    assert manifest["selection"]["benchmark_excluded"] is True
    assert manifest["selection"]["final_boosting_round_policy"].startswith("median of development")
    assert pairwise["a_pre_fight_average_opponent_elo_career"].null_count() > 0
    for phase, root in {
        "phase1": ROOT / "data/processed/m4-baselines",
        "phase2": ROOT / "data/processed/m4-phase2-symmetry",
        "phase3a": ROOT / "data/processed/m4-phase3a-xgboost",
    }.items():
        for filename, digest in manifest["protected_artifacts_sha256"][phase].items():
            assert (
                digest
                == hashlib.sha256(
                    (root / ACCEPTED_M3_GENERATION_ID / filename).read_bytes()
                ).hexdigest()
            )


def test_phase3b1_replay_is_byte_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "replay"
    kwargs = {
        "m3_root": ROOT / "data/processed/m3-v6",
        "phase1_root": ROOT / "data/processed/m4-baselines",
        "phase2_root": ROOT / "data/processed/m4-phase2-symmetry",
        "phase3a_root": ROOT / "data/processed/m4-phase3a-xgboost",
        "output_root": root,
    }
    run_m4_opponent_strength_training(**kwargs)
    output = root / ACCEPTED_M3_GENERATION_ID
    first = {path.name: path.read_bytes() for path in output.iterdir() if path.is_file()}
    run_m4_opponent_strength_training(**kwargs)
    assert first == {path.name: path.read_bytes() for path in output.iterdir() if path.is_file()}
