"""Deterministic M4 Phase 3A XGBoost rolling-temporal training."""

from __future__ import annotations

import platform
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any, cast

import joblib
import numpy as np
import pandas as pd
import polars as pl
import sklearn
import xgboost as xgb
from sklearn.base import BaseEstimator
from sklearn.pipeline import Pipeline

from ufc_predictor.training.m4_baselines import (
    ACCEPTED_M3_ACCEPTANCE_SHA256,
    RANDOM_SEED,
    _metrics,
    _sha256_path,
    _to_builtin,
    _write_json,
    _year_summary,
    build_logistic_pipeline,
    calibration_summary,
    load_accepted_m3_data,
)
from ufc_predictor.training.m4_symmetry import (
    augment_training_rows,
    swap_m4_rows,
    symmetric_probability,
)

M4_PHASE3A_SCHEMA_VERSION = "m4.phase3a.xgboost_rolling_temporal.v1"
ROLLING_FOLD_POLICY = "m4.phase3a.expanding_distinct_dates.55-.70-.85-1.00.v1"
EARLY_STOPPING_ROUNDS = 35
MAX_BOOSTING_ROUNDS = 500


@dataclass(frozen=True, slots=True)
class RollingFold:
    """One distinct-date expanding training / later validation fold."""

    fold_id: str
    train_positions: tuple[int, ...]
    validation_positions: tuple[int, ...]
    boundaries: dict[str, str]


@dataclass(frozen=True, slots=True)
class XGBoostCandidate:
    """A compact predefined configuration and its train-orientation policy."""

    candidate_id: str
    configuration_id: str
    training_policy: str
    parameters: dict[str, float | int]
    complexity_rank: int


def create_rolling_temporal_folds(
    development: pd.DataFrame, *, fold_count: int = 3
) -> tuple[RollingFold, ...]:
    """Create three expanding folds using whole fight dates only."""

    if fold_count != 3:
        raise ValueError("Phase 3A deliberately defines exactly three rolling folds")
    dates = pd.to_datetime(development["fight_date"], errors="raise").dt.normalize()
    date_counts = dates.value_counts().sort_index()
    if len(date_counts) < 8:
        raise ValueError("rolling folds require sufficient distinct fight dates")
    cumulative = date_counts.cumsum()
    total = len(development)

    def nearest_index(fraction: float, minimum: int) -> int:
        candidates = list(range(minimum, len(date_counts)))
        return min(
            candidates,
            key=lambda index: (abs(int(cumulative.iloc[index]) - total * fraction), index),
        )

    first = nearest_index(0.55, 0)
    second = nearest_index(0.70, first + 1)
    third = nearest_index(0.85, second + 1)
    if third >= len(date_counts) - 1:
        third = len(date_counts) - 2
    if not first < second < third:
        raise ValueError("rolling-fold date cutoffs are not strictly increasing")
    boundaries = (first, second, third, len(date_counts) - 1)
    folds: list[RollingFold] = []
    for number, (train_end_index, validation_end_index) in enumerate(pairwise(boundaries), start=1):
        train_end = date_counts.index[train_end_index]
        validation_end = date_counts.index[validation_end_index]
        train_positions = tuple(np.flatnonzero((dates <= train_end).to_numpy()).tolist())
        validation_positions = tuple(
            np.flatnonzero(((dates > train_end) & (dates <= validation_end)).to_numpy()).tolist()
        )
        if not train_positions or not validation_positions:
            raise ValueError("rolling fold is empty")
        train_dates = set(dates.iloc[list(train_positions)])
        validation_dates = set(dates.iloc[list(validation_positions)])
        if train_dates & validation_dates or max(train_dates) >= min(validation_dates):
            raise ValueError("rolling fold leaks a date into its validation partition")
        folds.append(
            RollingFold(
                fold_id=f"fold_{number}",
                train_positions=train_positions,
                validation_positions=validation_positions,
                boundaries={
                    "train_start_date": min(train_dates).date().isoformat(),
                    "train_end_date": max(train_dates).date().isoformat(),
                    "validation_start_date": min(validation_dates).date().isoformat(),
                    "validation_end_date": max(validation_dates).date().isoformat(),
                },
            )
        )
    return tuple(folds)


def predefined_xgboost_candidates() -> tuple[XGBoostCandidate, ...]:
    """Return six conservative regularized configurations under two train policies."""

    configurations = (
        (
            "depth1_high_regularization",
            {
                "max_depth": 1,
                "min_child_weight": 5,
                "learning_rate": 0.04,
                "subsample": 0.9,
                "colsample_bytree": 0.8,
                "reg_alpha": 0.1,
                "reg_lambda": 6.0,
            },
            1,
        ),
        (
            "depth2_high_regularization",
            {
                "max_depth": 2,
                "min_child_weight": 6,
                "learning_rate": 0.04,
                "subsample": 0.9,
                "colsample_bytree": 0.8,
                "reg_alpha": 0.15,
                "reg_lambda": 7.0,
            },
            2,
        ),
        (
            "depth2_balanced",
            {
                "max_depth": 2,
                "min_child_weight": 4,
                "learning_rate": 0.05,
                "subsample": 0.9,
                "colsample_bytree": 0.9,
                "reg_alpha": 0.05,
                "reg_lambda": 5.0,
            },
            3,
        ),
        (
            "depth3_high_regularization",
            {
                "max_depth": 3,
                "min_child_weight": 8,
                "learning_rate": 0.035,
                "subsample": 0.85,
                "colsample_bytree": 0.8,
                "reg_alpha": 0.2,
                "reg_lambda": 8.0,
            },
            4,
        ),
        (
            "depth3_balanced",
            {
                "max_depth": 3,
                "min_child_weight": 6,
                "learning_rate": 0.04,
                "subsample": 0.85,
                "colsample_bytree": 0.85,
                "reg_alpha": 0.1,
                "reg_lambda": 6.0,
            },
            5,
        ),
        (
            "depth1_low_learning_rate",
            {
                "max_depth": 1,
                "min_child_weight": 3,
                "learning_rate": 0.025,
                "subsample": 1.0,
                "colsample_bytree": 1.0,
                "reg_alpha": 0.0,
                "reg_lambda": 4.0,
            },
            6,
        ),
    )
    candidates: list[XGBoostCandidate] = []
    for configuration_id, parameters, rank in configurations:
        for policy in ("canonical", "swap_augmented"):
            candidates.append(
                XGBoostCandidate(
                    candidate_id=f"{configuration_id}__{policy}",
                    configuration_id=configuration_id,
                    training_policy=policy,
                    parameters=parameters,
                    complexity_rank=rank + (10 if policy == "swap_augmented" else 0),
                )
            )
    return tuple(candidates)


def _feature_matrix(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    """Preserve NaN for XGBoost native missing-value routing; observed zeros remain zeros."""

    return frame.loc[:, list(columns)].astype(float).copy()


def _build_xgboost(candidate: XGBoostCandidate, *, n_estimators: int) -> xgb.XGBClassifier:
    return xgb.XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        n_estimators=n_estimators,
        random_state=RANDOM_SEED,
        n_jobs=1,
        tree_method="hist",
        device="cpu",
        verbosity=0,
        early_stopping_rounds=EARLY_STOPPING_ROUNDS
        if n_estimators == MAX_BOOSTING_ROUNDS
        else None,
        **candidate.parameters,
    )


def _predict_triplet(
    model: BaseEstimator,
    frame: pd.DataFrame,
    features: tuple[str, ...],
    target_column: str,
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    forward = cast(Any, model).predict_proba(_feature_matrix(frame, features))[:, 1]
    swapped_frame = swap_m4_rows(frame, feature_columns=features, target_column=target_column)
    swapped = cast(Any, model).predict_proba(_feature_matrix(swapped_frame, features))[:, 1]
    return forward, swapped, symmetric_probability(forward, swapped)


def _audit(
    forward: np.ndarray[Any, Any], swapped: np.ndarray[Any, Any], symmetric: np.ndarray[Any, Any]
) -> dict[str, dict[str, float | int]]:
    def summarize(error: np.ndarray[Any, Any]) -> dict[str, float | int]:
        return {
            "mean_absolute_complement_error": float(error.mean()),
            "median_absolute_complement_error": float(np.median(error)),
            "maximum_absolute_complement_error": float(error.max()),
            "violations_above_1e-6": int((error > 1e-6).sum()),
            "violations_above_1e-3": int((error > 1e-3).sum()),
            "violations_above_1e-2": int((error > 1e-2).sum()),
        }

    return {
        "raw_forward": summarize(np.abs(forward - (1.0 - swapped))),
        "symmetrized": summarize(
            np.abs(symmetric - (1.0 - symmetric_probability(swapped, forward)))
        ),
    }


def _fold_summary(frame: pd.DataFrame, target_column: str) -> dict[str, object]:
    target = frame[target_column].astype(int)
    return {
        "row_count": len(frame),
        "positive_count": int(target.sum()),
        "negative_count": int(len(target) - target.sum()),
        "positive_prevalence": float(target.mean()),
    }


def _best_iteration(model: xgb.XGBClassifier) -> int:
    value = getattr(model, "best_iteration", None)
    return int(value) + 1 if value is not None else MAX_BOOSTING_ROUNDS


def _candidate_aggregate(rows: list[dict[str, Any]]) -> dict[str, object]:
    validation_metrics = [cast(dict[str, float], row["symmetric_metrics"]) for row in rows]
    raw_audits = [
        cast(dict[str, dict[str, float]], row["corner_swap_audit"])["raw_forward"] for row in rows
    ]
    log_losses = [float(metrics["log_loss"]) for metrics in validation_metrics]
    aucs = [float(metrics["roc_auc"]) for metrics in validation_metrics]
    train_losses = [float(cast(dict[str, float], row["train_metrics"])["log_loss"]) for row in rows]
    gaps = [validation - train for validation, train in zip(log_losses, train_losses, strict=True)]
    return {
        "fold_count": len(rows),
        "mean_log_loss": float(np.mean(log_losses)),
        "std_log_loss": float(np.std(log_losses)),
        "worst_fold_log_loss": float(max(log_losses)),
        "mean_brier_score": float(
            np.mean([metrics["brier_score"] for metrics in validation_metrics])
        ),
        "mean_roc_auc": float(np.mean(aucs)),
        "worst_fold_roc_auc": float(min(aucs)),
        "mean_raw_corner_swap_error": float(
            np.mean([audit["mean_absolute_complement_error"] for audit in raw_audits])
        ),
        "mean_train_validation_log_loss_gap": float(np.mean(gaps)),
        "severe_train_validation_gap": bool(max(gaps) > 0.08),
        "best_iteration_counts": [int(row["best_iteration_count"]) for row in rows],
    }


def select_xgboost_candidate(
    candidate_aggregates: dict[str, dict[str, Any]], candidates: Iterable[XGBoostCandidate]
) -> tuple[str, dict[str, object]]:
    """Select only from rolling development metrics, never benchmark metrics."""

    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    if set(candidate_aggregates) != set(candidate_by_id):
        raise ValueError("aggregate candidates do not match the predefined XGBoost grid")

    def rank(candidate_id: str) -> tuple[float, float, float, float, float, int, str]:
        aggregate = candidate_aggregates[candidate_id]
        candidate = candidate_by_id[candidate_id]
        return (
            float(aggregate["mean_log_loss"]),
            float(aggregate["mean_brier_score"]),
            -float(aggregate["mean_roc_auc"]),
            float(aggregate["std_log_loss"]),
            float(aggregate["mean_raw_corner_swap_error"]),
            candidate.complexity_rank,
            candidate_id,
        )

    selected = min(candidate_aggregates, key=rank)
    return selected, {
        "selection_data_scope": "development_period_rolling_validation_only",
        "selection_priority": [
            "lowest_mean_rolling_validation_log_loss",
            "lowest_mean_rolling_validation_brier_score",
            "highest_mean_rolling_validation_roc_auc",
            "lowest_fold_log_loss_standard_deviation",
            "lowest_raw_forward_corner_swap_error",
            "simpler_configuration",
        ],
        "benchmark_test_excluded": True,
        "selected_candidate": selected,
    }


def _artifact_hashes(directory: Path) -> dict[str, str]:
    return {path.name: _sha256_path(path) for path in sorted(directory.iterdir()) if path.is_file()}


def _feature_importance(model: xgb.XGBClassifier, features: tuple[str, ...]) -> pl.DataFrame:
    booster = model.get_booster()
    gain = booster.get_score(importance_type="gain")
    weight = booster.get_score(importance_type="weight")

    def family(feature: str) -> str:
        if feature.startswith("a_") or feature.startswith("b_"):
            return "fighter_specific"
        if feature.startswith("diff_"):
            return "signed_difference"
        return "other"

    def scalar(value: float | list[float]) -> float:
        return float(value[0] if isinstance(value, list) else value)

    return pl.DataFrame(
        {
            "feature_name": list(features),
            "gain_importance": [scalar(gain.get(feature, 0.0)) for feature in features],
            "split_count_importance": [scalar(weight.get(feature, 0.0)) for feature in features],
            "feature_family": [family(feature) for feature in features],
        }
    ).sort(["gain_importance", "feature_name"], descending=[True, False])


def run_m4_xgboost_training(
    *,
    m3_root: Path = Path("data/processed/m3-v6"),
    phase1_root: Path = Path("data/processed/m4-baselines"),
    phase2_root: Path = Path("data/processed/m4-phase2-symmetry"),
    output_root: Path = Path("data/processed/m4-phase3a-xgboost"),
) -> dict[str, object]:
    """Select regularized XGBoost only with rolling development folds, then benchmark once."""

    np.random.seed(RANDOM_SEED)
    accepted = load_accepted_m3_data(m3_root)
    phase1_dir, phase2_dir = (
        phase1_root / accepted.generation_id,
        phase2_root / accepted.generation_id,
    )
    if not phase1_dir.is_dir() or not phase2_dir.is_dir():
        raise FileNotFoundError("accepted Phase 1 or Phase 2 artifacts are missing")
    protected_before = {
        "phase1": _artifact_hashes(phase1_dir),
        "phase2": _artifact_hashes(phase2_dir),
    }
    frame = pd.DataFrame(accepted.frame.to_dicts())
    dates = pd.to_datetime(frame["fight_date"], errors="raise")
    development = frame.loc[dates <= pd.Timestamp("2023-11-11")].reset_index(drop=True)
    benchmark = frame.loc[dates >= pd.Timestamp("2023-11-18")].reset_index(drop=True)
    if len(development) != 7575 or len(benchmark) != 1337:
        raise ValueError("accepted Phase 3A development/benchmark cardinalities changed")
    folds = create_rolling_temporal_folds(development)
    candidates = predefined_xgboost_candidates()
    fold_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, object]] = []
    candidate_rows: list[dict[str, Any]] = []
    control_rows: list[dict[str, Any]] = []
    for fold in folds:
        train = development.iloc[list(fold.train_positions)].reset_index(drop=True)
        validation = development.iloc[list(fold.validation_positions)].reset_index(drop=True)
        train_y = train[accepted.target_column].astype(int).to_numpy()
        validation_y = validation[accepted.target_column].astype(int).to_numpy()
        fold_rows.extend(
            {
                "canonical_bout_id": row["canonical_bout_id"],
                "fight_date": row["fight_date"],
                "fold_id": fold.fold_id,
                "role": role,
            }
            for role, subset in (("train", train), ("validation", validation))
            for row in subset[["canonical_bout_id", "fight_date"]].to_dict(orient="records")
        )
        control = build_logistic_pipeline().fit(
            _feature_matrix(train, accepted.feature_columns), train_y
        )
        control_forward, control_swapped, control_symmetric = _predict_triplet(
            control, validation, accepted.feature_columns, accepted.target_column
        )
        control_rows.append(
            {
                "fold_id": fold.fold_id,
                "symmetric_metrics": _metrics(validation_y, control_symmetric),
                "corner_swap_audit": _audit(control_forward, control_swapped, control_symmetric),
            }
        )
        for candidate in candidates:
            fitting = (
                train
                if candidate.training_policy == "canonical"
                else augment_training_rows(
                    train,
                    feature_columns=accepted.feature_columns,
                    target_column=accepted.target_column,
                )
            )
            model = _build_xgboost(candidate, n_estimators=MAX_BOOSTING_ROUNDS)
            model.fit(
                _feature_matrix(fitting, accepted.feature_columns),
                fitting[accepted.target_column].astype(int).to_numpy(),
                eval_set=[(_feature_matrix(validation, accepted.feature_columns), validation_y)],
                verbose=False,
            )
            forward, swapped, symmetric = _predict_triplet(
                model, validation, accepted.feature_columns, accepted.target_column
            )
            _, _, train_symmetric = _predict_triplet(
                model, train, accepted.feature_columns, accepted.target_column
            )
            audit = _audit(forward, swapped, symmetric)
            row = {
                "candidate_id": candidate.candidate_id,
                "configuration_id": candidate.configuration_id,
                "training_policy": candidate.training_policy,
                "complexity_rank": candidate.complexity_rank,
                "fold_id": fold.fold_id,
                "fold_boundaries": fold.boundaries,
                "train_summary": _fold_summary(train, accepted.target_column),
                "validation_summary": _fold_summary(validation, accepted.target_column),
                "train_metrics": _metrics(train_y, train_symmetric),
                "forward_metrics": _metrics(validation_y, forward),
                "symmetric_metrics": _metrics(validation_y, symmetric),
                "calibration": calibration_summary(validation_y, symmetric),
                "corner_swap_audit": audit,
                "best_iteration_count": _best_iteration(model),
                "parameters": candidate.parameters,
            }
            candidate_rows.append(row)
            predicted = (symmetric >= 0.5).astype(int)
            for source, p_forward, p_swapped, p_symmetric, predicted_class in zip(
                validation[["canonical_bout_id", "fight_date", accepted.target_column]].to_dict(
                    orient="records"
                ),
                forward,
                swapped,
                symmetric,
                predicted,
                strict=True,
            ):
                prediction_rows.append(
                    {
                        "canonical_bout_id": source["canonical_bout_id"],
                        "fight_date": source["fight_date"],
                        "evaluation_partition": "rolling_validation",
                        "fold_id": fold.fold_id,
                        "target_fighter_a_won": int(source[accepted.target_column]),
                        "candidate_id": candidate.candidate_id,
                        "forward_probability": float(p_forward),
                        "swapped_probability": float(p_swapped),
                        "symmetric_probability": float(p_symmetric),
                        "predicted_class": int(predicted_class),
                        "raw_complement_error": float(abs(p_forward - (1.0 - p_swapped))),
                    }
                )
    grouped: dict[str, list[dict[str, Any]]] = {
        candidate.candidate_id: [] for candidate in candidates
    }
    for row in candidate_rows:
        grouped[str(row["candidate_id"])].append(row)
    aggregates = {
        candidate_id: _candidate_aggregate(rows) for candidate_id, rows in grouped.items()
    }
    selected_id, selection = select_xgboost_candidate(aggregates, candidates)
    selected_candidate = next(
        candidate for candidate in candidates if candidate.candidate_id == selected_id
    )
    selected_rounds = int(median(cast(list[int], aggregates[selected_id]["best_iteration_counts"])))
    final_fitting = (
        development
        if selected_candidate.training_policy == "canonical"
        else augment_training_rows(
            development,
            feature_columns=accepted.feature_columns,
            target_column=accepted.target_column,
        )
    )
    final_model = _build_xgboost(selected_candidate, n_estimators=selected_rounds)
    final_model.fit(
        _feature_matrix(final_fitting, accepted.feature_columns),
        final_fitting[accepted.target_column].astype(int).to_numpy(),
        verbose=False,
    )
    benchmark_y = benchmark[accepted.target_column].astype(int).to_numpy()
    benchmark_forward, benchmark_swapped, benchmark_symmetric = _predict_triplet(
        final_model, benchmark, accepted.feature_columns, accepted.target_column
    )
    benchmark_audit = _audit(benchmark_forward, benchmark_swapped, benchmark_symmetric)
    benchmark_metrics = {
        "forward_metrics": _metrics(benchmark_y, benchmark_forward),
        "symmetric_metrics": _metrics(benchmark_y, benchmark_symmetric),
        "calibration": calibration_summary(benchmark_y, benchmark_symmetric),
        "corner_swap_audit": benchmark_audit,
        "test_by_year": _year_summary(benchmark, benchmark_y, benchmark_symmetric),
    }
    for source, p_forward, p_swapped, p_symmetric, predicted_class in zip(
        benchmark[["canonical_bout_id", "fight_date", accepted.target_column]].to_dict(
            orient="records"
        ),
        benchmark_forward,
        benchmark_swapped,
        benchmark_symmetric,
        (benchmark_symmetric >= 0.5).astype(int),
        strict=True,
    ):
        prediction_rows.append(
            {
                "canonical_bout_id": source["canonical_bout_id"],
                "fight_date": source["fight_date"],
                "evaluation_partition": "locked_benchmark",
                "fold_id": None,
                "target_fighter_a_won": int(source[accepted.target_column]),
                "candidate_id": selected_id,
                "forward_probability": float(p_forward),
                "swapped_probability": float(p_swapped),
                "symmetric_probability": float(p_symmetric),
                "predicted_class": int(predicted_class),
                "raw_complement_error": float(abs(p_forward - (1.0 - p_swapped))),
            }
        )
    phase1_logistic = cast(Pipeline, joblib.load(phase1_dir / "m4_logistic_regression.joblib"))
    phase1_hgb = cast(Pipeline, joblib.load(phase1_dir / "m4_hist_gradient_boosting.joblib"))
    comparisons: dict[str, object] = {}
    for name, model, use_symmetric in (
        ("phase1_logistic", phase1_logistic, False),
        ("phase2_symmetrized_logistic", phase1_logistic, True),
        ("phase2_symmetrized_hgb", phase1_hgb, True),
    ):
        forward, swapped, symmetric = _predict_triplet(
            model, benchmark, accepted.feature_columns, accepted.target_column
        )
        probability = symmetric if use_symmetric else forward
        comparisons[name] = {
            "metrics": _metrics(benchmark_y, probability),
            "calibration": calibration_summary(benchmark_y, probability),
            "corner_swap_audit": _audit(forward, swapped, symmetric),
        }
    run_dir = output_root / accepted.generation_id
    run_dir.mkdir(parents=True, exist_ok=True)
    folds_path = run_dir / "m4_phase3a_rolling_folds.parquet"
    results_path = run_dir / "m4_phase3a_candidate_results.parquet"
    predictions_path = run_dir / "m4_phase3a_predictions.parquet"
    metrics_path = run_dir / "m4_phase3a_metrics.json"
    comparison_path = run_dir / "m4_phase3a_model_comparison.json"
    importance_path = run_dir / "m4_phase3a_feature_importance.parquet"
    contract_path = run_dir / "m4_phase3a_feature_contract.json"
    manifest_path = run_dir / "m4_phase3a_training_manifest.json"
    model_path = run_dir / "m4_phase3a_selected_xgboost.joblib"
    folds_frame = pl.DataFrame(pd.DataFrame(fold_rows).to_dict(orient="list")).sort(
        ["fold_id", "role", "canonical_bout_id"]
    )
    flat_results = []
    for row in candidate_rows:
        symmetric_metrics = cast(dict[str, Any], row["symmetric_metrics"])
        train_metrics = cast(dict[str, Any], row["train_metrics"])
        audit = cast(dict[str, dict[str, Any]], row["corner_swap_audit"])
        flat_results.append(
            {
                "candidate_id": row["candidate_id"],
                "configuration_id": row["configuration_id"],
                "training_policy": row["training_policy"],
                "fold_id": row["fold_id"],
                "best_iteration_count": row["best_iteration_count"],
                "validation_log_loss": symmetric_metrics["log_loss"],
                "validation_brier_score": symmetric_metrics["brier_score"],
                "validation_roc_auc": symmetric_metrics["roc_auc"],
                "train_log_loss": train_metrics["log_loss"],
                "raw_forward_mean_complement_error": audit["raw_forward"][
                    "mean_absolute_complement_error"
                ],
                "symmetric_mean_complement_error": audit["symmetrized"][
                    "mean_absolute_complement_error"
                ],
            }
        )
    results_frame = pl.DataFrame(flat_results).sort(["candidate_id", "fold_id"])
    predictions_frame = pl.DataFrame(pd.DataFrame(prediction_rows).to_dict(orient="list")).sort(
        ["evaluation_partition", "candidate_id", "fold_id", "canonical_bout_id"], nulls_last=True
    )
    importance_frame = _feature_importance(final_model, accepted.feature_columns)
    folds_frame.write_parquet(folds_path, compression="zstd")
    results_frame.write_parquet(results_path, compression="zstd")
    predictions_frame.write_parquet(predictions_path, compression="zstd")
    importance_frame.write_parquet(importance_path, compression="zstd")
    joblib.dump(final_model, model_path, compress=3)
    control_aggregate = _candidate_aggregate(
        [
            {
                "symmetric_metrics": row["symmetric_metrics"],
                "corner_swap_audit": row["corner_swap_audit"],
                "train_metrics": row["symmetric_metrics"],
                "best_iteration_count": 0,
            }
            for row in control_rows
        ]
    )
    metrics = {
        "schema_version": M4_PHASE3A_SCHEMA_VERSION,
        "candidate_aggregates": aggregates,
        "rolling_symmetrized_logistic_control": control_aggregate,
        "fold_results": candidate_rows,
        "selected_candidate": {
            "candidate_id": selected_id,
            "configuration_id": selected_candidate.configuration_id,
            "training_policy": selected_candidate.training_policy,
            "parameters": selected_candidate.parameters,
            "best_iteration_count": selected_rounds,
            "best_iteration_policy": (
                "median of validation-only early-stopping best iterations "
                "across selected rolling folds"
            ),
            "selection": selection,
        },
        "locked_benchmark": benchmark_metrics,
    }
    comparison = {
        "schema_version": M4_PHASE3A_SCHEMA_VERSION,
        "reporting_only_policy": (
            "benchmark metrics do not alter the selected XGBoost configuration"
        ),
        "selected_xgboost": benchmark_metrics,
        "accepted_controls": comparisons,
    }
    feature_contract = {
        "schema_version": M4_PHASE3A_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "accepted_m3_final_acceptance_report_sha256": ACCEPTED_M3_ACCEPTANCE_SHA256,
        "feature_count": len(accepted.feature_columns),
        "ordered_feature_columns": list(accepted.feature_columns),
        "missing_value_policy": (
            "XGBoost native missing-value routing; NaN preserved and zero remains observed zero"
        ),
        "rolling_fold_policy": ROLLING_FOLD_POLICY,
        "forbidden_feature_check": {"registered_features_only": True, "forbidden_feature_count": 0},
    }
    _write_json(metrics_path, _to_builtin(metrics))
    _write_json(comparison_path, _to_builtin(comparison))
    _write_json(contract_path, _to_builtin(feature_contract))
    output_paths = {
        "rolling_folds": folds_path,
        "candidate_results": results_path,
        "predictions": predictions_path,
        "metrics": metrics_path,
        "model_comparison": comparison_path,
        "feature_importance": importance_path,
        "feature_contract": contract_path,
        "selected_xgboost_model": model_path,
    }
    protected_after = {
        "phase1": _artifact_hashes(phase1_dir),
        "phase2": _artifact_hashes(phase2_dir),
    }
    if protected_before != protected_after:
        raise ValueError("Phase 3A changed protected Phase 1 or Phase 2 artifacts")
    manifest = {
        "schema_version": M4_PHASE3A_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "accepted_m3_final_acceptance_report_sha256": ACCEPTED_M3_ACCEPTANCE_SHA256,
        "development_period": {
            "start": "1994-03-11",
            "end": "2023-11-11",
            "rows": len(development),
        },
        "locked_benchmark_period": {
            "start": "2023-11-18",
            "end": "2026-06-27",
            "rows": len(benchmark),
        },
        "rolling_fold_policy": ROLLING_FOLD_POLICY,
        "fold_boundaries": {fold.fold_id: fold.boundaries for fold in folds},
        "candidate_configurations": [
            {
                "candidate_id": candidate.candidate_id,
                "parameters": candidate.parameters,
                "training_policy": candidate.training_policy,
            }
            for candidate in candidates
        ],
        "selection": metrics["selected_candidate"],
        "preprocessing": feature_contract["missing_value_policy"],
        "protected_prior_artifacts_sha256": protected_before,
        "random_seeds": {"numpy": RANDOM_SEED, "xgboost": RANDOM_SEED, "n_jobs": 1},
        "output_paths": {key: str(path) for key, path in output_paths.items()},
        "output_checksums": {key: _sha256_path(path) for key, path in output_paths.items()},
        "environment": {
            "python": platform.python_version(),
            "xgboost": xgb.__version__,
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "determinism_replay_summary": (
            "fixed seed, n_jobs=1, native missing values, sorted artifacts, "
            "and validation-only early stopping"
        ),
    }
    _write_json(manifest_path, _to_builtin(manifest))
    return {
        "run_directory": str(run_dir),
        "selected_candidate": selected_id,
        "selected_best_iteration_count": selected_rounds,
        "metrics_path": str(metrics_path),
        "metrics_sha256": _sha256_path(metrics_path),
        "predictions_path": str(predictions_path),
        "predictions_sha256": _sha256_path(predictions_path),
        "training_manifest_path": str(manifest_path),
        "training_manifest_sha256": _sha256_path(manifest_path),
    }
