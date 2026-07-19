from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import polars as pl
import pytest

from ufc_predictor.training.m4_baselines import ACCEPTED_M3_GENERATION_ID, load_accepted_m3_data
from ufc_predictor.training.m4_symmetry import swap_m4_rows, symmetric_probability
from ufc_predictor.training.m4_xgboost import (
    create_rolling_temporal_folds,
    predefined_xgboost_candidates,
    run_m4_xgboost_training,
    select_xgboost_candidate,
)

ROOT = Path(__file__).parents[2]
FEATURES = ("a_value", "b_value", "diff_value", "a_value_missing", "b_value_missing")


def _synthetic_development() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for day, date in enumerate(pd.date_range("2010-01-01", periods=20, freq="14D")):
        for bout in range(2):
            rows.append(
                {
                    "canonical_bout_id": f"bout-{day}-{bout}",
                    "fight_date": date,
                    "target_fighter_a_won": (day + bout) % 2,
                }
            )
    return pd.DataFrame(rows)


def _aggregate(
    *, log_loss_value: float, brier: float, auc: float, std: float, error: float
) -> dict[str, Any]:
    return {
        "mean_log_loss": log_loss_value,
        "mean_brier_score": brier,
        "mean_roc_auc": auc,
        "std_log_loss": std,
        "mean_raw_corner_swap_error": error,
    }


def test_rolling_folds_are_expanding_distinct_date_and_development_only() -> None:
    development = _synthetic_development()
    folds = create_rolling_temporal_folds(development)

    assert len(folds) == 3
    assert set().union(
        *(set(fold.train_positions) | set(fold.validation_positions) for fold in folds)
    ) == set(range(len(development)))
    for fold in folds:
        train_dates = set(development.iloc[list(fold.train_positions)]["fight_date"])
        validation_dates = set(development.iloc[list(fold.validation_positions)]["fight_date"])
        assert not train_dates & validation_dates
        assert max(train_dates) < min(validation_dates)
        assert development.iloc[list(fold.validation_positions)]["canonical_bout_id"].is_unique


def test_swap_contract_complements_target_and_preserves_missingness_semantics() -> None:
    original = pd.DataFrame(
        {
            "a_value": [2.0, np.nan],
            "b_value": [5.0, 7.0],
            "diff_value": [-3.0, np.nan],
            "a_value_missing": [False, True],
            "b_value_missing": [False, False],
            "target_fighter_a_won": [1, 0],
        }
    )
    swapped = swap_m4_rows(original, feature_columns=FEATURES)

    assert swapped["target_fighter_a_won"].tolist() == [0, 1]
    assert swapped["a_value"].tolist() == [5.0, 7.0]
    assert swapped["b_value_missing"].tolist() == [False, True]
    assert swapped["diff_value"].iloc[0] == 3.0
    assert pd.isna(swapped["diff_value"].iloc[1])


def test_symmetrized_probability_is_exactly_complementary() -> None:
    forward = np.array([0.1, 0.3, 0.8])
    swapped = np.array([0.4, 0.6, 0.2])

    assert np.allclose(
        symmetric_probability(forward, swapped),
        1.0 - symmetric_probability(swapped, forward),
        atol=1e-15,
        rtol=0.0,
    )


def test_candidate_selection_cannot_observe_benchmark_outcomes() -> None:
    candidates = predefined_xgboost_candidates()
    aggregates = {
        candidate.candidate_id: _aggregate(
            log_loss_value=0.68 + index / 1000,
            brier=0.24,
            auc=0.61,
            std=0.01,
            error=0.001,
        )
        for index, candidate in enumerate(candidates)
    }
    selected, policy = select_xgboost_candidate(aggregates, candidates)
    mutated_benchmark_targets = np.array([1, 0, 1, 1, 0])

    assert selected == candidates[0].candidate_id
    assert policy["benchmark_test_excluded"] is True
    assert mutated_benchmark_targets.sum() == 3
    assert select_xgboost_candidate(aggregates, candidates)[0] == selected


@pytest.fixture(scope="module")
def phase3a_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("m4-phase3a-output")
    run_m4_xgboost_training(
        m3_root=ROOT / "data/processed/m3-v6",
        phase1_root=ROOT / "data/processed/m4-baselines",
        phase2_root=ROOT / "data/processed/m4-phase2-symmetry",
        output_root=root,
    )
    return root / ACCEPTED_M3_GENERATION_ID


def test_phase3a_artifacts_are_fold_safe_and_registered(phase3a_output: Path) -> None:
    folds = pl.read_parquet(phase3a_output / "m4_phase3a_rolling_folds.parquet")
    predictions = pl.read_parquet(phase3a_output / "m4_phase3a_predictions.parquet")
    importance = pl.read_parquet(phase3a_output / "m4_phase3a_feature_importance.parquet")
    contract = json.loads((phase3a_output / "m4_phase3a_feature_contract.json").read_text())
    manifest = json.loads((phase3a_output / "m4_phase3a_training_manifest.json").read_text())
    accepted = load_accepted_m3_data(ROOT / "data/processed/m3-v6")

    assert contract["ordered_feature_columns"] == list(accepted.feature_columns)
    assert contract["feature_count"] == 130
    assert contract["forbidden_feature_check"]["forbidden_feature_count"] == 0
    assert set(importance["feature_name"]) == set(accepted.feature_columns)
    validation_folds = folds.filter(pl.col("role") == "validation")
    assert validation_folds.height > 0
    validation_last_date = pd.Timestamp(cast(Any, validation_folds["fight_date"].max()))
    benchmark_dates = predictions.filter(pl.col("evaluation_partition") == "locked_benchmark")[
        "fight_date"
    ]
    assert validation_last_date.date().isoformat() == "2023-11-11"
    assert len(benchmark_dates) == 1337
    assert pd.Timestamp(cast(Any, benchmark_dates.min())).date().isoformat() == "2023-11-18"
    assert predictions.select(
        ((pl.col("symmetric_probability") >= 0) & (pl.col("symmetric_probability") <= 1)).all()
    ).item()
    assert manifest["locked_benchmark_period"]["rows"] == 1337


def test_phase3a_replay_is_deterministic_and_preserves_prior_artifacts(tmp_path: Path) -> None:
    protected_directories = (
        ROOT / "data/processed/m4-baselines" / ACCEPTED_M3_GENERATION_ID,
        ROOT / "data/processed/m4-phase2-symmetry" / ACCEPTED_M3_GENERATION_ID,
    )
    protected = {
        directory.name + path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for directory in protected_directories
        for path in directory.iterdir()
        if path.is_file()
    }
    root = tmp_path / "replay"
    run_m4_xgboost_training(
        m3_root=ROOT / "data/processed/m3-v6",
        phase1_root=ROOT / "data/processed/m4-baselines",
        phase2_root=ROOT / "data/processed/m4-phase2-symmetry",
        output_root=root,
    )
    output = root / ACCEPTED_M3_GENERATION_ID
    first = {path.name: path.read_bytes() for path in output.iterdir() if path.is_file()}
    run_m4_xgboost_training(
        m3_root=ROOT / "data/processed/m3-v6",
        phase1_root=ROOT / "data/processed/m4-baselines",
        phase2_root=ROOT / "data/processed/m4-phase2-symmetry",
        output_root=root,
    )

    assert first == {path.name: path.read_bytes() for path in output.iterdir() if path.is_file()}
    assert protected == {
        directory.name + path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for directory in protected_directories
        for path in directory.iterdir()
        if path.is_file()
    }
