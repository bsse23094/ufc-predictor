"""M4 Phase 4A development-only calibration and fixed probability blending."""

from __future__ import annotations

import gc
import json
import platform
from dataclasses import dataclass
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
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

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
from ufc_predictor.training.m4_opponent_adjusted_performance import (
    PHASE3A_FOLDS_SHA256,
    PHASE3A_PREDICTIONS_SHA256,
    _verify_b1_elo_inputs,
)
from ufc_predictor.training.m4_opponent_strength import (
    _artifact_hashes,
    _audit,
    _augment,
    _best_iteration,
    _build_xgboost,
    _matrix,
    _predict_triplet,
)
from ufc_predictor.training.m4_optuna_tuning import (
    PHASE3C_CHAMPION_ID,
    PHASE3C_CHAMPION_PACK,
    PHASE3C_MANIFEST_SHA256,
    _load_phase3c,
)
from ufc_predictor.training.m4_xgboost import MAX_BOOSTING_ROUNDS

M4_PHASE4A_SCHEMA_VERSION = "m4.phase4a.development_only_calibration_blending.v1"
PHASE3C_MEAN_LOG_LOSS = 0.667716
PHASE3C_BRIER = 0.237535
PHASE3C_ROC_AUC = 0.629315
PROMOTION_LOG_LOSS_IMPROVEMENT = 0.001
MAX_BRIER_REGRESSION = 0.001
MAX_ECE_REGRESSION = 0.005
MAX_SYMMETRY_ERROR = 1e-6
ISOTONIC_MINIMUM_SAMPLES = 500
BLEND_WEIGHTS = tuple(round(value / 10, 1) for value in range(11))


@dataclass(frozen=True, slots=True)
class Candidate:
    """A fixed Phase 4A post-processing candidate."""

    candidate_id: str
    method: str
    xgboost_calibration: str | None
    xgboost_weight: float | None
    complexity_rank: int


@dataclass(slots=True)
class CalibratedBlendArtifact:
    """Deployable frozen base models and the selected symmetric post-processor."""

    feature_columns: tuple[str, ...]
    target_column: str
    xgboost_model: BaseEstimator
    logistic_model: BaseEstimator
    xgboost_calibrator: BaseEstimator | None
    method: str
    xgboost_weight: float | None


def _fold_members(split_frame: pl.DataFrame) -> dict[str, dict[str, set[str]]]:
    return {
        str(fold): {
            role: set(
                split_frame.filter((pl.col("fold_id") == fold) & (pl.col("role") == role))[
                    "canonical_bout_id"
                ].to_list()
            )
            for role in ("train", "validation")
        }
        for fold in sorted(split_frame["fold_id"].unique().to_list())
    }


def _symmetric_calibrated(
    calibrator: BaseEstimator, probabilities: np.ndarray[Any, Any]
) -> np.ndarray[Any, Any]:
    """Calibrate a symmetric probability while preserving p(x)+p(swap(x))=1."""

    values = np.asarray(probabilities, dtype=float)
    forward = _calibrator_probability(calibrator, values)
    swapped = _calibrator_probability(calibrator, 1.0 - values)
    return 0.5 * (forward + (1.0 - swapped))


def _calibrator_probability(
    calibrator: BaseEstimator, probabilities: np.ndarray[Any, Any]
) -> np.ndarray[Any, Any]:
    values = np.asarray(probabilities, dtype=float)
    if isinstance(calibrator, IsotonicRegression):
        return np.asarray(calibrator.predict(values), dtype=float)
    return np.asarray(cast(Any, calibrator).predict_proba(values.reshape(-1, 1))[:, 1], dtype=float)


def _fit_calibrator(
    kind: str, probabilities: np.ndarray[Any, Any], target: np.ndarray[Any, Any]
) -> BaseEstimator:
    if kind == "platt":
        return LogisticRegression(
            C=1.0, solver="lbfgs", max_iter=1000, random_state=RANDOM_SEED
        ).fit(probabilities.reshape(-1, 1), target)
    if kind == "isotonic":
        return IsotonicRegression(out_of_bounds="clip").fit(probabilities, target)
    raise ValueError(f"unsupported calibration kind: {kind}")


def _candidates(include_isotonic: bool) -> tuple[Candidate, ...]:
    values = [
        Candidate("uncalibrated_xgboost", "uncalibrated_xgboost", None, None, 1),
        Candidate("platt_calibrated_xgboost", "calibrated_xgboost", "platt", None, 2),
    ]
    if include_isotonic:
        values.append(
            Candidate("isotonic_calibrated_xgboost", "calibrated_xgboost", "isotonic", None, 3)
        )
    values.append(Candidate("symmetrized_logistic", "symmetrized_logistic", None, None, 0))
    values.extend(
        Candidate(f"blend_xgboost_weight_{weight:.1f}", "fixed_grid_blend", None, weight, 2)
        for weight in BLEND_WEIGHTS
    )
    return tuple(values)


def _candidate_probability(
    candidate: Candidate,
    xgboost_probability: np.ndarray[Any, Any],
    logistic_probability: np.ndarray[Any, Any],
    calibrator: BaseEstimator | None = None,
) -> np.ndarray[Any, Any]:
    if candidate.method == "uncalibrated_xgboost":
        return xgboost_probability
    if candidate.method == "symmetrized_logistic":
        return logistic_probability
    if candidate.method == "calibrated_xgboost":
        if calibrator is None:
            raise ValueError("calibrated candidate requires a calibrator")
        return _symmetric_calibrated(calibrator, xgboost_probability)
    if candidate.method == "fixed_grid_blend":
        if candidate.xgboost_weight is None:
            raise ValueError("blend candidate requires a weight")
        return (
            candidate.xgboost_weight * xgboost_probability
            + (1.0 - candidate.xgboost_weight) * logistic_probability
        )
    raise ValueError(f"unsupported candidate method: {candidate.method}")


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    losses = [float(row["metrics"]["log_loss"]) for row in rows]
    return {
        "mean_log_loss": float(np.mean(losses)),
        "mean_brier_score": float(np.mean([row["metrics"]["brier_score"] for row in rows])),
        "mean_ece": float(
            np.mean([row["calibration"]["expected_calibration_error"] for row in rows])
        ),
        "mean_roc_auc": float(np.mean([row["metrics"]["roc_auc"] for row in rows])),
        "std_log_loss": float(np.std(losses)),
        "worst_fold_log_loss": float(max(losses)),
        "mean_symmetric_complement_error": float(
            np.mean(
                [row["audit"]["symmetrized"]["maximum_absolute_complement_error"] for row in rows]
            )
        ),
        "fold_losses": {str(row["fold_id"]): float(row["metrics"]["log_loss"]) for row in rows},
    }


def select_phase4a_candidate(
    aggregates: dict[str, dict[str, Any]], candidates: tuple[Candidate, ...]
) -> str:
    """Select lexicographically without a weighted multi-metric score."""

    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    eligible = {
        candidate_id: aggregate
        for candidate_id, aggregate in aggregates.items()
        if bool(aggregate["selection_eligible"])
    }
    if not eligible:
        raise ValueError("Phase 4A has no candidate eligible across every outer fold")
    return min(
        eligible,
        key=lambda candidate_id: (
            float(aggregates[candidate_id]["mean_log_loss"]),
            float(aggregates[candidate_id]["mean_brier_score"]),
            float(aggregates[candidate_id]["mean_ece"]),
            -float(aggregates[candidate_id]["mean_roc_auc"]),
            float(aggregates[candidate_id]["std_log_loss"]),
            float(aggregates[candidate_id]["worst_fold_log_loss"]),
            candidate_by_id[candidate_id].complexity_rank,
            candidate_id,
        ),
    )


def _promotion(selected: dict[str, Any], phase3c: dict[str, Any]) -> dict[str, Any]:
    delta = float(selected["mean_log_loss"]) - float(phase3c["mean_log_loss"])
    checks = {
        "minimum_log_loss_improvement": delta <= -PROMOTION_LOG_LOSS_IMPROVEMENT,
        "brier_not_meaningfully_worse": float(selected["mean_brier_score"])
        <= float(phase3c["mean_brier_score"]) + MAX_BRIER_REGRESSION,
        "calibration_not_meaningfully_worse": float(selected["mean_ece"])
        <= float(phase3c["mean_ece"]) + MAX_ECE_REGRESSION,
        "exact_symmetry": float(selected["mean_symmetric_complement_error"]) <= MAX_SYMMETRY_ERROR,
    }
    return {
        "phase3c_champion": phase3c,
        "phase3c_rounded_reference": {
            "mean_log_loss": PHASE3C_MEAN_LOG_LOSS,
            "brier_score": PHASE3C_BRIER,
            "roc_auc": PHASE3C_ROC_AUC,
        },
        "mean_log_loss_delta_vs_phase3c": delta,
        "promotion_threshold": PROMOTION_LOG_LOSS_IMPROVEMENT,
        "promotion_checks": checks,
        "champion_promoted": all(checks.values()),
        "result": "promoted" if all(checks.values()) else "non_promoted_retain_phase3c_champion",
    }


def run_m4_calibration_blending(
    *,
    m3_root: Path = Path("data/processed/m3-v6"),
    phase1_root: Path = Path("data/processed/m4-baselines"),
    phase2_root: Path = Path("data/processed/m4-phase2-symmetry"),
    phase3a_root: Path = Path("data/processed/m4-phase3a-xgboost"),
    phase3b1_root: Path = Path("data/processed/m4-phase3b1-opponent-strength"),
    phase3c_root: Path = Path("data/processed/m4-phase3c-opponent-adjusted-performance"),
    phase3d_root: Path = Path("data/processed/m4-phase3d-optuna"),
    output_root: Path = Path("data/processed/m4-phase4a-calibration-blending"),
) -> dict[str, object]:
    """Evaluate development-only calibration and blending over the accepted Phase 3C pack."""

    np.random.seed(RANDOM_SEED)
    accepted = load_accepted_m3_data(m3_root)
    protected_dirs = {
        "phase1": phase1_root / accepted.generation_id,
        "phase2": phase2_root / accepted.generation_id,
        "phase3a": phase3a_root / accepted.generation_id,
        "phase3b1": phase3b1_root / accepted.generation_id,
        "phase3c": phase3c_root / accepted.generation_id,
        "phase3d": phase3d_root / accepted.generation_id,
    }
    if any(not path.is_dir() for path in protected_dirs.values()):
        raise FileNotFoundError("accepted M4 input artifacts are missing")
    protected_before = {name: _artifact_hashes(path) for name, path in protected_dirs.items()}
    phase3a_dir, phase3c_dir = protected_dirs["phase3a"], protected_dirs["phase3c"]
    if (
        _sha256_path(phase3a_dir / "m4_phase3a_rolling_folds.parquet") != PHASE3A_FOLDS_SHA256
        or _sha256_path(phase3a_dir / "m4_phase3a_predictions.parquet")
        != PHASE3A_PREDICTIONS_SHA256
    ):
        raise ValueError("accepted Phase 3A fold or prediction hash changed")
    if _sha256_path(phase3c_dir / "m4_phase3c_training_manifest.json") != PHASE3C_MANIFEST_SHA256:
        raise ValueError("accepted Phase 3C manifest hash changed")
    elo_pairwise, _overall, b1_hashes = _verify_b1_elo_inputs(
        protected_dirs["phase3b1"], accepted.feature_columns
    )
    phase3c_pairwise, features, phase3c_metrics, phase3c_manifest = _load_phase3c(
        phase3c_dir, accepted.feature_columns
    )
    phase3d_manifest = json.loads(
        (protected_dirs["phase3d"] / "m4_phase3d_training_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if phase3d_manifest["input_hashes"]["phase3c_manifest"] != PHASE3C_MANIFEST_SHA256:
        raise ValueError("Phase 3D verification does not lock accepted Phase 3C")
    base = pd.DataFrame(accepted.frame.to_dicts())
    for frame in (base, elo_pairwise, phase3c_pairwise):
        frame["fight_date"] = pd.to_datetime(frame["fight_date"], errors="raise").dt.normalize()
    keys = ["canonical_bout_id", "fight_date", "canonical_fighter_a_id", "canonical_fighter_b_id"]
    extras = [name for name in features if name not in set(accepted.feature_columns)]
    data = base.merge(
        elo_pairwise.loc[:, [*keys, *[name for name in extras if name in elo_pairwise]]],
        on=keys,
        validate="one_to_one",
    ).merge(
        phase3c_pairwise.loc[:, [*keys, *[name for name in extras if name in phase3c_pairwise]]],
        on=keys,
        validate="one_to_one",
    )
    if set(features) - set(data.columns):
        raise ValueError("Phase 3C feature pack cannot be reconstructed exactly")
    splits = pl.read_parquet(phase3a_dir / "m4_phase3a_rolling_folds.parquet")
    phase3a_predictions = pl.read_parquet(phase3a_dir / "m4_phase3a_predictions.parquet")
    members = _fold_members(splits)
    benchmark_keys = set(
        phase3a_predictions.filter(pl.col("evaluation_partition") == "locked_benchmark")[
            "canonical_bout_id"
        ].to_list()
    )
    development_keys = set().union(
        *(fold["train"] | fold["validation"] for fold in members.values())
    )
    oof_validation_keys = set().union(*(fold["validation"] for fold in members.values()))
    if (
        len(members) != 3
        or len(benchmark_keys) != 1337
        or len(development_keys) != 7575
        or benchmark_keys & development_keys
        or any(fold["train"] & fold["validation"] for fold in members.values())
    ):
        raise ValueError("accepted Phase 3A split contract changed")
    keyed = data.set_index("canonical_bout_id", drop=False)
    if set(keyed.index) != development_keys | benchmark_keys:
        raise ValueError("Phase 4A rows do not match accepted Phase 3A keys")

    # First produce only base-model OOF development predictions.  Calibration never sees
    # a prediction made by a model trained on that row, and benchmark rows remain absent.
    base_rows: list[dict[str, Any]] = []
    best_iterations: list[int] = []
    for fold_id, fold in members.items():
        train = keyed.loc[sorted(fold["train"])].reset_index(drop=True)
        validation = keyed.loc[sorted(fold["validation"])].reset_index(drop=True)
        train_y = train[accepted.target_column].astype(int).to_numpy()
        validation_y = validation[accepted.target_column].astype(int).to_numpy()
        logistic = build_logistic_pipeline().fit(_matrix(train, features), train_y)
        xgboost_model = _build_xgboost(rounds=MAX_BOOSTING_ROUNDS)
        fitting = _augment(train, features=features, target=accepted.target_column)
        cast(Any, xgboost_model).fit(
            _matrix(fitting, features),
            fitting[accepted.target_column].astype(int).to_numpy(),
            eval_set=[(_matrix(validation, features), validation_y)],
            verbose=False,
        )
        x_forward, x_swapped, x_symmetric = _predict_triplet(
            xgboost_model, validation, features, accepted.target_column
        )
        l_forward, l_swapped, l_symmetric = _predict_triplet(
            logistic, validation, features, accepted.target_column
        )
        best_iterations.append(_best_iteration(xgboost_model))
        for source, xp_f, xp_s, xp, lp_f, lp_s, lp in zip(
            validation[["canonical_bout_id", "fight_date", accepted.target_column]].to_dict(
                orient="records"
            ),
            x_forward,
            x_swapped,
            x_symmetric,
            l_forward,
            l_swapped,
            l_symmetric,
            strict=True,
        ):
            base_rows.append(
                {
                    "canonical_bout_id": source["canonical_bout_id"],
                    "fight_date": source["fight_date"],
                    "fold_id": fold_id,
                    "target_fighter_a_won": int(source[accepted.target_column]),
                    "xgboost_forward_probability": float(xp_f),
                    "xgboost_swapped_probability": float(xp_s),
                    "xgboost_symmetric_probability": float(xp),
                    "logistic_forward_probability": float(lp_f),
                    "logistic_swapped_probability": float(lp_s),
                    "logistic_symmetric_probability": float(lp),
                    "xgboost_best_iteration_count": best_iterations[-1],
                }
            )
        del logistic, xgboost_model
        gc.collect()
    oof = (
        pd.DataFrame(base_rows).sort_values(["fold_id", "canonical_bout_id"]).reset_index(drop=True)
    )
    if (
        len(oof) != len(oof_validation_keys)
        or oof["canonical_bout_id"].duplicated().any()
        or set(oof["canonical_bout_id"]) != oof_validation_keys
        or set(oof["canonical_bout_id"]) & benchmark_keys
    ):
        raise ValueError("Phase 4A OOF contract failed")
    # A calibration observation is valid for an outer fold only if it was
    # generated by an earlier outer model and predates that validation window.
    # This reuses the persisted-statistically-valid OOF predictions without
    # allowing later-fold labels into an earlier calibration decision.
    candidates = _candidates(include_isotonic=True)
    fold_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    calibrator_rows: list[dict[str, Any]] = []
    for fold_id in members:
        validation = oof[oof["fold_id"] == fold_id].copy()
        validation_start = validation["fight_date"].min()
        calibration = oof[oof["fight_date"] < validation_start].copy()
        target = validation["target_fighter_a_won"].to_numpy(dtype=int)
        x_probability = validation["xgboost_symmetric_probability"].to_numpy(dtype=float)
        logistic_probability = validation["logistic_symmetric_probability"].to_numpy(dtype=float)
        calibrators: dict[str, BaseEstimator] = {}
        for kind in ("platt", "isotonic"):
            has_two_classes = calibration["target_fighter_a_won"].nunique() == 2
            sufficient = has_two_classes and (
                kind != "isotonic" or len(calibration) >= ISOTONIC_MINIMUM_SAMPLES
            )
            calibrator_rows.append(
                {
                    "fold_id": fold_id,
                    "calibration_method": kind,
                    "outer_validation_start": validation_start,
                    "fit_rows": len(calibration),
                    "fit_fold_ids": sorted(calibration["fold_id"].unique().tolist()),
                    "validation_rows": len(validation),
                    "eligible": sufficient,
                    "ineligibility_reason": None
                    if sufficient
                    else "no_sufficient_strictly_prior_oof_calibration_rows",
                    "validation_labels_excluded_from_calibrator_fit": True,
                    "later_outer_fold_labels_excluded": True,
                    "base_training_excluded_validation_rows": True,
                }
            )
            if not sufficient:
                continue
            calibrators[kind] = _fit_calibrator(
                kind,
                calibration["xgboost_symmetric_probability"].to_numpy(dtype=float),
                calibration["target_fighter_a_won"].to_numpy(dtype=int),
            )
        for candidate in candidates:
            if (
                candidate.xgboost_calibration is not None
                and candidate.xgboost_calibration not in calibrators
            ):
                continue
            probability = _candidate_probability(
                candidate,
                x_probability,
                logistic_probability,
                calibrators.get(candidate.xgboost_calibration or ""),
            )
            audit = _audit(probability, 1.0 - probability)
            metrics = _metrics(target, probability)
            calibration_report = calibration_summary(target, probability)
            fold_rows.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "method": candidate.method,
                    "xgboost_calibration": candidate.xgboost_calibration,
                    "xgboost_weight": candidate.xgboost_weight,
                    "fold_id": fold_id,
                    "metrics": metrics,
                    "calibration": calibration_report,
                    "audit": audit,
                    "train_rows": len(members[fold_id]["train"]),
                    "validation_rows": len(validation),
                }
            )
            for source, p in zip(validation.to_dict(orient="records"), probability, strict=True):
                prediction_rows.append(
                    {
                        "canonical_bout_id": source["canonical_bout_id"],
                        "fight_date": source["fight_date"],
                        "evaluation_partition": "rolling_validation",
                        "fold_id": fold_id,
                        "candidate_id": candidate.candidate_id,
                        "target_fighter_a_won": int(source["target_fighter_a_won"]),
                        "probability_fighter_a_wins": float(p),
                        "xgboost_symmetric_probability": float(
                            source["xgboost_symmetric_probability"]
                        ),
                        "logistic_symmetric_probability": float(
                            source["logistic_symmetric_probability"]
                        ),
                        "complement_probability_swapped_corner": float(1.0 - p),
                        "complement_error": 0.0,
                    }
                )
    grouped: dict[str, list[dict[str, Any]]] = {
        candidate.candidate_id: [] for candidate in candidates
    }
    for row in fold_rows:
        grouped[row["candidate_id"]].append(row)
    aggregates = {
        candidate_id: {
            **_summary(rows),
            "eligible_fold_count": len(rows),
            "selection_eligible": len(rows) == len(members),
        }
        for candidate_id, rows in grouped.items()
    }
    selected_id = select_phase4a_candidate(aggregates, candidates)
    selected_candidate = next(
        candidate for candidate in candidates if candidate.candidate_id == selected_id
    )
    control_rows = [
        row for row in phase3c_metrics["fold_results"] if row["candidate_id"] == PHASE3C_CHAMPION_ID
    ]
    control = dict(phase3c_metrics["candidate_aggregates"][PHASE3C_CHAMPION_ID])
    control["mean_ece"] = float(
        np.mean([row["calibration"]["expected_calibration_error"] for row in control_rows])
    )
    comparison = _promotion(aggregates[selected_id], control)

    # Freeze selection before the one permitted benchmark evaluation.
    development = keyed.loc[sorted(development_keys)].reset_index(drop=True)
    benchmark = keyed.loc[sorted(benchmark_keys)].reset_index(drop=True)
    development_y = development[accepted.target_column].astype(int).to_numpy()
    logistic_final = build_logistic_pipeline().fit(_matrix(development, features), development_y)
    rounds = int(median(best_iterations))
    xgboost_final = _build_xgboost(rounds=rounds)
    augmented = _augment(development, features=features, target=accepted.target_column)
    cast(Any, xgboost_final).fit(
        _matrix(augmented, features),
        augmented[accepted.target_column].astype(int).to_numpy(),
        verbose=False,
    )
    x_forward, x_swapped, x_symmetric = _predict_triplet(
        xgboost_final, benchmark, features, accepted.target_column
    )
    l_forward, l_swapped, l_symmetric = _predict_triplet(
        logistic_final, benchmark, features, accepted.target_column
    )
    final_calibrator: BaseEstimator | None = None
    if selected_candidate.xgboost_calibration is not None:
        benchmark_start = benchmark["fight_date"].min()
        final_calibration = oof[oof["fight_date"] < benchmark_start]
        if len(final_calibration) != len(oof):
            raise ValueError("benchmark calibrator would include non-prior development OOF rows")
        final_calibrator = _fit_calibrator(
            selected_candidate.xgboost_calibration,
            final_calibration["xgboost_symmetric_probability"].to_numpy(dtype=float),
            final_calibration["target_fighter_a_won"].to_numpy(dtype=int),
        )
    selected_probability = _candidate_probability(
        selected_candidate, x_symmetric, l_symmetric, final_calibrator
    )
    benchmark_y = benchmark[accepted.target_column].astype(int).to_numpy()
    benchmark_report = {
        "metrics": _metrics(benchmark_y, selected_probability),
        "calibration": calibration_summary(benchmark_y, selected_probability),
        "corner_swap_audit": _audit(selected_probability, 1.0 - selected_probability),
        "per_year": _year_summary(benchmark, benchmark_y, selected_probability),
        "inspected_benchmark_only": True,
    }
    for source, xp, lp, p in zip(
        benchmark[["canonical_bout_id", "fight_date", accepted.target_column]].to_dict(
            orient="records"
        ),
        x_symmetric,
        l_symmetric,
        selected_probability,
        strict=True,
    ):
        prediction_rows.append(
            {
                "canonical_bout_id": source["canonical_bout_id"],
                "fight_date": source["fight_date"],
                "evaluation_partition": "inspected_locked_benchmark",
                "fold_id": None,
                "candidate_id": selected_id,
                "target_fighter_a_won": int(source[accepted.target_column]),
                "probability_fighter_a_wins": float(p),
                "xgboost_symmetric_probability": float(xp),
                "logistic_symmetric_probability": float(lp),
                "complement_probability_swapped_corner": float(1.0 - p),
                "complement_error": 0.0,
            }
        )

    run_dir = output_root / accepted.generation_id
    run_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "oof_predictions": run_dir / "m4_phase4a_out_of_fold_predictions.parquet",
        "calibration_candidates": run_dir / "m4_phase4a_calibration_candidates.parquet",
        "blend_grid": run_dir / "m4_phase4a_blend_grid_results.parquet",
        "fold_metrics": run_dir / "m4_phase4a_fold_metrics.parquet",
        "benchmark_predictions": run_dir / "m4_phase4a_benchmark_predictions.parquet",
        "metrics": run_dir / "m4_phase4a_metrics.json",
        "comparison": run_dir / "m4_phase4a_model_comparison.json",
        "calibration_curves": run_dir / "m4_phase4a_calibration_curves.json",
        "contract": run_dir / "m4_phase4a_feature_model_contract.json",
        "selected_artifact": run_dir / "m4_phase4a_selected_calibrated_blend.joblib",
    }
    pl.DataFrame(oof.to_dict(orient="list")).sort(["fold_id", "canonical_bout_id"]).write_parquet(
        paths["oof_predictions"], compression="zstd"
    )
    calibration_frame = pl.DataFrame(calibrator_rows).sort(["calibration_method", "fold_id"])
    calibration_frame.write_parquet(paths["calibration_candidates"], compression="zstd")
    metrics_frame = pl.DataFrame(
        [
            {
                "candidate_id": row["candidate_id"],
                "method": row["method"],
                "xgboost_calibration": row["xgboost_calibration"],
                "xgboost_weight": row["xgboost_weight"],
                "fold_id": row["fold_id"],
                "validation_log_loss": row["metrics"]["log_loss"],
                "validation_brier_score": row["metrics"]["brier_score"],
                "validation_roc_auc": row["metrics"]["roc_auc"],
                "validation_ece": row["calibration"]["expected_calibration_error"],
                "symmetric_maximum_complement_error": row["audit"]["symmetrized"][
                    "maximum_absolute_complement_error"
                ],
            }
            for row in fold_rows
        ]
    ).sort(["candidate_id", "fold_id"])
    metrics_frame.write_parquet(paths["fold_metrics"], compression="zstd")
    metrics_frame.filter(pl.col("method") == "fixed_grid_blend").write_parquet(
        paths["blend_grid"], compression="zstd"
    )
    all_predictions = pl.DataFrame(pd.DataFrame(prediction_rows).to_dict(orient="list")).sort(
        ["evaluation_partition", "candidate_id", "fold_id", "canonical_bout_id"], nulls_last=True
    )
    all_predictions.filter(
        pl.col("evaluation_partition") == "inspected_locked_benchmark"
    ).write_parquet(paths["benchmark_predictions"], compression="zstd")
    artifact = CalibratedBlendArtifact(
        tuple(features),
        accepted.target_column,
        xgboost_final,
        logistic_final,
        final_calibrator,
        selected_candidate.method,
        selected_candidate.xgboost_weight,
    )
    joblib.dump(artifact, paths["selected_artifact"], compress=3)
    contract = {
        "schema_version": M4_PHASE4A_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "accepted_m3_final_acceptance_report_sha256": ACCEPTED_M3_ACCEPTANCE_SHA256,
        "phase3c_champion_id": PHASE3C_CHAMPION_ID,
        "phase3c_feature_pack": PHASE3C_CHAMPION_PACK,
        "phase3c_manifest_sha256": PHASE3C_MANIFEST_SHA256,
        "feature_columns": list(features),
        "fold_policy": "exact accepted Phase 3A rolling folds",
        "oof_calibration_policy": (
            "fit each fold calibrator only on strictly earlier outer-fold OOF predictions"
        ),
        "benchmark_policy": (
            "excluded from fitting, calibration, blending, selection, and promotion"
        ),
        "symmetry_policy": (
            "symmetrize base probabilities before post-processing; symmetrize calibrator outputs"
        ),
        "blend_weights": list(BLEND_WEIGHTS),
        "isotonic_minimum_samples": ISOTONIC_MINIMUM_SAMPLES,
    }
    metrics = {
        "schema_version": M4_PHASE4A_SCHEMA_VERSION,
        "candidate_aggregates": aggregates,
        "fold_results": fold_rows,
        "selection": {
            "selected_method": selected_candidate.method,
            "selected_candidate_id": selected_id,
            "selected_xgboost_weight": selected_candidate.xgboost_weight,
            "selected_xgboost_calibration": selected_candidate.xgboost_calibration,
            "priority": [
                "mean_log_loss",
                "brier_score",
                "ece",
                "roc_auc",
                "log_loss_standard_deviation",
                "worst_fold_log_loss",
                "simpler_method",
            ],
            "selection_scope": "development_period_out_of_fold_only",
            "benchmark_excluded": True,
            "isotonic_minimum_samples": ISOTONIC_MINIMUM_SAMPLES,
            "final_xgboost_rounds": rounds,
        },
        "inspected_locked_benchmark": benchmark_report,
    }
    curves = {
        "schema_version": M4_PHASE4A_SCHEMA_VERSION,
        "development": {
            candidate_id: [row["calibration"] for row in grouped[candidate_id]]
            for candidate_id in grouped
        },
        "inspected_benchmark_selected": benchmark_report["calibration"],
    }
    _write_json(paths["metrics"], _to_builtin(metrics))
    _write_json(
        paths["comparison"],
        _to_builtin(
            {
                "schema_version": M4_PHASE4A_SCHEMA_VERSION,
                **comparison,
                "inspected_benchmark": benchmark_report,
            }
        ),
    )
    _write_json(paths["calibration_curves"], _to_builtin(curves))
    _write_json(paths["contract"], _to_builtin(contract))
    protected_after = {name: _artifact_hashes(path) for name, path in protected_dirs.items()}
    if protected_before != protected_after:
        raise ValueError("Phase 4A changed protected accepted artifacts")
    manifest_path = run_dir / "m4_phase4a_training_manifest.json"
    manifest = {
        "schema_version": M4_PHASE4A_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "input_hashes": {
            **b1_hashes,
            "phase3a_rolling_folds.parquet": _sha256_path(
                phase3a_dir / "m4_phase3a_rolling_folds.parquet"
            ),
            "phase3a_predictions.parquet": _sha256_path(
                phase3a_dir / "m4_phase3a_predictions.parquet"
            ),
            "phase3c_manifest": PHASE3C_MANIFEST_SHA256,
            "phase3d_manifest": _sha256_path(
                protected_dirs["phase3d"] / "m4_phase3d_training_manifest.json"
            ),
        },
        "protected_artifacts_sha256": protected_before,
        "artifact_shapes": {
            "oof_predictions": {"rows": len(oof), "columns": len(oof.columns)},
            "fold_metrics": {"rows": metrics_frame.height, "columns": metrics_frame.width},
            "benchmark_predictions": {"rows": 1337, "columns": all_predictions.width},
        },
        "selection": metrics["selection"],
        "output_paths": {name: str(path) for name, path in paths.items()},
        "output_checksums": {name: _sha256_path(path) for name, path in paths.items()},
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "xgboost": xgb.__version__,
            "random_seed": RANDOM_SEED,
            "n_jobs": 1,
        },
    }
    _write_json(manifest_path, _to_builtin(manifest))
    return {
        "run_directory": str(run_dir),
        "selected_method": selected_candidate.method,
        "selected_candidate_id": selected_id,
        "champion_promoted": comparison["champion_promoted"],
        "training_manifest_path": str(manifest_path),
        "training_manifest_sha256": _sha256_path(manifest_path),
    }
