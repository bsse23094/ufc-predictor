from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import polars as pl
import pytest

from ufc_predictor.training.m4_baselines import (
    ACCEPTED_M3_GENERATION_ID,
    build_logistic_pipeline,
    create_temporal_split,
    load_accepted_m3_data,
)
from ufc_predictor.training.m4_symmetry import (
    augment_training_rows,
    run_m4_symmetry_training,
    select_phase2_candidate,
    swap_m4_rows,
    symmetric_probability,
)

ROOT = Path(__file__).parents[2]
FEATURES = (
    "a_rate",
    "b_rate",
    "diff_rate",
    "a_rate_missing",
    "b_rate_missing",
)


def _synthetic_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "canonical_bout_id": ["one", "two"],
            "fight_date": pd.to_datetime(["2020-01-01", "2020-01-15"]),
            "canonical_fighter_a_id": ["a1", "a2"],
            "canonical_fighter_b_id": ["b1", "b2"],
            "a_rate": [2.0, np.nan],
            "b_rate": [5.0, 7.0],
            "diff_rate": [-3.0, np.nan],
            "a_rate_missing": [False, True],
            "b_rate_missing": [False, False],
            "target_fighter_a_won": [1, 0],
        }
    )


def _validation_report(
    *, log_loss_value: float, brier: float, auc: float, error: float, complexity: int
) -> dict[str, Any]:
    return {
        "metrics": {"log_loss": log_loss_value, "brier_score": brier, "roc_auc": auc},
        "corner_swap_audit": {"mean_absolute_complement_error": error},
        "complexity_rank": complexity,
    }


def test_swap_complements_target_and_exchanges_all_pairwise_values() -> None:
    original = _synthetic_rows()
    swapped = swap_m4_rows(original, feature_columns=FEATURES)

    assert swapped["target_fighter_a_won"].tolist() == [0, 1]
    assert swapped["a_rate"].tolist() == [5.0, 7.0]
    assert swapped["b_rate"].iloc[0] == 2.0
    assert swapped["a_rate_missing"].tolist() == [False, False]
    assert swapped["b_rate_missing"].tolist() == [False, True]
    assert swapped["diff_rate"].iloc[0] == 3.0
    assert pd.isna(swapped["diff_rate"].iloc[1])
    assert swapped["canonical_fighter_a_id"].tolist() == ["b1", "b2"]


def test_double_swap_restores_original_pairwise_features_and_target() -> None:
    original = _synthetic_rows()
    restored = swap_m4_rows(
        swap_m4_rows(original, feature_columns=FEATURES), feature_columns=FEATURES
    )

    pd.testing.assert_frame_equal(restored[original.columns], original)


def test_augmentation_is_train_only_and_exactly_doubles_rows() -> None:
    train, validation, test = (
        _synthetic_rows().iloc[:1],
        _synthetic_rows().iloc[1:],
        _synthetic_rows(),
    )
    augmented = augment_training_rows(
        train, feature_columns=FEATURES, target_column="target_fighter_a_won"
    )

    assert len(augmented) == 2 * len(train)
    assert set(augmented["augmentation_variant"]) == {"canonical", "swapped"}
    assert set(augmented["canonical_bout_id"]) == set(train["canonical_bout_id"])
    assert not set(validation["canonical_bout_id"]) & set(augmented["canonical_bout_id"])
    assert not set(test.iloc[1:]["canonical_bout_id"]) & set(augmented["canonical_bout_id"])


def test_symmetric_inference_is_complementary_at_numerical_precision() -> None:
    forward = np.array([0.11, 0.80, 0.47])
    swapped = np.array([0.31, 0.22, 0.58])

    canonical = symmetric_probability(forward, swapped)
    opposite_corner = symmetric_probability(swapped, forward)

    assert np.allclose(canonical, 1.0 - opposite_corner, atol=1e-15, rtol=0.0)


def test_selection_uses_validation_only_and_leaves_fitted_preprocessing_unchanged() -> None:
    train = pd.DataFrame({"a": [1.0, np.nan, 5.0], "b": [4.0, 4.0, 4.0]})
    fitted = build_logistic_pipeline().fit(train, np.array([0, 1, 1]))
    before = fitted.named_steps["imputer"].statistics_.copy()
    validation = {
        "phase1_logistic_forward": _validation_report(
            log_loss_value=0.67, brier=0.24, auc=0.62, error=0.05, complexity=1
        ),
        "symmetrized": _validation_report(
            log_loss_value=0.66, brier=0.23, auc=0.63, error=0.0, complexity=2
        ),
    }
    selected, _ = select_phase2_candidate(validation)
    altered_validation = dict(validation)
    altered_validation["symmetrized"] = _validation_report(
        log_loss_value=0.80, brier=0.23, auc=0.63, error=0.0, complexity=2
    )
    altered_selected, _ = select_phase2_candidate(altered_validation)

    assert selected == "symmetrized"
    assert altered_selected == "phase1_logistic_forward"
    assert fitted.named_steps["imputer"].statistics_.tolist() == before.tolist() == [3.0, 4.0]


def test_temporal_split_does_not_allow_a_bout_to_cross_partitions() -> None:
    frame = pd.DataFrame(
        {
            "canonical_bout_id": [f"bout-{index}" for index in range(12)],
            "fight_date": pd.date_range("2020-01-01", periods=12, freq="7D"),
        }
    )
    split = create_temporal_split(frame)

    assert split.assignments.groupby(frame["canonical_bout_id"]).nunique().eq(1).all()


@pytest.fixture(scope="module")
def phase2_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_root = tmp_path_factory.mktemp("m4-phase2-output")
    run_m4_symmetry_training(
        m3_root=ROOT / "data/processed/m3-v6",
        phase1_root=ROOT / "data/processed/m4-baselines",
        output_root=output_root,
    )
    return output_root / ACCEPTED_M3_GENERATION_ID


def test_phase2_artifacts_use_only_accepted_features_and_train_augmentation(
    phase2_output: Path,
) -> None:
    contract = json.loads((phase2_output / "m4_phase2_feature_contract.json").read_text())
    manifest = json.loads((phase2_output / "m4_phase2_training_manifest.json").read_text())
    predictions = pl.read_parquet(phase2_output / "m4_phase2_predictions.parquet")
    augmented = pl.read_parquet(phase2_output / "m4_phase2_augmented_training_keys.parquet")
    splits = pl.read_parquet(phase2_output / "m4_phase2_temporal_splits.parquet")
    accepted = load_accepted_m3_data(ROOT / "data/processed/m3-v6")

    assert contract["ordered_feature_columns"] == list(accepted.feature_columns)
    assert contract["forbidden_feature_check"]["forbidden_feature_count"] == 0
    assert augmented.height == 2 * 6233 == contract["augmentation"]["augmented_train_rows"]
    augmented_bouts = set(augmented["canonical_bout_id"])
    assert augmented_bouts == set(splits.filter(pl.col("split") == "train")["canonical_bout_id"])
    assert not augmented_bouts & set(splits.filter(pl.col("split") != "train")["canonical_bout_id"])
    assert predictions.height == 8912 * 5
    assert {"forward_probability", "swapped_probability", "symmetric_probability"}.issubset(
        predictions.columns
    )
    assert manifest["accepted_m3_generation_id"] == ACCEPTED_M3_GENERATION_ID


def test_phase2_replay_is_deterministic_and_preserves_phase1_artifacts(tmp_path: Path) -> None:
    phase1 = ROOT / "data/processed/m4-baselines" / ACCEPTED_M3_GENERATION_ID
    protected_names = (
        "m4_temporal_splits.parquet",
        "m4_baseline_predictions.parquet",
        "m4_baseline_metrics.json",
        "m4_feature_contract.json",
        "m4_training_manifest.json",
        "m4_logistic_regression.joblib",
        "m4_hist_gradient_boosting.joblib",
    )
    protected = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (phase1 / name for name in protected_names)
    }
    output_root = tmp_path / "same-output-root"
    run_m4_symmetry_training(
        m3_root=ROOT / "data/processed/m3-v6",
        phase1_root=ROOT / "data/processed/m4-baselines",
        output_root=output_root,
    )
    first = output_root / ACCEPTED_M3_GENERATION_ID
    names = [
        "m4_phase2_temporal_splits.parquet",
        "m4_phase2_augmented_training_keys.parquet",
        "m4_phase2_predictions.parquet",
        "m4_phase2_metrics.json",
        "m4_phase2_model_comparison.json",
        "m4_phase2_feature_contract.json",
        "m4_phase2_training_manifest.json",
        "m4_phase2_swap_augmented_logistic.joblib",
    ]
    first_bytes = {name: (first / name).read_bytes() for name in names}
    run_m4_symmetry_training(
        m3_root=ROOT / "data/processed/m3-v6",
        phase1_root=ROOT / "data/processed/m4-baselines",
        output_root=output_root,
    )

    assert all(first_bytes[name] == (first / name).read_bytes() for name in names)
    assert protected == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (phase1 / name for name in protected_names)
    }
