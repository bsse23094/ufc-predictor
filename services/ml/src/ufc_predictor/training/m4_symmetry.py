"""Deterministic M4 Phase 2 symmetry-aware temporal training.

Phase 2 consumes the accepted M3 projection and the immutable Phase 1 models.
It adds no features and never alters Phase 1 outputs.
"""

from __future__ import annotations

import json
import platform
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import joblib
import numpy as np
import pandas as pd
import polars as pl
import sklearn
from sklearn.base import BaseEstimator
from sklearn.pipeline import Pipeline

from ufc_predictor.training.m4_baselines import (
    ACCEPTED_M3_ACCEPTANCE_SHA256,
    RANDOM_SEED,
    SPLIT_POLICY_VERSION,
    _metrics,
    _pipeline_state,
    _sha256_path,
    _to_builtin,
    _write_json,
    _year_summary,
    build_logistic_pipeline,
    calibration_summary,
    create_temporal_split,
    load_accepted_m3_data,
)

M4_PHASE2_SCHEMA_VERSION = "m4.phase2.symmetry_aware.v1"
PHASE1_SCHEMA_VERSION = "m4.phase1.temporal_baselines.v1"
SELECTION_GUARDRAIL_LOG_LOSS_TOLERANCE = 0.002


@dataclass(frozen=True, slots=True)
class Candidate:
    """A fixed fitted model and the probability rule used for evaluation."""

    name: str
    model: BaseEstimator
    probability_rule: str
    complexity_rank: int
    training_scope: str


def swap_m4_rows(
    frame: pd.DataFrame,
    *,
    feature_columns: Iterable[str],
    target_column: str = "target_fighter_a_won",
) -> pd.DataFrame:
    """Apply the accepted A/B, missingness, and signed-difference swap contract."""

    features = tuple(feature_columns)
    result = frame.copy(deep=True)
    feature_set = set(features)
    for name in features:
        if name.startswith("a_"):
            peer = f"b_{name[2:]}"
            if peer not in feature_set:
                raise ValueError(f"swap contract has no B feature for {name}")
            result[name], result[peer] = frame[peer], frame[name]
        elif name.startswith("diff_"):
            result[name] = -frame[name]
        elif not name.startswith("b_"):
            raise ValueError(f"feature is outside the approved pairwise contract: {name}")
    if target_column not in result:
        raise ValueError("swap contract requires the binary M3 target")
    result[target_column] = 1 - frame[target_column].astype(int)
    if {"canonical_fighter_a_id", "canonical_fighter_b_id"}.issubset(frame.columns):
        result["canonical_fighter_a_id"], result["canonical_fighter_b_id"] = (
            frame["canonical_fighter_b_id"],
            frame["canonical_fighter_a_id"],
        )
    return result.copy()


def augment_training_rows(
    train: pd.DataFrame,
    *,
    feature_columns: Iterable[str],
    target_column: str,
) -> pd.DataFrame:
    """Return exactly one canonical and one target-complemented swapped row per train row."""

    canonical = train.copy(deep=True)
    canonical["augmentation_variant"] = "canonical"
    swapped = swap_m4_rows(train, feature_columns=feature_columns, target_column=target_column)
    swapped["augmentation_variant"] = "swapped"
    augmented = pd.concat([canonical, swapped], ignore_index=True)
    if len(augmented) != 2 * len(train):
        raise ValueError("training augmentation did not exactly double the train rows")
    return augmented


def symmetric_probability(
    forward: np.ndarray[Any, Any], swapped: np.ndarray[Any, Any]
) -> np.ndarray[Any, Any]:
    """Average a prediction with the complementary prediction in the opposite corner."""

    return 0.5 * (forward + (1.0 - swapped))


def _feature_matrix(frame: pd.DataFrame, feature_columns: tuple[str, ...]) -> pd.DataFrame:
    return frame.loc[:, list(feature_columns)].astype(float).copy()


def _predict_triplet(
    model: BaseEstimator,
    frame: pd.DataFrame,
    feature_columns: tuple[str, ...],
    target_column: str,
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    forward = cast(Any, model).predict_proba(_feature_matrix(frame, feature_columns))[:, 1]
    swapped_frame = swap_m4_rows(
        frame, feature_columns=feature_columns, target_column=target_column
    )
    swapped = cast(Any, model).predict_proba(_feature_matrix(swapped_frame, feature_columns))[:, 1]
    return forward, swapped, symmetric_probability(forward, swapped)


def _candidate_probability(
    candidate: Candidate,
    forward: np.ndarray[Any, Any],
    symmetric: np.ndarray[Any, Any],
) -> np.ndarray[Any, Any]:
    if candidate.probability_rule == "forward":
        return forward
    if candidate.probability_rule == "symmetrized":
        return symmetric
    raise ValueError(f"unsupported candidate probability rule: {candidate.probability_rule}")


def _corner_audit(
    candidate: Candidate,
    forward: np.ndarray[Any, Any],
    swapped: np.ndarray[Any, Any],
    symmetric: np.ndarray[Any, Any],
) -> dict[str, object]:
    chosen = _candidate_probability(candidate, forward, symmetric)
    swapped_symmetric = symmetric_probability(swapped, forward)
    chosen_swapped = _candidate_probability(candidate, swapped, swapped_symmetric)
    error = np.abs(chosen - (1.0 - chosen_swapped))
    return {
        "mean_absolute_complement_error": float(error.mean()),
        "median_absolute_complement_error": float(np.median(error)),
        "maximum_absolute_complement_error": float(error.max()),
        "violations_above_1e-6": int((error > 1e-6).sum()),
        "violations_above_1e-3": int((error > 1e-3).sum()),
        "violations_above_1e-2": int((error > 1e-2).sum()),
    }


def select_phase2_candidate(
    validation: dict[str, dict[str, Any]],
    *,
    baseline_name: str = "phase1_logistic_forward",
    guardrail_log_loss_tolerance: float = SELECTION_GUARDRAIL_LOG_LOSS_TOLERANCE,
) -> tuple[str, dict[str, object]]:
    """Select exclusively from validation metrics with an explicit baseline guardrail."""

    if baseline_name not in validation:
        raise ValueError("Phase 1 logistic validation control is missing")
    baseline_log_loss = float(validation[baseline_name]["metrics"]["log_loss"])
    eligible = {
        name: report
        for name, report in validation.items()
        if float(report["metrics"]["log_loss"]) <= baseline_log_loss + guardrail_log_loss_tolerance
    }
    if not eligible:
        raise ValueError("the Phase 1 logistic control must satisfy its own guardrail")

    def rank(item: tuple[str, dict[str, Any]]) -> tuple[float, float, float, float, int, str]:
        name, report = item
        metrics = cast(dict[str, float], report["metrics"])
        audit = cast(dict[str, float], report["corner_swap_audit"])
        return (
            float(metrics["log_loss"]),
            float(metrics["brier_score"]),
            -float(metrics["roc_auc"]),
            float(audit["mean_absolute_complement_error"]),
            int(report["complexity_rank"]),
            name,
        )

    selected = min(eligible.items(), key=rank)[0]
    return selected, {
        "selection_split": "validation",
        "selection_priority": [
            "lowest_log_loss",
            "lowest_brier_score",
            "highest_roc_auc",
            "lowest_mean_corner_swap_complement_error",
            "simpler_model",
        ],
        "guardrail": {
            "baseline_candidate": baseline_name,
            "baseline_validation_log_loss": baseline_log_loss,
            "maximum_allowed_validation_log_loss": baseline_log_loss + guardrail_log_loss_tolerance,
            "tolerance": guardrail_log_loss_tolerance,
            "policy": "candidate validation log loss may not worsen materially; test excluded",
        },
        "eligible_candidates": sorted(eligible),
    }


def _load_phase1_models(
    phase1_root: Path, generation_id: str
) -> tuple[Pipeline, Pipeline, dict[str, str]]:
    directory = phase1_root / generation_id
    manifest_path = directory / "m4_training_manifest.json"
    logistic_path = directory / "m4_logistic_regression.joblib"
    tree_path = directory / "m4_hist_gradient_boosting.joblib"
    if not all(path.is_file() for path in (manifest_path, logistic_path, tree_path)):
        raise FileNotFoundError("accepted Phase 1 models or manifest are missing")
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    if manifest.get("schema_version") != PHASE1_SCHEMA_VERSION:
        raise ValueError("Phase 1 manifest schema is not accepted")
    if manifest.get("accepted_m3_final_acceptance_report_sha256") != ACCEPTED_M3_ACCEPTANCE_SHA256:
        raise ValueError("Phase 1 does not reference the accepted M3 acceptance report")
    return (
        cast(Pipeline, joblib.load(logistic_path)),
        cast(Pipeline, joblib.load(tree_path)),
        {
            "phase1_manifest": _sha256_path(manifest_path),
            "phase1_logistic_model": _sha256_path(logistic_path),
            "phase1_hgb_model": _sha256_path(tree_path),
        },
    )


def run_m4_symmetry_training(
    *,
    m3_root: Path = Path("data/processed/m3-v6"),
    phase1_root: Path = Path("data/processed/m4-baselines"),
    output_root: Path = Path("data/processed/m4-phase2-symmetry"),
) -> dict[str, object]:
    """Train fixed Phase 2 candidates and publish a separate deterministic run."""

    np.random.seed(RANDOM_SEED)
    accepted = load_accepted_m3_data(m3_root)
    phase1_logistic, phase1_hgb, phase1_checksums = _load_phase1_models(
        phase1_root, accepted.generation_id
    )
    frame = pd.DataFrame(accepted.frame.to_dicts())
    split = create_temporal_split(frame)
    assignments = split.assignments
    partitions = {
        name: frame.loc[assignments == name].reset_index(drop=True)
        for name in ("train", "validation", "test")
    }
    train = partitions["train"]
    augmented_train = augment_training_rows(
        train,
        feature_columns=accepted.feature_columns,
        target_column=accepted.target_column,
    )
    augmented_logistic = build_logistic_pipeline().fit(
        _feature_matrix(augmented_train, accepted.feature_columns),
        augmented_train[accepted.target_column].astype(int).to_numpy(),
    )
    candidates = (
        Candidate("phase1_logistic_forward", phase1_logistic, "forward", 1, "phase1_train"),
        Candidate("phase1_logistic_symmetrized", phase1_logistic, "symmetrized", 2, "phase1_train"),
        Candidate(
            "swap_augmented_logistic_forward",
            augmented_logistic,
            "forward",
            2,
            "augmented_train_only",
        ),
        Candidate(
            "swap_augmented_logistic_symmetrized",
            augmented_logistic,
            "symmetrized",
            3,
            "augmented_train_only",
        ),
        Candidate("phase1_hgb_symmetrized", phase1_hgb, "symmetrized", 4, "phase1_train"),
    )
    reports: dict[str, dict[str, Any]] = {
        candidate.name: {
            "probability_rule": candidate.probability_rule,
            "training_scope": candidate.training_scope,
            "complexity_rank": candidate.complexity_rank,
            "splits": {},
            "corner_swap_audit": {},
            "test_by_year": {},
        }
        for candidate in candidates
    }
    prediction_rows: list[dict[str, object]] = []
    validation_for_selection: dict[str, dict[str, Any]] = {}
    for split_name in ("train", "validation", "test"):
        subset = partitions[split_name]
        target = subset[accepted.target_column].astype(int).to_numpy()
        for candidate in candidates:
            forward, swapped, symmetric = _predict_triplet(
                candidate.model, subset, accepted.feature_columns, accepted.target_column
            )
            probability = _candidate_probability(candidate, forward, symmetric)
            audit = _corner_audit(candidate, forward, swapped, symmetric)
            split_report = {
                "metrics": _metrics(target, probability),
                "calibration": calibration_summary(target, probability),
            }
            reports[candidate.name]["splits"][split_name] = split_report
            if split_name != "train":
                reports[candidate.name]["corner_swap_audit"][split_name] = audit
            if split_name == "validation":
                validation_for_selection[candidate.name] = {
                    "metrics": split_report["metrics"],
                    "corner_swap_audit": audit,
                    "complexity_rank": candidate.complexity_rank,
                }
            if split_name == "test":
                reports[candidate.name]["test_by_year"] = _year_summary(subset, target, probability)
            predicted = (probability >= 0.5).astype(int)
            for row, p_forward, p_swapped, p_symmetric, p, predicted_class in zip(
                subset[["canonical_bout_id", "fight_date", accepted.target_column]].to_dict(
                    orient="records"
                ),
                forward,
                swapped,
                symmetric,
                probability,
                predicted,
                strict=True,
            ):
                prediction_rows.append(
                    {
                        "canonical_bout_id": row["canonical_bout_id"],
                        "fight_date": row["fight_date"],
                        "split": split_name,
                        "target_fighter_a_won": int(row[accepted.target_column]),
                        "candidate_model": candidate.name,
                        "forward_probability": float(p_forward),
                        "swapped_probability": float(p_swapped),
                        "symmetric_probability": float(p_symmetric),
                        "probability_fighter_a_wins": float(p),
                        "predicted_class": int(predicted_class),
                        "complement_error": float(
                            abs(
                                p
                                - (
                                    1.0
                                    - _candidate_probability(
                                        candidate,
                                        np.asarray([p_swapped]),
                                        np.asarray([0.5 * (p_swapped + (1.0 - p_forward))]),
                                    )[0]
                                )
                            )
                        ),
                    }
                )
    selected_name, selection = select_phase2_candidate(validation_for_selection)
    selected = reports[selected_name]
    metrics = {
        "schema_version": M4_PHASE2_SCHEMA_VERSION,
        "candidates": reports,
        "selected_candidate": {
            "name": selected_name,
            "selection": selection,
            "untouched_test_metrics": selected["splits"]["test"]["metrics"],
        },
    }
    run_dir = output_root / accepted.generation_id
    run_dir.mkdir(parents=True, exist_ok=True)
    split_path = run_dir / "m4_phase2_temporal_splits.parquet"
    augmented_keys_path = run_dir / "m4_phase2_augmented_training_keys.parquet"
    predictions_path = run_dir / "m4_phase2_predictions.parquet"
    metrics_path = run_dir / "m4_phase2_metrics.json"
    comparison_path = run_dir / "m4_phase2_model_comparison.json"
    contract_path = run_dir / "m4_phase2_feature_contract.json"
    manifest_path = run_dir / "m4_phase2_training_manifest.json"
    augmented_model_path = run_dir / "m4_phase2_swap_augmented_logistic.joblib"
    split_frame = pl.DataFrame(
        frame[["canonical_bout_id", "fight_date", accepted.target_column]]
        .assign(split=assignments)
        .sort_values("canonical_bout_id")
        .to_dict(orient="list")
    )
    augmented_keys = pl.DataFrame(
        augmented_train[
            ["canonical_bout_id", "fight_date", "augmentation_variant", accepted.target_column]
        ]
        .sort_values(["canonical_bout_id", "augmentation_variant"])
        .to_dict(orient="list")
    )
    predictions = pl.DataFrame(pd.DataFrame(prediction_rows).to_dict(orient="list")).sort(
        ["candidate_model", "split", "canonical_bout_id"]
    )
    split_frame.write_parquet(split_path, compression="zstd")
    augmented_keys.write_parquet(augmented_keys_path, compression="zstd")
    predictions.write_parquet(predictions_path, compression="zstd")
    joblib.dump(augmented_logistic, augmented_model_path, compress=3)
    feature_contract = {
        "schema_version": M4_PHASE2_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "feature_schema_version": accepted.feature_schema_version,
        "feature_count": len(accepted.feature_columns),
        "ordered_feature_columns": list(accepted.feature_columns),
        "target_column": accepted.target_column,
        "swap_contract": (
            "exchange all a/b values and missingness indicators; negate diffs; complement target"
        ),
        "augmentation": {
            "scope": "chronological_train_only",
            "canonical_train_rows": len(train),
            "augmented_train_rows": len(augmented_train),
            "augmentation_factor": 2,
        },
        "swap_augmented_logistic_preprocessing": _pipeline_state(
            augmented_logistic, accepted.feature_columns
        ),
        "forbidden_feature_check": {
            "training_features_exactly_accepted_m3_contract": True,
            "forbidden_feature_count": 0,
        },
    }
    comparison = {
        "schema_version": M4_PHASE2_SCHEMA_VERSION,
        "candidate_names": [candidate.name for candidate in candidates],
        "validation_selection": metrics["selected_candidate"],
        "phase1_logistic_validation_control": reports["phase1_logistic_forward"]["splits"][
            "validation"
        ]["metrics"],
        "phase1_logistic_test_control": reports["phase1_logistic_forward"]["splits"]["test"][
            "metrics"
        ],
    }
    _write_json(metrics_path, _to_builtin(metrics))
    _write_json(comparison_path, _to_builtin(comparison))
    _write_json(contract_path, _to_builtin(feature_contract))
    output_paths = {
        "temporal_splits": split_path,
        "augmented_training_keys": augmented_keys_path,
        "predictions": predictions_path,
        "metrics": metrics_path,
        "model_comparison": comparison_path,
        "feature_contract": contract_path,
        "swap_augmented_logistic_model": augmented_model_path,
    }
    phase1_checksums_after = {
        key: _sha256_path(phase1_root / accepted.generation_id / filename)
        for key, filename in (
            ("phase1_manifest", "m4_training_manifest.json"),
            ("phase1_logistic_model", "m4_logistic_regression.joblib"),
            ("phase1_hgb_model", "m4_hist_gradient_boosting.joblib"),
        )
    }
    if phase1_checksums != phase1_checksums_after:
        raise ValueError("Phase 2 changed a protected Phase 1 artifact")
    manifest = {
        "schema_version": M4_PHASE2_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "accepted_m3_final_acceptance_report_sha256": ACCEPTED_M3_ACCEPTANCE_SHA256,
        "phase1_artifacts_preserved_sha256": phase1_checksums,
        "model_ready_artifact_path": str(accepted.artifact_path),
        "model_ready_artifact_sha256": accepted.artifact_sha256,
        "feature_count": len(accepted.feature_columns),
        "ordered_feature_columns": list(accepted.feature_columns),
        "split_policy": {"version": SPLIT_POLICY_VERSION, "boundaries": split.boundaries},
        "augmentation_policy": feature_contract["augmentation"],
        "selection_policy": selection,
        "selected_candidate": selected_name,
        "candidate_configurations": {
            candidate.name: {
                "probability_rule": candidate.probability_rule,
                "training_scope": candidate.training_scope,
                "complexity_rank": candidate.complexity_rank,
            }
            for candidate in candidates
        },
        "preprocessing_fit_scope": (
            "Phase 1 train only or Phase 2 augmented train only; validation/test never fit"
        ),
        "random_seeds": {"numpy": RANDOM_SEED, "scikit_learn_estimators": RANDOM_SEED},
        "output_paths": {key: str(path) for key, path in output_paths.items()},
        "output_checksums": {key: _sha256_path(path) for key, path in output_paths.items()},
        "output_row_counts": {
            "temporal_splits": split_frame.height,
            "augmented_training_keys": augmented_keys.height,
            "predictions": predictions.height,
        },
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "polars": pl.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "determinism_replay_summary": (
            "fixed seed, sorted output rows, stable JSON, and chronological date-only split"
        ),
    }
    _write_json(manifest_path, _to_builtin(manifest))
    return {
        "run_directory": str(run_dir),
        "training_manifest_path": str(manifest_path),
        "training_manifest_sha256": _sha256_path(manifest_path),
        "metrics_path": str(metrics_path),
        "metrics_sha256": _sha256_path(metrics_path),
        "predictions_path": str(predictions_path),
        "predictions_sha256": _sha256_path(predictions_path),
        "selected_candidate": selected_name,
        "augmented_train_rows": len(augmented_train),
    }
