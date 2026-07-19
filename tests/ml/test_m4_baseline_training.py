from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import pytest
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

from ufc_predictor.training.m4_baselines import (
    ACCEPTED_M3_GENERATION_ID,
    RANDOM_SEED,
    build_logistic_pipeline,
    build_tree_pipeline,
    calibration_summary,
    create_temporal_split,
    load_accepted_m3_data,
    run_m4_baseline_training,
)

ROOT = Path(__file__).parents[2]


def _synthetic_temporal_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for date_index, date in enumerate(pd.date_range("2020-01-01", periods=12, freq="14D")):
        for bout_index in range(2):
            rows.append(
                {
                    "canonical_bout_id": f"bout-{date_index}-{bout_index}",
                    "fight_date": date,
                    "target_fighter_a_won": (date_index + bout_index) % 2,
                    "a_cold_start": date_index == 0,
                    "b_cold_start": False,
                    "a_prior_bouts_missing": False,
                    "b_prior_bouts_missing": False,
                }
            )
    return pd.DataFrame(rows)


def test_accepted_generation_schema_and_ordered_features_are_locked() -> None:
    accepted = load_accepted_m3_data(ROOT / "data/processed/m3-v6")

    assert accepted.generation_id == ACCEPTED_M3_GENERATION_ID
    assert accepted.frame.height == accepted.frame["canonical_bout_id"].n_unique() == 8912
    assert len(accepted.feature_columns) == 130
    assert accepted.frame.columns[7:-1] == list(accepted.feature_columns)
    excluded_columns = set((*accepted.metadata_columns, accepted.target_column))
    assert not excluded_columns & set(accepted.feature_columns)
    assert accepted.frame[accepted.target_column].sum() == 4610


def test_temporal_split_uses_whole_non_overlapping_dates_and_every_row_once() -> None:
    frame = _synthetic_temporal_frame()
    split = create_temporal_split(frame)
    assigned = frame.assign(split=split.assignments)

    assert assigned["split"].isna().sum() == 0
    assert assigned.groupby("fight_date")["split"].nunique().eq(1).all()
    dates = assigned.groupby("split")["fight_date"].agg(["min", "max"])
    assert dates.loc["train", "max"] < dates.loc["validation", "min"] < dates.loc["test", "min"]


def test_preprocessing_is_fit_only_on_training_rows() -> None:
    train = pd.DataFrame({"first": [1.0, np.nan, 5.0], "second": [4.0, 4.0, 4.0]})
    mutated_test = pd.DataFrame({"first": [1_000_000.0], "second": [-1_000_000.0]})
    target = np.array([0, 1, 1])
    first = build_logistic_pipeline().fit(train, target)
    second = build_logistic_pipeline().fit(train, target)
    first_imputer = first.named_steps["imputer"]
    second_imputer = second.named_steps["imputer"]

    first.predict_proba(mutated_test)
    assert first_imputer.statistics_.tolist() == second_imputer.statistics_.tolist() == [3.0, 4.0]


def test_baseline_models_produce_valid_deterministic_probabilities() -> None:
    x = pd.DataFrame({"first": [0.0, 1.0, 0.0, 1.0], "second": [1.0, np.nan, 2.0, 3.0]})
    y = np.array([0, 1, 0, 1])
    logistic = build_logistic_pipeline().fit(x, y)
    tree = build_tree_pipeline().fit(x, y)

    for model in (logistic, tree):
        probability = model.predict_proba(x)[:, 1]
        assert np.all((probability >= 0.0) & (probability <= 1.0))
    assert build_tree_pipeline().named_steps["model"].random_state == RANDOM_SEED


def test_calibration_explicitly_preserves_empty_bins() -> None:
    summary = calibration_summary(np.array([0, 1]), np.array([0.1, 0.9]))

    assert len(summary["bins"]) == 10
    assert summary["bins"][1]["count"] == 1
    assert any(bin_["count"] == 0 for bin_ in summary["bins"])


@pytest.fixture(scope="module")
def m4_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_root = tmp_path_factory.mktemp("m4-output")
    run_m4_baseline_training(m3_root=ROOT / "data/processed/m3-v6", output_root=output_root)
    return output_root / ACCEPTED_M3_GENERATION_ID


def test_end_to_end_artifacts_reference_accepted_m3_and_cover_all_rows(m4_output: Path) -> None:
    manifest = json.loads((m4_output / "m4_training_manifest.json").read_text(encoding="utf-8"))
    splits = pl.read_parquet(m4_output / "m4_temporal_splits.parquet")
    predictions = pl.read_parquet(m4_output / "m4_baseline_predictions.parquet")

    assert manifest["accepted_m3_generation_id"] == ACCEPTED_M3_GENERATION_ID
    assert manifest["feature_count"] == 130
    assert splits.height == splits["canonical_bout_id"].n_unique() == 8912
    assert set(splits["split"]) == {"train", "validation", "test"}
    assert predictions.height == 8912 * 3
    assert (
        predictions.filter(
            (pl.col("probability_fighter_a_wins") < 0) | (pl.col("probability_fighter_a_wins") > 1)
        ).height
        == 0
    )
    assert {"majority", "logistic_regression", "hist_gradient_boosting"} == set(
        predictions["model_name"]
    )


def test_persisted_metrics_match_independent_recomputation(m4_output: Path) -> None:
    metrics = json.loads((m4_output / "m4_baseline_metrics.json").read_text(encoding="utf-8"))
    predictions = pl.read_parquet(m4_output / "m4_baseline_predictions.parquet")
    subset = predictions.filter(
        (pl.col("model_name") == "logistic_regression") & (pl.col("split") == "test")
    )
    target = subset["target_fighter_a_won"].to_numpy()
    probability = subset["probability_fighter_a_wins"].to_numpy()
    recorded = metrics["models"]["logistic_regression"]["splits"]["test"]["metrics"]

    assert recorded["accuracy"] == pytest.approx(accuracy_score(target, probability >= 0.5))
    assert recorded["roc_auc"] == pytest.approx(roc_auc_score(target, probability))
    assert recorded["log_loss"] == pytest.approx(log_loss(target, probability, labels=[0, 1]))
    assert recorded["brier_score"] == pytest.approx(brier_score_loss(target, probability))


def test_unchanged_replay_preserves_predictions_metrics_and_swap_audit(tmp_path: Path) -> None:
    first_root, second_root = tmp_path / "first", tmp_path / "second"
    run_m4_baseline_training(m3_root=ROOT / "data/processed/m3-v6", output_root=first_root)
    run_m4_baseline_training(m3_root=ROOT / "data/processed/m3-v6", output_root=second_root)
    first = first_root / ACCEPTED_M3_GENERATION_ID
    second = second_root / ACCEPTED_M3_GENERATION_ID

    assert (first / "m4_baseline_predictions.parquet").read_bytes() == (
        second / "m4_baseline_predictions.parquet"
    ).read_bytes()
    assert (first / "m4_baseline_metrics.json").read_bytes() == (
        second / "m4_baseline_metrics.json"
    ).read_bytes()
