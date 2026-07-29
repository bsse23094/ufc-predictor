"""M4 Phase 3D bounded, development-only Optuna tuning."""

from __future__ import annotations

import gc
import json
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, cast

import joblib
import numpy as np
import optuna
import pandas as pd
import polars as pl
import sklearn
import xgboost as xgb

from ufc_predictor.training.m4_baselines import (
    ACCEPTED_M3_ACCEPTANCE_SHA256,
    RANDOM_SEED,
    _metrics,
    _sha256_path,
    _to_builtin,
    _write_json,
    _year_summary,
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
    _matrix,
    _predict_triplet,
)
from ufc_predictor.training.m4_xgboost import EARLY_STOPPING_ROUNDS, MAX_BOOSTING_ROUNDS

M4_PHASE3D_SCHEMA_VERSION = "m4.phase3d.bounded_optuna_phase3c_champion.v1"
OPTUNA_VERSION = "4.5.0"
OPTUNA_SAMPLER_SEED = 20260722
TRIAL_COUNT = 40
PHASE3C_MANIFEST_SHA256 = "279ac89a5494ce913849a17a8c713f02e3060d5e6344170dce35a91a82c0f29a"
PHASE3C_CHAMPION_ID = "overall_elo_plus_recent_adjusted__phase3a_shallow_xgboost"
PHASE3C_CHAMPION_PACK = "overall_elo_plus_recent_adjusted"
PHASE3C_MEAN_LOG_LOSS = 0.667716
PHASE3C_BRIER = 0.237535
PHASE3C_ROC_AUC = 0.629315
PROMOTION_LOG_LOSS_IMPROVEMENT = 0.001
MAX_BRIER_REGRESSION = 0.001
MAX_ROC_AUC_REGRESSION = 0.005
MAX_WORST_LOG_LOSS_REGRESSION = 0.002
MAX_ECE_REGRESSION = 0.005
MAX_SYMMETRY_ERROR = 1e-6


@dataclass(frozen=True, slots=True)
class TrialAggregate:
    """The development-only deterministic result for one Optuna trial."""

    number: int
    params: dict[str, float | int]
    mean_log_loss: float
    std_log_loss: float
    mean_brier_score: float
    mean_roc_auc: float
    worst_fold_log_loss: float
    mean_ece: float
    mean_symmetric_complement_error: float
    best_iteration_counts: list[int]
    improvement_fold_count: int
    fold_losses: dict[str, float]

    @property
    def objectives(self) -> tuple[float, float, float, float, float]:
        """Fixed lexicographic objective values; no weighted score is used."""

        return (
            self.mean_log_loss,
            self.std_log_loss,
            self.mean_brier_score,
            -self.mean_roc_auc,
            float(self.params["max_depth"]),
        )


def _build_xgboost(params: Mapping[str, float | int], *, rounds: int) -> xgb.XGBClassifier:
    return xgb.XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        n_estimators=rounds,
        random_state=RANDOM_SEED,
        n_jobs=1,
        tree_method="hist",
        device="cpu",
        verbosity=0,
        early_stopping_rounds=EARLY_STOPPING_ROUNDS if rounds == MAX_BOOSTING_ROUNDS else None,
        **params,
    )


def _suggest_params(trial: optuna.Trial) -> dict[str, float | int]:
    return {
        "max_depth": trial.suggest_int("max_depth", 1, 4),
        "min_child_weight": trial.suggest_int("min_child_weight", 3, 16),
        "learning_rate": trial.suggest_float("learning_rate", 0.015, 0.08, log=True),
        "subsample": trial.suggest_float("subsample", 0.70, 1.00),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.55, 1.00),
        "reg_alpha": trial.suggest_float("reg_alpha", 0.0, 2.0),
        "reg_lambda": trial.suggest_float("reg_lambda", 2.0, 20.0, log=True),
        "gamma": trial.suggest_float("gamma", 0.0, 1.5),
    }


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


def _aggregate(
    number: int, params: dict[str, float | int], rows: list[dict[str, Any]]
) -> TrialAggregate:
    metrics = [cast(dict[str, float], row["metrics"]) for row in rows]
    losses = [metric["log_loss"] for metric in metrics]
    return TrialAggregate(
        number=number,
        params=params,
        mean_log_loss=float(np.mean(losses)),
        std_log_loss=float(np.std(losses)),
        mean_brier_score=float(np.mean([metric["brier_score"] for metric in metrics])),
        mean_roc_auc=float(np.mean([metric["roc_auc"] for metric in metrics])),
        worst_fold_log_loss=float(max(losses)),
        mean_ece=float(
            np.mean(
                [
                    cast(dict[str, float], row["calibration"])["expected_calibration_error"]
                    for row in rows
                ]
            )
        ),
        mean_symmetric_complement_error=float(
            np.mean(
                [row["audit"]["symmetrized"]["maximum_absolute_complement_error"] for row in rows]
            )
        ),
        best_iteration_counts=[int(row["best_iteration_count"]) for row in rows],
        improvement_fold_count=0,
        fold_losses={str(row["fold_id"]): float(row["metrics"]["log_loss"]) for row in rows},
    )


def select_best_trial(
    trials: list[TrialAggregate], control_losses: Mapping[str, float]
) -> TrialAggregate:
    """Use the stated objective hierarchy, then deterministic trial number."""

    enriched = [
        TrialAggregate(
            number=trial.number,
            params=trial.params,
            mean_log_loss=trial.mean_log_loss,
            std_log_loss=trial.std_log_loss,
            mean_brier_score=trial.mean_brier_score,
            mean_roc_auc=trial.mean_roc_auc,
            worst_fold_log_loss=trial.worst_fold_log_loss,
            mean_ece=trial.mean_ece,
            mean_symmetric_complement_error=trial.mean_symmetric_complement_error,
            best_iteration_counts=trial.best_iteration_counts,
            improvement_fold_count=sum(
                trial.fold_losses[fold] < control_losses[fold] for fold in sorted(control_losses)
            ),
            fold_losses=trial.fold_losses,
        )
        for trial in trials
    ]
    return min(
        enriched,
        key=lambda trial: (*trial.objectives, trial.number),
    )


def _load_phase3c(
    phase3c_dir: Path, base_features: tuple[str, ...]
) -> tuple[pd.DataFrame, tuple[str, ...], dict[str, Any], dict[str, Any]]:
    manifest_path = phase3c_dir / "m4_phase3c_training_manifest.json"
    if _sha256_path(manifest_path) != PHASE3C_MANIFEST_SHA256:
        raise ValueError("accepted Phase 3C manifest hash changed")
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    for name, expected in cast(dict[str, str], manifest["output_checksums"]).items():
        filename = (
            str(cast(dict[str, str], manifest["output_paths"])[name])
            .replace("\\", "/")
            .split("/")[-1]
        )
        if _sha256_path(phase3c_dir / filename) != expected:
            raise ValueError(f"accepted Phase 3C output hash changed: {name}")
    packs = cast(
        dict[str, Any], json.loads((phase3c_dir / "m4_phase3c_feature_packs.json").read_text())
    )
    definition = next(
        item
        for item in cast(list[dict[str, Any]], packs["packs"])
        if item["pack_id"] == PHASE3C_CHAMPION_PACK
    )
    feature_columns = tuple(cast(list[str], definition["feature_columns"]))
    if feature_columns[: len(base_features)] != base_features:
        raise ValueError("Phase 3C champion does not retain accepted M3 base features")
    metrics = cast(
        dict[str, Any], json.loads((phase3c_dir / "m4_phase3c_metrics.json").read_text())
    )
    if metrics["selection"]["selected_leader"] != PHASE3C_CHAMPION_ID:
        raise ValueError("Phase 3C champion changed")
    pairwise = pd.DataFrame(
        pl.read_parquet(
            phase3c_dir / "m4_phase3c_pairwise_opponent_adjusted_performance.parquet"
        ).to_dicts()
    )
    return pairwise, feature_columns, metrics, manifest


def _promotion(winner: TrialAggregate, control: Mapping[str, Any]) -> dict[str, object]:
    loss_delta = winner.mean_log_loss - float(control["mean_log_loss"])
    checks = {
        "minimum_log_loss_improvement": loss_delta <= -PROMOTION_LOG_LOSS_IMPROVEMENT,
        "improves_at_least_two_folds": winner.improvement_fold_count >= 2,
        "brier_not_meaningfully_worse": winner.mean_brier_score
        <= float(control["mean_brier_score"]) + MAX_BRIER_REGRESSION,
        "roc_auc_not_meaningfully_worse": winner.mean_roc_auc
        >= float(control["mean_roc_auc"]) - MAX_ROC_AUC_REGRESSION,
        "worst_fold_not_meaningfully_worse": winner.worst_fold_log_loss
        <= float(control["worst_fold_log_loss"]) + MAX_WORST_LOG_LOSS_REGRESSION,
        "calibration_not_meaningfully_worse": winner.mean_ece
        <= float(control["mean_ece"]) + MAX_ECE_REGRESSION,
        "exact_symmetry": winner.mean_symmetric_complement_error <= MAX_SYMMETRY_ERROR,
    }
    return {
        "phase3c_champion": control,
        "phase3c_rounded_reference": {
            "mean_log_loss": PHASE3C_MEAN_LOG_LOSS,
            "brier_score": PHASE3C_BRIER,
            "roc_auc": PHASE3C_ROC_AUC,
        },
        "mean_log_loss_delta_vs_phase3c": loss_delta,
        "promotion_threshold": PROMOTION_LOG_LOSS_IMPROVEMENT,
        "promotion_checks": checks,
        "champion_promoted": all(checks.values()),
        "result": "promoted" if all(checks.values()) else "non_promoted_retain_phase3c_champion",
    }


def run_m4_optuna_tuning(
    *,
    m3_root: Path = Path("data/processed/m3-v6"),
    phase1_root: Path = Path("data/processed/m4-baselines"),
    phase2_root: Path = Path("data/processed/m4-phase2-symmetry"),
    phase3a_root: Path = Path("data/processed/m4-phase3a-xgboost"),
    phase3b1_root: Path = Path("data/processed/m4-phase3b1-opponent-strength"),
    phase3c_root: Path = Path("data/processed/m4-phase3c-opponent-adjusted-performance"),
    output_root: Path = Path("data/processed/m4-phase3d-optuna"),
) -> dict[str, object]:
    """Tune exactly 40 Phase 3C champion-pack configurations on development folds."""

    if optuna.__version__ != OPTUNA_VERSION:
        raise RuntimeError(f"Optuna must be pinned to {OPTUNA_VERSION}")
    np.random.seed(RANDOM_SEED)
    accepted = load_accepted_m3_data(m3_root)
    protected_dirs = {
        "phase1": phase1_root / accepted.generation_id,
        "phase2": phase2_root / accepted.generation_id,
        "phase3a": phase3a_root / accepted.generation_id,
        "phase3b1": phase3b1_root / accepted.generation_id,
        "phase3c": phase3c_root / accepted.generation_id,
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
        raise ValueError("accepted Phase 3A fold or benchmark hash changed")
    elo_pairwise, _overall, b1_hashes = _verify_b1_elo_inputs(
        protected_dirs["phase3b1"], accepted.feature_columns
    )
    phase3c_pairwise, feature_columns, phase3c_metrics, phase3c_manifest = _load_phase3c(
        phase3c_dir, accepted.feature_columns
    )
    base = pd.DataFrame(accepted.frame.to_dicts())
    for frame in (base, elo_pairwise, phase3c_pairwise):
        frame["fight_date"] = pd.to_datetime(frame["fight_date"], errors="raise").dt.normalize()
    keys = ["canonical_bout_id", "fight_date", "canonical_fighter_a_id", "canonical_fighter_b_id"]
    needed = [name for name in feature_columns if name not in set(accepted.feature_columns)]
    data = base.merge(
        elo_pairwise.loc[:, [*keys, *[name for name in needed if name in elo_pairwise.columns]]],
        on=keys,
        validate="one_to_one",
    ).merge(
        phase3c_pairwise.loc[
            :, [*keys, *[name for name in needed if name in phase3c_pairwise.columns]]
        ],
        on=keys,
        validate="one_to_one",
    )
    if set(feature_columns) - set(data.columns):
        raise ValueError("Phase 3C champion feature pack cannot be reconstructed exactly")
    split_frame = pl.read_parquet(phase3a_dir / "m4_phase3a_rolling_folds.parquet")
    phase3a_predictions = pl.read_parquet(phase3a_dir / "m4_phase3a_predictions.parquet")
    members = _fold_members(split_frame)
    benchmark_keys = set(
        phase3a_predictions.filter(pl.col("evaluation_partition") == "locked_benchmark")[
            "canonical_bout_id"
        ].to_list()
    )
    development_keys = set().union(
        *(item["train"] | item["validation"] for item in members.values())
    )
    if (
        len(members) != 3
        or len(benchmark_keys) != 1337
        or len(development_keys) != 7575
        or development_keys & benchmark_keys
        or any(item["train"] & item["validation"] for item in members.values())
    ):
        raise ValueError("accepted Phase 3A split contract changed")
    keyed = data.set_index("canonical_bout_id", drop=False)
    if set(keyed.index) != development_keys | benchmark_keys:
        raise ValueError("Phase 3D rows do not exactly match accepted Phase 3A keys")
    control_rows = [
        row
        for row in cast(list[dict[str, Any]], phase3c_metrics["fold_results"])
        if row["candidate_id"] == PHASE3C_CHAMPION_ID
    ]
    control_losses = {
        str(row["fold_id"]): float(row["metrics"]["log_loss"]) for row in control_rows
    }
    if len(control_losses) != 3:
        raise ValueError("Phase 3C champion fold control is incomplete")
    control = dict(
        cast(dict[str, Any], phase3c_metrics["candidate_aggregates"])[PHASE3C_CHAMPION_ID]
    )
    # Phase 3C's compact aggregate omitted ECE, while retaining each fold's
    # calibration record. Reconstruct the same unweighted fold mean here.
    control["mean_ece"] = float(
        np.mean([float(row["calibration"]["expected_calibration_error"]) for row in control_rows])
    )

    sampler = optuna.samplers.NSGAIISampler(seed=OPTUNA_SAMPLER_SEED)
    study = optuna.create_study(
        directions=["minimize", "minimize", "minimize", "maximize", "minimize"],
        sampler=sampler,
        study_name="m4_phase3d_bounded_phase3c_champion",
    )
    trial_aggregates: list[TrialAggregate] = []
    fold_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, object]] = []
    for _ in range(TRIAL_COUNT):
        trial = study.ask()
        params = _suggest_params(trial)
        rows: list[dict[str, Any]] = []
        for fold_id, fold in members.items():
            train = keyed.loc[sorted(fold["train"])].reset_index(drop=True)
            validation = keyed.loc[sorted(fold["validation"])].reset_index(drop=True)
            validation_y = validation[accepted.target_column].astype(int).to_numpy()
            fitting = _augment(train, features=feature_columns, target=accepted.target_column)
            model = _build_xgboost(params, rounds=MAX_BOOSTING_ROUNDS)
            cast(Any, model).fit(
                _matrix(fitting, feature_columns),
                fitting[accepted.target_column].astype(int).to_numpy(),
                eval_set=[(_matrix(validation, feature_columns), validation_y)],
                verbose=False,
            )
            forward, swapped, symmetric = _predict_triplet(
                model, validation, feature_columns, accepted.target_column
            )
            row = {
                "trial_number": trial.number,
                "fold_id": fold_id,
                "metrics": _metrics(validation_y, symmetric),
                "calibration": calibration_summary(validation_y, symmetric),
                "audit": _audit(forward, swapped),
                "best_iteration_count": _best_iteration(model),
                "train_rows": len(train),
                "validation_rows": len(validation),
            }
            rows.append(row)
            for source, p_forward, p_swapped, p_symmetric in zip(
                validation[["canonical_bout_id", "fight_date", accepted.target_column]].to_dict(
                    orient="records"
                ),
                forward,
                swapped,
                symmetric,
                strict=True,
            ):
                prediction_rows.append(
                    {
                        "trial_number": trial.number,
                        "canonical_bout_id": source["canonical_bout_id"],
                        "fight_date": source["fight_date"],
                        "evaluation_partition": "rolling_validation",
                        "fold_id": fold_id,
                        "target_fighter_a_won": int(source[accepted.target_column]),
                        "forward_probability": float(p_forward),
                        "swapped_probability": float(p_swapped),
                        "symmetric_probability": float(p_symmetric),
                    }
                )
            del model
            gc.collect()
        aggregate = _aggregate(trial.number, params, rows)
        study.tell(trial, aggregate.objectives)
        trial_aggregates.append(aggregate)
        fold_rows.extend([{**row, "params": params} for row in rows])
    if len(study.trials) != TRIAL_COUNT or len(trial_aggregates) != TRIAL_COUNT:
        raise ValueError("Phase 3D requires exactly 40 complete Optuna trials")
    trial_aggregates = [
        TrialAggregate(
            number=trial.number,
            params=trial.params,
            mean_log_loss=trial.mean_log_loss,
            std_log_loss=trial.std_log_loss,
            mean_brier_score=trial.mean_brier_score,
            mean_roc_auc=trial.mean_roc_auc,
            worst_fold_log_loss=trial.worst_fold_log_loss,
            mean_ece=trial.mean_ece,
            mean_symmetric_complement_error=trial.mean_symmetric_complement_error,
            best_iteration_counts=trial.best_iteration_counts,
            improvement_fold_count=sum(
                trial.fold_losses[fold] < control_losses[fold] for fold in sorted(control_losses)
            ),
            fold_losses=trial.fold_losses,
        )
        for trial in trial_aggregates
    ]
    winner = select_best_trial(trial_aggregates, control_losses)
    winner_params = winner.params
    comparison = _promotion(winner, control)

    development = keyed.loc[sorted(development_keys)].reset_index(drop=True)
    benchmark = keyed.loc[sorted(benchmark_keys)].reset_index(drop=True)
    final_rounds = int(median(winner.best_iteration_counts))
    final_model = _build_xgboost(winner_params, rounds=final_rounds)
    fitting = _augment(development, features=feature_columns, target=accepted.target_column)
    cast(Any, final_model).fit(
        _matrix(fitting, feature_columns),
        fitting[accepted.target_column].astype(int).to_numpy(),
        verbose=False,
    )
    benchmark_y = benchmark[accepted.target_column].astype(int).to_numpy()
    forward, swapped, symmetric = _predict_triplet(
        final_model, benchmark, feature_columns, accepted.target_column
    )
    benchmark_report = {
        "metrics": _metrics(benchmark_y, symmetric),
        "calibration": calibration_summary(benchmark_y, symmetric),
        "corner_swap_audit": _audit(forward, swapped),
        "per_year": _year_summary(benchmark, benchmark_y, symmetric),
        "inspected_benchmark_only": True,
    }
    for source, p_forward, p_swapped, p_symmetric in zip(
        benchmark[["canonical_bout_id", "fight_date", accepted.target_column]].to_dict(
            orient="records"
        ),
        forward,
        swapped,
        symmetric,
        strict=True,
    ):
        prediction_rows.append(
            {
                "trial_number": winner.number,
                "canonical_bout_id": source["canonical_bout_id"],
                "fight_date": source["fight_date"],
                "evaluation_partition": "inspected_locked_benchmark",
                "fold_id": None,
                "target_fighter_a_won": int(source[accepted.target_column]),
                "forward_probability": float(p_forward),
                "swapped_probability": float(p_swapped),
                "symmetric_probability": float(p_symmetric),
            }
        )

    run_dir = output_root / accepted.generation_id
    run_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "study": run_dir / "m4_phase3d_optuna_study.json",
        "trials": run_dir / "m4_phase3d_optuna_trials.parquet",
        "fold_metrics": run_dir / "m4_phase3d_fold_metrics.parquet",
        "predictions": run_dir / "m4_phase3d_predictions.parquet",
        "selected_parameters": run_dir / "m4_phase3d_selected_parameters.json",
        "metrics": run_dir / "m4_phase3d_metrics.json",
        "comparison": run_dir / "m4_phase3d_model_comparison.json",
        "feature_contract": run_dir / "m4_phase3d_feature_contract.json",
        "selected_model": run_dir / "m4_phase3d_selected_model.joblib",
    }
    persisted_trials = [
        {
            "number": trial.number,
            "mean_log_loss": trial.mean_log_loss,
            "std_log_loss": trial.std_log_loss,
            "mean_brier_score": trial.mean_brier_score,
            "mean_roc_auc": trial.mean_roc_auc,
            "worst_fold_log_loss": trial.worst_fold_log_loss,
            "mean_ece": trial.mean_ece,
            "mean_symmetric_complement_error": trial.mean_symmetric_complement_error,
            "best_iteration_counts": trial.best_iteration_counts,
            "improvement_fold_count": trial.improvement_fold_count,
            "params": trial.params,
            "objectives": trial.objectives,
        }
        for trial in trial_aggregates
    ]
    trials_frame = pl.DataFrame(
        [
            {
                "trial_number": trial["number"],
                **cast(dict[str, float | int], trial["params"]),
                "mean_log_loss": trial["mean_log_loss"],
                "std_log_loss": trial["std_log_loss"],
                "mean_brier_score": trial["mean_brier_score"],
                "mean_roc_auc": trial["mean_roc_auc"],
                "worst_fold_log_loss": trial["worst_fold_log_loss"],
                "mean_ece": trial["mean_ece"],
                "mean_symmetric_complement_error": trial["mean_symmetric_complement_error"],
                "improvement_fold_count": trial["improvement_fold_count"],
                "best_iteration_counts": json.dumps(trial["best_iteration_counts"]),
            }
            for trial in persisted_trials
        ]
    ).sort("trial_number")
    fold_frame = pl.DataFrame(
        [
            {
                "trial_number": row["trial_number"],
                "fold_id": row["fold_id"],
                **cast(dict[str, float | int], row["params"]),
                "validation_log_loss": row["metrics"]["log_loss"],
                "validation_brier_score": row["metrics"]["brier_score"],
                "validation_roc_auc": row["metrics"]["roc_auc"],
                "validation_ece": row["calibration"]["expected_calibration_error"],
                "best_iteration_count": row["best_iteration_count"],
                "symmetric_maximum_complement_error": row["audit"]["symmetrized"][
                    "maximum_absolute_complement_error"
                ],
            }
            for row in fold_rows
        ]
    ).sort(["trial_number", "fold_id"])
    prediction_frame = pl.DataFrame(pd.DataFrame(prediction_rows).to_dict(orient="list")).sort(
        ["evaluation_partition", "trial_number", "fold_id", "canonical_bout_id"], nulls_last=True
    )
    _write_json(
        paths["study"],
        _to_builtin(
            {
                "schema_version": M4_PHASE3D_SCHEMA_VERSION,
                "optuna_version": optuna.__version__,
                "study_name": study.study_name,
                "sampler": "NSGAIISampler",
                "sampler_seed": OPTUNA_SAMPLER_SEED,
                "directions": ["minimize", "minimize", "minimize", "maximize", "minimize"],
                "trial_count": TRIAL_COUNT,
                "selection_policy": "lexicographic objectives then trial number; no weighted score",
                "trials": persisted_trials,
            }
        ),
    )
    trials_frame.write_parquet(paths["trials"], compression="zstd")
    fold_frame.write_parquet(paths["fold_metrics"], compression="zstd")
    prediction_frame.write_parquet(paths["predictions"], compression="zstd")
    _write_json(
        paths["selected_parameters"],
        _to_builtin(
            {
                "trial_number": winner.number,
                "parameters": winner_params,
                "best_iteration_counts": winner.best_iteration_counts,
                "final_boosting_rounds": final_rounds,
                "round_policy": (
                    "median of selected trial development-fold early-stopping iterations"
                ),
            }
        ),
    )
    _write_json(
        paths["metrics"],
        _to_builtin(
            {
                "schema_version": M4_PHASE3D_SCHEMA_VERSION,
                "trial_count": TRIAL_COUNT,
                "selected_trial": persisted_trials[winner.number],
                "phase3c_champion": control,
                "selection_scope": "development_rolling_validation_only",
                "benchmark_excluded_from_tuning": True,
                "inspected_locked_benchmark": benchmark_report,
            }
        ),
    )
    _write_json(
        paths["comparison"],
        _to_builtin(
            {
                "schema_version": M4_PHASE3D_SCHEMA_VERSION,
                **comparison,
                "inspected_benchmark": benchmark_report,
            }
        ),
    )
    _write_json(
        paths["feature_contract"],
        _to_builtin(
            {
                "schema_version": M4_PHASE3D_SCHEMA_VERSION,
                "accepted_m3_generation_id": accepted.generation_id,
                "accepted_m3_final_acceptance_report_sha256": ACCEPTED_M3_ACCEPTANCE_SHA256,
                "source_phase3c_manifest_sha256": PHASE3C_MANIFEST_SHA256,
                "source_phase3c_champion": PHASE3C_CHAMPION_ID,
                "feature_pack": PHASE3C_CHAMPION_PACK,
                "feature_columns": feature_columns,
                "fold_reuse_verified": True,
                "benchmark_selection_policy": (
                    "benchmark excluded from tuning, selection, and early stopping"
                ),
                "training_policy": (
                    "swap augmented; native missing-value routing; symmetrized inference"
                ),
                "search_space": {
                    "max_depth": [1, 4],
                    "min_child_weight": [3, 16],
                    "learning_rate": [0.015, 0.08, "log"],
                    "subsample": [0.70, 1.00],
                    "colsample_bytree": [0.55, 1.00],
                    "reg_alpha": [0.0, 2.0],
                    "reg_lambda": [2.0, 20.0, "log"],
                    "gamma": [0.0, 1.5],
                },
            }
        ),
    )
    joblib.dump(final_model, paths["selected_model"], compress=3)
    protected_after = {name: _artifact_hashes(path) for name, path in protected_dirs.items()}
    if protected_before != protected_after:
        raise ValueError("Phase 3D changed protected accepted artifacts")
    manifest_path = run_dir / "m4_phase3d_training_manifest.json"
    manifest = {
        "schema_version": M4_PHASE3D_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "input_hashes": {
            "m3_model_ready_binary.parquet": accepted.artifact_sha256,
            "phase3a_rolling_folds.parquet": PHASE3A_FOLDS_SHA256,
            "phase3a_predictions.parquet": PHASE3A_PREDICTIONS_SHA256,
            "phase3c_manifest": PHASE3C_MANIFEST_SHA256,
            **b1_hashes,
            **cast(dict[str, str], phase3c_manifest["output_checksums"]),
        },
        "trial_count": TRIAL_COUNT,
        "sampler_seed": OPTUNA_SAMPLER_SEED,
        "artifact_shapes": {
            "trials": {"rows": trials_frame.height, "columns": trials_frame.width},
            "fold_metrics": {"rows": fold_frame.height, "columns": fold_frame.width},
            "predictions": {"rows": prediction_frame.height, "columns": prediction_frame.width},
        },
        "protected_artifacts_sha256": protected_before,
        "selection": {"selected_trial": winner.number, "parameters": winner_params},
        "output_paths": {name: str(path) for name, path in paths.items()},
        "output_checksums": {name: _sha256_path(path) for name, path in paths.items()},
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "xgboost": xgb.__version__,
            "optuna": optuna.__version__,
            "random_seed": RANDOM_SEED,
            "n_jobs": 1,
        },
    }
    _write_json(manifest_path, _to_builtin(manifest))
    return {
        "run_directory": str(run_dir),
        "selected_trial": winner.number,
        "champion_promoted": comparison["champion_promoted"],
        "training_manifest_path": str(manifest_path),
        "training_manifest_sha256": _sha256_path(manifest_path),
    }
