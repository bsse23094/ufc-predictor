"""M4 Phase 3B2 opponent-strength feature-group ablation training."""

from __future__ import annotations

import json
import platform
from collections import defaultdict
from collections.abc import Iterable, Mapping
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
from ufc_predictor.training.m4_opponent_strength import (
    OVERALL_FEATURES,
    PHASE3A_XGBOOST_PARAMETERS,
    WEIGHT_CLASS_FEATURES,
    _artifact_hashes,
    _audit,
    _augment,
    _best_iteration,
    _build_xgboost,
    _matrix,
    _predict_triplet,
)
from ufc_predictor.training.m4_xgboost import EARLY_STOPPING_ROUNDS, MAX_BOOSTING_ROUNDS

M4_PHASE3B2_SCHEMA_VERSION = "m4.phase3b2.opponent_strength_group_ablation.v1"
B1_SNAPSHOTS_SHA256 = "308f47ad49c9583fea8d2de72feed8721192517721ace6cf6b1d94a2e0bb2dcd"
B1_PAIRWISE_SHA256 = "08e283638d95c1d4150fe7c28ce91b54d8214671be336aa4ba886f2c5aaa75fc"
B1_CONTRACT_SHA256 = "c3226d6a43797e0568cb3991db961db9e4568724a74df3e3db2a63981382e076"
PHASE3A_CONTROL_ID = "pack_a_base_130__phase3a_shallow_xgboost"
B1_OVERALL_CONTROL_ID = "pack_b_overall_elo__phase3a_shallow_xgboost"
CHAMPION_LOG_LOSS_IMPROVEMENT = 0.002
MAX_BRIER_REGRESSION = 0.001
MAX_ROC_AUC_REGRESSION = 0.005
MAX_WORST_LOG_LOSS_REGRESSION = 0.002
MAX_ECE_REGRESSION = 0.005
MAX_SYMMETRY_ERROR = 1e-6


@dataclass(frozen=True, slots=True)
class FeaturePack:
    """One fixed Phase 3B2 feature pack."""

    pack_id: str
    feature_columns: tuple[str, ...]
    added_feature_count: int
    complexity_rank: int


def _oriented(features: Iterable[str]) -> tuple[str, ...]:
    return tuple(f"{side}{feature}" for feature in features for side in ("a_", "b_")) + tuple(
        f"diff_{feature}" for feature in features
    )


def feature_groups() -> dict[str, tuple[str, ...]]:
    """Return the complete, disjoint B1-added feature partition."""

    career = ("pre_fight_average_opponent_elo_career",)
    recent = (
        "pre_fight_average_opponent_elo_last_3",
        "pre_fight_average_opponent_elo_last_5",
    )
    defeated = (
        "pre_fight_average_defeated_opponent_elo",
        "pre_fight_strongest_defeated_opponent_elo",
    )
    return {
        "overall_elo": (*_oriented(OVERALL_FEATURES), "elo_expected_probability_a"),
        "weight_class_elo": _oriented(WEIGHT_CLASS_FEATURES),
        "career_opponent_quality": _oriented(career),
        "recent_opponent_quality": _oriented(recent),
        "defeated_opponent_quality": _oriented(defeated),
    }


def feature_packs(base_features: tuple[str, ...]) -> tuple[FeaturePack, ...]:
    """Build precisely the eight predeclared group-ablation packs."""

    groups = feature_groups()
    overall = groups["overall_elo"]
    # Retain the B1 full-pack column ordering exactly.  XGBoost's deterministic
    # histogram implementation still treats feature order as part of model
    # identity, so group concatenation would not reproduce its locked control.
    quality = _oriented(
        (
            "pre_fight_average_opponent_elo_career",
            "pre_fight_average_opponent_elo_last_3",
            "pre_fight_average_opponent_elo_last_5",
            "pre_fight_average_defeated_opponent_elo",
            "pre_fight_strongest_defeated_opponent_elo",
        )
    )
    definitions = (
        ("pack_a_base_130", ()),
        ("pack_b_overall_elo", overall),
        ("pack_c_overall_plus_weight_class", (*overall, *groups["weight_class_elo"])),
        ("pack_d_overall_plus_career_quality", (*overall, *groups["career_opponent_quality"])),
        ("pack_e_overall_plus_recent_quality", (*overall, *groups["recent_opponent_quality"])),
        ("pack_f_overall_plus_defeated_quality", (*overall, *groups["defeated_opponent_quality"])),
        ("pack_g_overall_plus_all_quality", (*overall, *quality)),
        ("pack_h_full_phase3b1", (*overall, *groups["weight_class_elo"], *quality)),
    )
    return tuple(
        FeaturePack(pack_id, (*base_features, *added), len(added), index)
        for index, (pack_id, added) in enumerate(definitions)
    )


def _verify_b1_inputs(
    *,
    b1_dir: Path,
    base_features: tuple[str, ...],
) -> tuple[pd.DataFrame, dict[str, object], dict[str, str]]:
    """Hash-lock B1 inputs and prove that group assignment is exact."""

    paths = {
        "fighter_rating_snapshots": b1_dir / "m4_phase3b1_fighter_rating_snapshots.parquet",
        "pairwise_opponent_strength": b1_dir / "m4_phase3b1_pairwise_opponent_strength.parquet",
        "feature_contract": b1_dir / "m4_phase3b1_feature_contract.json",
        "feature_packs": b1_dir / "m4_phase3b1_feature_packs.json",
    }
    required = {
        "fighter_rating_snapshots": B1_SNAPSHOTS_SHA256,
        "pairwise_opponent_strength": B1_PAIRWISE_SHA256,
        "feature_contract": B1_CONTRACT_SHA256,
    }
    hashes = {name: _sha256_path(path) for name, path in paths.items()}
    if any(hashes[name] != expected for name, expected in required.items()):
        raise ValueError("accepted Phase 3B1 input hash changed")
    contract = cast(
        dict[str, object], json.loads(paths["feature_contract"].read_text(encoding="utf-8"))
    )
    b1_packs = cast(
        dict[str, object], json.loads(paths["feature_packs"].read_text(encoding="utf-8"))
    )
    listed = cast(list[dict[str, object]], b1_packs["packs"])
    b1_base = next(item for item in listed if item["pack_id"] == "base_130")
    b1_full = next(item for item in listed if item["pack_id"] == "base_plus_opponent_strength")
    if tuple(cast(list[str], b1_base["feature_columns"])) != base_features:
        raise ValueError("Phase 3B1 base feature contract differs from accepted M3")
    added = set(cast(list[str], b1_full["feature_columns"])) - set(base_features)
    groups = feature_groups()
    assigned = [feature for features in groups.values() for feature in features]
    if len(assigned) != len(set(assigned)) or set(assigned) != added:
        raise ValueError("Phase 3B1 feature-group assignment is incomplete or non-unique")
    pairwise = pd.DataFrame(pl.read_parquet(paths["pairwise_opponent_strength"]).to_dicts())
    if set(pairwise.columns) < {"canonical_bout_id", *assigned}:
        raise ValueError("Phase 3B1 pairwise artifact lacks assigned features")
    return pairwise, contract, hashes


def _summary(rows: list[dict[str, Any]]) -> dict[str, object]:
    metrics = [cast(dict[str, float], row["metrics"]) for row in rows]
    losses = [item["log_loss"] for item in metrics]
    return {
        "fold_count": len(rows),
        "mean_log_loss": float(np.mean(losses)),
        "mean_brier_score": float(np.mean([item["brier_score"] for item in metrics])),
        "mean_roc_auc": float(np.mean([item["roc_auc"] for item in metrics])),
        "std_log_loss": float(np.std(losses)),
        "worst_fold_log_loss": float(max(losses)),
        "mean_ece": float(
            np.mean(
                [
                    cast(dict[str, float], row["calibration"])["expected_calibration_error"]
                    for row in rows
                ]
            )
        ),
        "mean_symmetric_complement_error": float(
            np.mean(
                [row["audit"]["symmetrized"]["maximum_absolute_complement_error"] for row in rows]
            )
        ),
        "best_iteration_counts": [int(row["best_iteration_count"]) for row in rows],
    }


def _select(
    *,
    aggregates: Mapping[str, Mapping[str, object]],
    rows: Iterable[Mapping[str, Any]],
    definitions: Mapping[str, tuple[int, int]],
) -> tuple[str, dict[str, int]]:
    """Select solely from development folds using the locked B2 ordering."""

    losses = {
        (str(row["candidate_id"]), str(row["fold_id"])): float(
            cast(Mapping[str, float], row["metrics"])["log_loss"]
        )
        for row in rows
    }
    control_folds = sorted(fold for candidate, fold in losses if candidate == PHASE3A_CONTROL_ID)
    improvement_counts = {
        candidate: sum(
            losses[(candidate, fold)] < losses[(PHASE3A_CONTROL_ID, fold)] for fold in control_folds
        )
        for candidate in aggregates
    }
    selected = min(
        aggregates,
        key=lambda candidate: (
            float(cast(float, aggregates[candidate]["mean_log_loss"])),
            float(cast(float, aggregates[candidate]["mean_brier_score"])),
            -float(cast(float, aggregates[candidate]["mean_roc_auc"])),
            float(cast(float, aggregates[candidate]["std_log_loss"])),
            float(cast(float, aggregates[candidate]["worst_fold_log_loss"])),
            0 if improvement_counts[candidate] >= 2 else 1,
            definitions[candidate][0],
            definitions[candidate][1],
            candidate,
        ),
    )
    return selected, improvement_counts


def _comparison(
    *,
    selected_id: str,
    aggregates: Mapping[str, Mapping[str, object]],
    improvement_counts: Mapping[str, int],
) -> dict[str, object]:
    selected = aggregates[selected_id]
    phase3a = aggregates[PHASE3A_CONTROL_ID]
    b1_overall = aggregates[B1_OVERALL_CONTROL_ID]
    loss_delta = float(
        cast(float, selected["mean_log_loss"]) - cast(float, phase3a["mean_log_loss"])
    )
    promotion_checks = {
        "minimum_log_loss_improvement": loss_delta <= -CHAMPION_LOG_LOSS_IMPROVEMENT,
        "brier_not_meaningfully_worse": float(cast(float, selected["mean_brier_score"]))
        <= float(cast(float, phase3a["mean_brier_score"])) + MAX_BRIER_REGRESSION,
        "roc_auc_not_meaningfully_worse": float(cast(float, selected["mean_roc_auc"]))
        >= float(cast(float, phase3a["mean_roc_auc"])) - MAX_ROC_AUC_REGRESSION,
        "worst_fold_not_meaningfully_worse": float(cast(float, selected["worst_fold_log_loss"]))
        <= float(cast(float, phase3a["worst_fold_log_loss"])) + MAX_WORST_LOG_LOSS_REGRESSION,
        "calibration_not_meaningfully_worse": float(cast(float, selected["mean_ece"]))
        <= float(cast(float, phase3a["mean_ece"])) + MAX_ECE_REGRESSION,
        "exact_symmetry": float(cast(float, selected["mean_symmetric_complement_error"]))
        <= MAX_SYMMETRY_ERROR,
        "improves_at_least_two_folds": improvement_counts[selected_id] >= 2,
    }
    promoted = all(promotion_checks.values())
    return {
        "selection_scope": "development_rolling_validation_only",
        "selected_leader": selected_id,
        "phase3a_control": {"candidate_id": PHASE3A_CONTROL_ID, "aggregate": phase3a},
        "phase3b1_overall_elo_control": {
            "candidate_id": B1_OVERALL_CONTROL_ID,
            "aggregate": b1_overall,
        },
        "leader_aggregate": selected,
        "mean_log_loss_delta_vs_phase3a": loss_delta,
        "mean_log_loss_delta_vs_phase3b1_overall": float(
            cast(float, selected["mean_log_loss"]) - cast(float, b1_overall["mean_log_loss"])
        ),
        "improvement_fold_counts_vs_phase3a": dict(improvement_counts),
        "champion_threshold": CHAMPION_LOG_LOSS_IMPROVEMENT,
        "promotion_checks": promotion_checks,
        "champion_promoted": promoted,
        "result": "promoted" if promoted else "non_promoted_retain_accepted_incumbent",
    }


def run_m4_opponent_ablation_training(
    *,
    m3_root: Path = Path("data/processed/m3-v6"),
    phase1_root: Path = Path("data/processed/m4-baselines"),
    phase2_root: Path = Path("data/processed/m4-phase2-symmetry"),
    phase3a_root: Path = Path("data/processed/m4-phase3a-xgboost"),
    phase3b1_root: Path = Path("data/processed/m4-phase3b1-opponent-strength"),
    output_root: Path = Path("data/processed/m4-phase3b2-opponent-ablation"),
) -> dict[str, object]:
    """Run the prescribed B2 group ablation and inspect its leader once."""

    np.random.seed(RANDOM_SEED)
    accepted = load_accepted_m3_data(m3_root)
    protected_dirs = {
        "phase1": phase1_root / accepted.generation_id,
        "phase2": phase2_root / accepted.generation_id,
        "phase3a": phase3a_root / accepted.generation_id,
        "phase3b1": phase3b1_root / accepted.generation_id,
    }
    if any(not path.is_dir() for path in protected_dirs.values()):
        raise FileNotFoundError("accepted M4 control artifacts are missing")
    protected_before = {name: _artifact_hashes(path) for name, path in protected_dirs.items()}
    phase3a_dir = protected_dirs["phase3a"]
    pairwise, b1_contract, b1_hashes = _verify_b1_inputs(
        b1_dir=protected_dirs["phase3b1"], base_features=accepted.feature_columns
    )
    base = pd.DataFrame(accepted.frame.to_dicts())
    base["fight_date"] = pd.to_datetime(base["fight_date"], errors="raise").dt.normalize()
    pairwise["fight_date"] = pd.to_datetime(pairwise["fight_date"], errors="raise").dt.normalize()
    data = base.merge(
        pairwise,
        on=["canonical_bout_id", "fight_date", "canonical_fighter_a_id", "canonical_fighter_b_id"],
        validate="one_to_one",
    )
    packs = feature_packs(accepted.feature_columns)
    split_frame = pl.read_parquet(phase3a_dir / "m4_phase3a_rolling_folds.parquet")
    phase3a_predictions = pl.read_parquet(phase3a_dir / "m4_phase3a_predictions.parquet")
    fold_members = {
        str(fold_id): {
            role: set(
                split_frame.filter((pl.col("fold_id") == fold_id) & (pl.col("role") == role))[
                    "canonical_bout_id"
                ].to_list()
            )
            for role in ("train", "validation")
        }
        for fold_id in sorted(split_frame["fold_id"].unique().to_list())
    }
    benchmark_keys = set(
        phase3a_predictions.filter(pl.col("evaluation_partition") == "locked_benchmark")[
            "canonical_bout_id"
        ].to_list()
    )
    development_keys = set().union(
        *(roles["train"] | roles["validation"] for roles in fold_members.values())
    )
    if (
        len(fold_members) != 3
        or len(benchmark_keys) != 1337
        or len(development_keys) != 7575
        or development_keys & benchmark_keys
        or any(roles["train"] & roles["validation"] for roles in fold_members.values())
    ):
        raise ValueError("accepted Phase 3A split contract changed")
    keyed = data.set_index("canonical_bout_id", drop=False)
    if set(keyed.index) != development_keys | benchmark_keys:
        raise ValueError("Phase 3B2 rows do not exactly match accepted Phase 3A keys")

    rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, object]] = []
    definitions: dict[str, tuple[int, int]] = {}
    for pack in packs:
        for model_name, model_rank in (("symmetrized_logistic", 0), ("phase3a_shallow_xgboost", 1)):
            candidate_id = f"{pack.pack_id}__{model_name}"
            definitions[candidate_id] = (pack.added_feature_count, model_rank)
            for fold_id, members in fold_members.items():
                train = keyed.loc[sorted(members["train"])].reset_index(drop=True)
                validation = keyed.loc[sorted(members["validation"])].reset_index(drop=True)
                train_y = train[accepted.target_column].astype(int).to_numpy()
                validation_y = validation[accepted.target_column].astype(int).to_numpy()
                if model_name == "symmetrized_logistic":
                    model: BaseEstimator = build_logistic_pipeline().fit(
                        _matrix(train, pack.feature_columns), train_y
                    )
                    best_iteration = 0
                else:
                    fitting = _augment(
                        train, features=pack.feature_columns, target=accepted.target_column
                    )
                    model = _build_xgboost(rounds=MAX_BOOSTING_ROUNDS)
                    cast(Any, model).fit(
                        _matrix(fitting, pack.feature_columns),
                        fitting[accepted.target_column].astype(int).to_numpy(),
                        eval_set=[(_matrix(validation, pack.feature_columns), validation_y)],
                        verbose=False,
                    )
                    best_iteration = _best_iteration(cast(xgb.XGBClassifier, model))
                forward, swapped, symmetric = _predict_triplet(
                    model, validation, pack.feature_columns, accepted.target_column
                )
                row = {
                    "candidate_id": candidate_id,
                    "feature_pack": pack.pack_id,
                    "model": model_name,
                    "fold_id": fold_id,
                    "metrics": _metrics(validation_y, symmetric),
                    "calibration": calibration_summary(validation_y, symmetric),
                    "audit": _audit(forward, swapped),
                    "best_iteration_count": best_iteration,
                    "train_rows": len(train),
                    "validation_rows": len(validation),
                    "feature_count": len(pack.feature_columns),
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
                            "canonical_bout_id": source["canonical_bout_id"],
                            "fight_date": source["fight_date"],
                            "evaluation_partition": "rolling_validation",
                            "fold_id": fold_id,
                            "candidate_id": candidate_id,
                            "target_fighter_a_won": int(source[accepted.target_column]),
                            "forward_probability": float(p_forward),
                            "swapped_probability": float(p_swapped),
                            "symmetric_probability": float(p_symmetric),
                            "predicted_class": int(p_symmetric >= 0.5),
                            "raw_complement_error": float(abs(p_forward - (1.0 - p_swapped))),
                        }
                    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["candidate_id"])].append(row)
    aggregates = {candidate_id: _summary(value) for candidate_id, value in grouped.items()}
    selected_id, improvement_counts = _select(
        aggregates=aggregates, rows=rows, definitions=definitions
    )
    comparison = _comparison(
        selected_id=selected_id, aggregates=aggregates, improvement_counts=improvement_counts
    )
    selected_pack_id, selected_model_name = selected_id.split("__", 1)
    selected_pack = next(pack for pack in packs if pack.pack_id == selected_pack_id)
    development = keyed.loc[sorted(development_keys)].reset_index(drop=True)
    benchmark = keyed.loc[sorted(benchmark_keys)].reset_index(drop=True)
    development_y = development[accepted.target_column].astype(int).to_numpy()
    if selected_model_name == "symmetrized_logistic":
        selected_model: BaseEstimator = build_logistic_pipeline().fit(
            _matrix(development, selected_pack.feature_columns), development_y
        )
        final_rounds = 0
        round_policy = "not_applicable_logistic"
    else:
        final_rounds = int(
            median(cast(list[int], aggregates[selected_id]["best_iteration_counts"]))
        )
        selected_model = _build_xgboost(rounds=final_rounds)
        fitting = _augment(
            development, features=selected_pack.feature_columns, target=accepted.target_column
        )
        cast(Any, selected_model).fit(
            _matrix(fitting, selected_pack.feature_columns),
            fitting[accepted.target_column].astype(int).to_numpy(),
            verbose=False,
        )
        round_policy = "median of development-only rolling-fold early-stopping iterations"
    benchmark_y = benchmark[accepted.target_column].astype(int).to_numpy()
    forward, swapped, symmetric = _predict_triplet(
        selected_model, benchmark, selected_pack.feature_columns, accepted.target_column
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
                "canonical_bout_id": source["canonical_bout_id"],
                "fight_date": source["fight_date"],
                "evaluation_partition": "inspected_locked_benchmark",
                "fold_id": None,
                "candidate_id": selected_id,
                "target_fighter_a_won": int(source[accepted.target_column]),
                "forward_probability": float(p_forward),
                "swapped_probability": float(p_swapped),
                "symmetric_probability": float(p_symmetric),
                "predicted_class": int(p_symmetric >= 0.5),
                "raw_complement_error": float(abs(p_forward - (1.0 - p_swapped))),
            }
        )

    run_dir = output_root / accepted.generation_id
    run_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "feature_groups": run_dir / "m4_phase3b2_feature_groups.json",
        "feature_packs": run_dir / "m4_phase3b2_feature_packs.json",
        "fold_candidate_results": run_dir / "m4_phase3b2_rolling_candidate_results.parquet",
        "predictions": run_dir / "m4_phase3b2_predictions.parquet",
        "metrics": run_dir / "m4_phase3b2_metrics.json",
        "model_comparison": run_dir / "m4_phase3b2_model_comparison.json",
        "feature_contract": run_dir / "m4_phase3b2_feature_contract.json",
        "selected_model": run_dir / "m4_phase3b2_selected_model.joblib",
    }
    groups = feature_groups()
    _write_json(
        paths["feature_groups"],
        _to_builtin({"schema_version": M4_PHASE3B2_SCHEMA_VERSION, "groups": groups}),
    )
    _write_json(
        paths["feature_packs"],
        _to_builtin(
            {
                "schema_version": M4_PHASE3B2_SCHEMA_VERSION,
                "packs": [
                    {
                        "pack_id": pack.pack_id,
                        "feature_count": len(pack.feature_columns),
                        "feature_columns": pack.feature_columns,
                    }
                    for pack in packs
                ],
            }
        ),
    )
    results = pl.DataFrame(
        [
            {
                "candidate_id": row["candidate_id"],
                "feature_pack": row["feature_pack"],
                "model": row["model"],
                "fold_id": row["fold_id"],
                "feature_count": row["feature_count"],
                "best_iteration_count": row["best_iteration_count"],
                "validation_log_loss": row["metrics"]["log_loss"],
                "validation_brier_score": row["metrics"]["brier_score"],
                "validation_roc_auc": row["metrics"]["roc_auc"],
                "validation_ece": row["calibration"]["expected_calibration_error"],
                "symmetric_maximum_complement_error": row["audit"]["symmetrized"][
                    "maximum_absolute_complement_error"
                ],
            }
            for row in rows
        ]
    ).sort(["candidate_id", "fold_id"])
    predictions = pl.DataFrame(pd.DataFrame(prediction_rows).to_dict(orient="list")).sort(
        ["evaluation_partition", "candidate_id", "fold_id", "canonical_bout_id"], nulls_last=True
    )
    results.write_parquet(paths["fold_candidate_results"], compression="zstd")
    predictions.write_parquet(paths["predictions"], compression="zstd")
    joblib.dump(selected_model, paths["selected_model"], compress=3)
    contract = {
        "schema_version": M4_PHASE3B2_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "accepted_m3_final_acceptance_report_sha256": ACCEPTED_M3_ACCEPTANCE_SHA256,
        "phase3b1_input_hashes": b1_hashes,
        "phase3b1_rating_policy_id": b1_contract["rating_policy_id"],
        "feature_groups": groups,
        "feature_packs": {pack.pack_id: pack.feature_columns for pack in packs},
        "phase3a_split_identity_verified": True,
        "benchmark_selection_policy": (
            "benchmark excluded from candidate selection and early stopping"
        ),
        "swap_contract": (
            "exchange all a/b values; negate diffs; complement Elo probability and target"
        ),
    }
    metrics = {
        "schema_version": M4_PHASE3B2_SCHEMA_VERSION,
        "candidate_aggregates": aggregates,
        "fold_results": rows,
        "selection": {
            "selected_leader": selected_id,
            "selected_feature_pack": selected_pack_id,
            "selected_model": selected_model_name,
            "selection_scope": "development_period_rolling_validation_only",
            "benchmark_excluded": True,
            "priority": [
                "mean_log_loss",
                "brier_score",
                "roc_auc",
                "log_loss_standard_deviation",
                "worst_fold_log_loss",
                "improvement_on_at_least_two_folds",
                "fewer_features",
                "simpler_model",
            ],
            "final_boosting_rounds": final_rounds,
            "final_boosting_round_policy": round_policy,
        },
        "inspected_locked_benchmark": benchmark_report,
    }
    _write_json(paths["metrics"], _to_builtin(metrics))
    _write_json(
        paths["model_comparison"],
        _to_builtin(
            {
                "schema_version": M4_PHASE3B2_SCHEMA_VERSION,
                **comparison,
                "inspected_benchmark": benchmark_report,
            }
        ),
    )
    _write_json(paths["feature_contract"], _to_builtin(contract))
    protected_after = {name: _artifact_hashes(path) for name, path in protected_dirs.items()}
    if protected_before != protected_after:
        raise ValueError("Phase 3B2 changed protected accepted artifacts")
    manifest_path = run_dir / "m4_phase3b2_training_manifest.json"
    manifest = {
        "schema_version": M4_PHASE3B2_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "input_hashes": {
            "m3_model_ready_binary.parquet": accepted.artifact_sha256,
            "phase3a_rolling_folds.parquet": _sha256_path(
                phase3a_dir / "m4_phase3a_rolling_folds.parquet"
            ),
            "phase3a_predictions.parquet": _sha256_path(
                phase3a_dir / "m4_phase3a_predictions.parquet"
            ),
            **b1_hashes,
        },
        "artifact_shapes": {
            "fold_candidate_results": {"rows": results.height, "columns": results.width},
            "predictions": {"rows": predictions.height, "columns": predictions.width},
        },
        "input_counts": {"model_ready_bouts": len(base), "pairwise_rows": len(pairwise)},
        "null_counts": {name: int(pairwise[name].isna().sum()) for name in pairwise.columns},
        "date_range": {
            "start": str(pairwise["fight_date"].min()),
            "end": str(pairwise["fight_date"].max()),
        },
        "protected_artifacts_sha256": protected_before,
        "selection": metrics["selection"],
        "champion_result": comparison,
        "output_paths": {name: str(path) for name, path in paths.items()},
        "output_checksums": {name: _sha256_path(path) for name, path in paths.items()},
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "xgboost": xgb.__version__,
            "random_seed": RANDOM_SEED,
            "n_jobs": 1,
            "early_stopping_rounds": EARLY_STOPPING_ROUNDS,
            "max_boosting_rounds": MAX_BOOSTING_ROUNDS,
            "xgboost_parameters": PHASE3A_XGBOOST_PARAMETERS,
        },
    }
    _write_json(manifest_path, _to_builtin(manifest))
    return {
        "run_directory": str(run_dir),
        "selected_leader": selected_id,
        "champion_promoted": comparison["champion_promoted"],
        "training_manifest_path": str(manifest_path),
        "training_manifest_sha256": _sha256_path(manifest_path),
    }
