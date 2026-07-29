"""M4 Phase 3C leakage-safe opponent-adjusted performance evaluation."""

from __future__ import annotations

import gc
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
    PHASE3A_XGBOOST_PARAMETERS,
    _artifact_hashes,
    _audit,
    _augment,
    _best_iteration,
    _build_xgboost,
    _matrix,
    _predict_triplet,
)
from ufc_predictor.training.m4_xgboost import EARLY_STOPPING_ROUNDS, MAX_BOOSTING_ROUNDS

M4_PHASE3C_SCHEMA_VERSION = "m4.phase3c.opponent_adjusted_performance.v1"
OPPONENT_BASELINE_POLICY_ID = "m4.phase3c.strict_prior_date.opponent_offense_defense.v1"
PHASE3A_CONTROL_ID = "base_plus_overall_elo__phase3a_shallow_xgboost"
CHAMPION_LOG_LOSS_IMPROVEMENT = 0.002
MAX_BRIER_REGRESSION = 0.001
MAX_ROC_AUC_REGRESSION = 0.005
MAX_WORST_LOG_LOSS_REGRESSION = 0.002
MAX_SYMMETRY_ERROR = 1e-6

# Hash-lock the accepted Phase 3B1 Elo material.  These are deliberately
# local constants rather than a dependence on a later ablation artifact.
B1_SNAPSHOTS_SHA256 = "308f47ad49c9583fea8d2de72feed8721192517721ace6cf6b1d94a2e0bb2dcd"
B1_PAIRWISE_SHA256 = "08e283638d95c1d4150fe7c28ce91b54d8214671be336aa4ba886f2c5aaa75fc"
B1_CONTRACT_SHA256 = "c3226d6a43797e0568cb3991db961db9e4568724a74df3e3db2a63981382e076"
PHASE3A_FOLDS_SHA256 = "527d0fda5fb6c1ebcae2dad4e7af30586e430b96caf67582387c959557314e2f"
PHASE3A_PREDICTIONS_SHA256 = "c3f5dcdead0458f7d2379be837823fe7a08ae3545a9c99f57ee14b9048dc492d"

PERFORMANCE_METRICS = (
    "significant_strikes_landed",
    "total_strikes_landed",
    "takedowns_landed",
    "control_seconds",
)
WINDOWS = ("career", "recent_3", "recent_5")


@dataclass(frozen=True, slots=True)
class FeaturePack:
    """One fixed and preregistered Phase 3C pack."""

    pack_id: str
    feature_columns: tuple[str, ...]
    added_feature_count: int
    complexity_rank: int


def _oriented(features: Iterable[str]) -> tuple[str, ...]:
    return tuple(f"{side}{feature}" for feature in features for side in ("a_", "b_")) + tuple(
        f"diff_{feature}" for feature in features
    )


def adjusted_feature_names() -> tuple[str, ...]:
    """Return the only un-oriented Phase 3C feature names allowed."""

    names = [
        f"opponent_adjusted_{metric}_{window}_mean"
        for metric in PERFORMANCE_METRICS
        for window in WINDOWS
    ]
    names.extend(f"opponent_adjusted_{metric}_observation_count" for metric in PERFORMANCE_METRICS)
    return tuple(names)


def feature_packs(
    base_features: tuple[str, ...], overall_features: tuple[str, ...]
) -> tuple[FeaturePack, ...]:
    """Build exactly the four requested control/additive performance packs."""

    career = tuple(
        name
        for name in adjusted_feature_names()
        if name.endswith("_career_mean") or name.endswith("_observation_count")
    )
    recent = tuple(
        name
        for name in adjusted_feature_names()
        if name.endswith("_recent_3_mean") or name.endswith("_recent_5_mean")
    )
    all_adjusted = adjusted_feature_names()
    definitions = (
        ("base_plus_overall_elo", ()),
        ("overall_elo_plus_career_adjusted", _oriented(career)),
        ("overall_elo_plus_recent_adjusted", _oriented(recent)),
        ("overall_elo_plus_all_adjusted", _oriented(all_adjusted)),
    )
    return tuple(
        FeaturePack(pack_id, (*base_features, *overall_features, *added), len(added), rank)
        for rank, (pack_id, added) in enumerate(definitions)
    )


def _accepted_m3_hashes(generation_path: Path) -> dict[str, str]:
    """Verify all M3 artifacts consumed by 3C against final acceptance."""

    acceptance = json.loads((generation_path / "m3_final_acceptance_report.json").read_text())
    inventory = cast(dict[str, dict[str, object]], acceptance["artifact_inventory"])
    names = (
        "m3_fighter_bout_performance.parquet",
        "m3_prefight_performance_history.parquet",
        "m3_canonical_historical_bouts.parquet",
        "m3_model_ready_binary.parquet",
    )
    hashes = {name: _sha256_path(generation_path / name) for name in names}
    if any(hashes[name] != inventory[name]["sha256"] for name in names):
        raise ValueError("accepted M3 performance input hash changed")
    return hashes


def _verify_b1_elo_inputs(
    b1_dir: Path, base_features: tuple[str, ...]
) -> tuple[pd.DataFrame, tuple[str, ...], dict[str, str]]:
    """Hash-lock the Phase 3B1 snapshots and recover the exact overall control."""

    paths = {
        "fighter_rating_snapshots": b1_dir / "m4_phase3b1_fighter_rating_snapshots.parquet",
        "pairwise_opponent_strength": b1_dir / "m4_phase3b1_pairwise_opponent_strength.parquet",
        "feature_contract": b1_dir / "m4_phase3b1_feature_contract.json",
        "feature_packs": b1_dir / "m4_phase3b1_feature_packs.json",
    }
    hashes = {name: _sha256_path(path) for name, path in paths.items()}
    required = {
        "fighter_rating_snapshots": B1_SNAPSHOTS_SHA256,
        "pairwise_opponent_strength": B1_PAIRWISE_SHA256,
        "feature_contract": B1_CONTRACT_SHA256,
    }
    if any(hashes[name] != expected for name, expected in required.items()):
        raise ValueError("accepted Phase 3B1 input hash changed")
    packs = cast(dict[str, object], json.loads(paths["feature_packs"].read_text()))
    definitions = cast(list[dict[str, object]], packs["packs"])
    control = next(item for item in definitions if item["pack_id"] == "base_plus_overall_elo")
    columns = tuple(cast(list[str], control["feature_columns"]))
    if columns[: len(base_features)] != base_features:
        raise ValueError("Phase 3B1 overall-Elo control no longer has the accepted base")
    pairwise = pd.DataFrame(pl.read_parquet(paths["pairwise_opponent_strength"]).to_dicts())
    if not set(columns[len(base_features) :]).issubset(pairwise.columns):
        raise ValueError("Phase 3B1 pairwise Elo control is incomplete")
    return pairwise, columns[len(base_features) :], hashes


def build_opponent_adjusted_snapshots(
    performance: pd.DataFrame, pre_fight_history: pd.DataFrame
) -> pd.DataFrame:
    """Snapshot adjusted histories before each date, then batch-append that date.

    For one observed bout metric, the opponent baseline is its strictly
    pre-fight defensive mean (allowed metric) minus offensive mean (landed
    metric).  The adjusted observation is the fighter's bout differential
    minus that baseline.  A missing half of a baseline makes the observation
    unavailable; it is never imputed as zero.
    """

    required_performance = {
        "canonical_bout_id",
        "canonical_fighter_id",
        "opponent_canonical_fighter_id",
        "fight_date",
        *(metric for metric in PERFORMANCE_METRICS),
        *(f"{metric}_available" for metric in PERFORMANCE_METRICS),
    }
    if missing := required_performance - set(performance.columns):
        raise ValueError(f"performance artifact misses columns: {sorted(missing)}")
    required_history = {
        "canonical_bout_id",
        "canonical_fighter_id",
        "target_fight_date",
        *(f"career_{metric}_mean" for metric in PERFORMANCE_METRICS),
        *(f"career_{metric}_absorbed_per_observed_bout" for metric in PERFORMANCE_METRICS),
    }
    if missing := required_history - set(pre_fight_history.columns):
        raise ValueError(f"pre-fight performance artifact misses columns: {sorted(missing)}")
    rows = performance.copy(deep=True)
    rows["fight_date"] = pd.to_datetime(rows["fight_date"], errors="raise").dt.normalize()
    opponent_values = rows[
        ["canonical_bout_id", "canonical_fighter_id", *PERFORMANCE_METRICS]
    ].copy()
    opponent_values = opponent_values.rename(
        columns={
            "canonical_fighter_id": "opponent_canonical_fighter_id",
            **{metric: f"opponent_{metric}" for metric in PERFORMANCE_METRICS},
        }
    )
    rows = rows.merge(
        opponent_values,
        on=["canonical_bout_id", "opponent_canonical_fighter_id"],
        validate="one_to_one",
    )
    history_columns = ["canonical_bout_id", "canonical_fighter_id"]
    for metric in PERFORMANCE_METRICS:
        history_columns.extend(
            [f"career_{metric}_mean", f"career_{metric}_absorbed_per_observed_bout"]
        )
    baseline = pre_fight_history.loc[:, history_columns].rename(
        columns={"canonical_fighter_id": "opponent_canonical_fighter_id"}
    )
    baseline = baseline.rename(
        columns={column: f"opponent_{column}" for column in history_columns[2:]}
    )
    rows = rows.merge(
        baseline, on=["canonical_bout_id", "opponent_canonical_fighter_id"], validate="one_to_one"
    )
    rows = rows.sort_values(
        ["fight_date", "canonical_bout_id", "canonical_fighter_id"], kind="stable"
    )
    histories: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    snapshots: list[dict[str, object]] = []

    def snapshot(fighter: str, bout_id: str, date: pd.Timestamp) -> dict[str, object]:
        result: dict[str, object] = {
            "canonical_bout_id": bout_id,
            "fight_date": date,
            "canonical_fighter_id": fighter,
        }
        for metric in PERFORMANCE_METRICS:
            values = histories[fighter][metric]
            result[f"opponent_adjusted_{metric}_observation_count"] = float(len(values))
            for window in WINDOWS:
                selected = (
                    values if window == "career" else values[-int(window.rsplit("_", 1)[1]) :]
                )
                result[f"opponent_adjusted_{metric}_{window}_mean"] = (
                    float(np.mean(selected)) if selected else np.nan
                )
        return result

    for date, date_rows in rows.groupby("fight_date", sort=True):
        records = date_rows.to_dict(orient="records")
        for row in records:
            snapshots.append(
                snapshot(
                    str(row["canonical_fighter_id"]),
                    str(row["canonical_bout_id"]),
                    pd.Timestamp(date),
                )
            )
        # Only now append all outcomes from the date.  This makes same-date
        # snapshots independent of row ordering and prevents contemporaneous leakage.
        for row in records:
            fighter = str(row["canonical_fighter_id"])
            for metric in PERFORMANCE_METRICS:
                own, opponent = row[metric], row[f"opponent_{metric}"]
                offense = row[f"opponent_career_{metric}_mean"]
                defense = row[f"opponent_career_{metric}_absorbed_per_observed_bout"]
                if (
                    bool(row[f"{metric}_available"])
                    and pd.notna(own)
                    and pd.notna(opponent)
                    and pd.notna(offense)
                    and pd.notna(defense)
                ):
                    actual_differential = float(own) - float(opponent)
                    opponent_baseline = float(defense) - float(offense)
                    histories[fighter][metric].append(actual_differential - opponent_baseline)
    output = pd.DataFrame(snapshots).sort_values(
        ["canonical_bout_id", "canonical_fighter_id"], kind="stable"
    )
    if output.duplicated(["canonical_bout_id", "canonical_fighter_id"]).any():
        raise ValueError("opponent-adjusted snapshot keys are not unique")
    return output.reset_index(drop=True)


def build_pairwise_opponent_adjusted(
    snapshots: pd.DataFrame, model_ready: pd.DataFrame
) -> pd.DataFrame:
    """Orient date-safe fighter snapshots to the accepted M3 A/B contract."""

    features = adjusted_feature_names()
    index = snapshots.set_index(["canonical_bout_id", "canonical_fighter_id"])
    rows: list[dict[str, object]] = []
    for bout in model_ready.sort_values("canonical_bout_id", kind="stable").to_dict(
        orient="records"
    ):
        bout_id, fighter_a, fighter_b = (
            str(bout[key])
            for key in ("canonical_bout_id", "canonical_fighter_a_id", "canonical_fighter_b_id")
        )
        a, b = index.loc[(bout_id, fighter_a)], index.loc[(bout_id, fighter_b)]
        row: dict[str, object] = {
            "canonical_bout_id": bout_id,
            "fight_date": pd.Timestamp(cast(Any, bout["fight_date"])),
            "canonical_fighter_a_id": fighter_a,
            "canonical_fighter_b_id": fighter_b,
        }
        for feature in features:
            a_value, b_value = a[feature], b[feature]
            row[f"a_{feature}"] = a_value
            row[f"b_{feature}"] = b_value
            row[f"diff_{feature}"] = (
                float(a_value) - float(b_value)
                if pd.notna(a_value) and pd.notna(b_value)
                else np.nan
            )
        rows.append(row)
    output = pd.DataFrame(rows)
    if len(output) != len(model_ready) or output["canonical_bout_id"].duplicated().any():
        raise ValueError("opponent-adjusted pairwise keys do not match model-ready rows")
    return output


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
        "mean_symmetric_complement_error": float(
            np.mean(
                [row["audit"]["symmetrized"]["maximum_absolute_complement_error"] for row in rows]
            )
        ),
        "best_iteration_counts": [int(row["best_iteration_count"]) for row in rows],
    }


def _select(
    aggregates: Mapping[str, Mapping[str, object]],
    rows: Iterable[Mapping[str, Any]],
    definitions: Mapping[str, tuple[int, int]],
) -> tuple[str, dict[str, int]]:
    losses = {
        (str(row["candidate_id"]), str(row["fold_id"])): float(
            cast(Mapping[str, float], row["metrics"])["log_loss"]
        )
        for row in rows
    }
    folds = sorted(fold for candidate, fold in losses if candidate == PHASE3A_CONTROL_ID)
    improvements = {
        candidate: sum(
            losses[(candidate, fold)] < losses[(PHASE3A_CONTROL_ID, fold)] for fold in folds
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
            0 if improvements[candidate] >= 2 else 1,
            definitions[candidate][0],
            definitions[candidate][1],
            candidate,
        ),
    )
    return selected, improvements


def _comparison(
    selected_id: str,
    aggregates: Mapping[str, Mapping[str, object]],
    improvements: Mapping[str, int],
) -> dict[str, object]:
    selected, control = aggregates[selected_id], aggregates[PHASE3A_CONTROL_ID]
    delta = float(cast(float, selected["mean_log_loss"]) - cast(float, control["mean_log_loss"]))
    checks = {
        "minimum_log_loss_improvement": delta <= -CHAMPION_LOG_LOSS_IMPROVEMENT,
        "brier_not_meaningfully_worse": float(cast(float, selected["mean_brier_score"]))
        <= float(cast(float, control["mean_brier_score"])) + MAX_BRIER_REGRESSION,
        "roc_auc_not_meaningfully_worse": float(cast(float, selected["mean_roc_auc"]))
        >= float(cast(float, control["mean_roc_auc"])) - MAX_ROC_AUC_REGRESSION,
        "worst_fold_not_meaningfully_worse": float(cast(float, selected["worst_fold_log_loss"]))
        <= float(cast(float, control["worst_fold_log_loss"])) + MAX_WORST_LOG_LOSS_REGRESSION,
        "exact_symmetry": float(cast(float, selected["mean_symmetric_complement_error"]))
        <= MAX_SYMMETRY_ERROR,
        "improves_at_least_two_folds": improvements[selected_id] >= 2,
    }
    return {
        "selection_scope": "development_rolling_validation_only",
        "selected_leader": selected_id,
        "control": {"candidate_id": PHASE3A_CONTROL_ID, "aggregate": control},
        "leader_aggregate": selected,
        "mean_log_loss_delta_vs_control": delta,
        "improvement_fold_counts_vs_control": dict(improvements),
        "champion_threshold": CHAMPION_LOG_LOSS_IMPROVEMENT,
        "promotion_checks": checks,
        "champion_promoted": all(checks.values()),
        "result": "promoted" if all(checks.values()) else "non_promoted_retain_accepted_incumbent",
    }


def run_m4_opponent_adjusted_performance_training(
    *,
    m3_root: Path = Path("data/processed/m3-v6"),
    phase1_root: Path = Path("data/processed/m4-baselines"),
    phase2_root: Path = Path("data/processed/m4-phase2-symmetry"),
    phase3a_root: Path = Path("data/processed/m4-phase3a-xgboost"),
    phase3b1_root: Path = Path("data/processed/m4-phase3b1-opponent-strength"),
    output_root: Path = Path("data/processed/m4-phase3c-opponent-adjusted-performance"),
) -> dict[str, object]:
    """Run the fixed Phase 3C packs, selecting only on Phase 3A development folds."""

    np.random.seed(RANDOM_SEED)
    accepted = load_accepted_m3_data(m3_root)
    protected_dirs = {
        "phase1": phase1_root / accepted.generation_id,
        "phase2": phase2_root / accepted.generation_id,
        "phase3a": phase3a_root / accepted.generation_id,
        "phase3b1": phase3b1_root / accepted.generation_id,
    }
    if any(not directory.is_dir() for directory in protected_dirs.values()):
        raise FileNotFoundError("accepted M4 control artifacts are missing")
    protected_before = {
        name: _artifact_hashes(directory) for name, directory in protected_dirs.items()
    }
    m3_hashes = _accepted_m3_hashes(accepted.generation_path)
    elo_pairwise, overall_features, b1_hashes = _verify_b1_elo_inputs(
        protected_dirs["phase3b1"], accepted.feature_columns
    )
    performance = pd.DataFrame(
        pl.read_parquet(accepted.generation_path / "m3_fighter_bout_performance.parquet").to_dicts()
    )
    history = pd.DataFrame(
        pl.read_parquet(
            accepted.generation_path / "m3_prefight_performance_history.parquet"
        ).to_dicts()
    )
    snapshots = build_opponent_adjusted_snapshots(performance, history)
    base = pd.DataFrame(accepted.frame.to_dicts())
    base["fight_date"] = pd.to_datetime(base["fight_date"], errors="raise").dt.normalize()
    pairwise = build_pairwise_opponent_adjusted(snapshots, base)
    pairwise["fight_date"] = pd.to_datetime(pairwise["fight_date"], errors="raise").dt.normalize()
    elo_pairwise["fight_date"] = pd.to_datetime(
        elo_pairwise["fight_date"], errors="raise"
    ).dt.normalize()
    keys = ["canonical_bout_id", "fight_date", "canonical_fighter_a_id", "canonical_fighter_b_id"]
    data = base.merge(
        elo_pairwise.loc[:, [*keys, *overall_features]], on=keys, validate="one_to_one"
    ).merge(pairwise, on=keys, validate="one_to_one")
    packs = feature_packs(accepted.feature_columns, overall_features)
    phase3a_dir = protected_dirs["phase3a"]
    if (
        _sha256_path(phase3a_dir / "m4_phase3a_rolling_folds.parquet") != PHASE3A_FOLDS_SHA256
        or _sha256_path(phase3a_dir / "m4_phase3a_predictions.parquet")
        != PHASE3A_PREDICTIONS_SHA256
    ):
        raise ValueError("accepted Phase 3A fold or benchmark input hash changed")
    split_frame, phase3a_predictions = (
        pl.read_parquet(phase3a_dir / name)
        for name in ("m4_phase3a_rolling_folds.parquet", "m4_phase3a_predictions.parquet")
    )
    fold_members = {
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
    benchmark_keys = set(
        phase3a_predictions.filter(pl.col("evaluation_partition") == "locked_benchmark")[
            "canonical_bout_id"
        ].to_list()
    )
    development_keys = set().union(
        *(members["train"] | members["validation"] for members in fold_members.values())
    )
    if (
        len(fold_members) != 3
        or len(benchmark_keys) != 1337
        or len(development_keys) != 7575
        or development_keys & benchmark_keys
        or any(members["train"] & members["validation"] for members in fold_members.values())
    ):
        raise ValueError("accepted Phase 3A split contract changed")
    keyed = data.set_index("canonical_bout_id", drop=False)
    if set(keyed.index) != development_keys | benchmark_keys:
        raise ValueError("Phase 3C rows do not exactly match accepted Phase 3A keys")
    rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, object]] = []
    definitions: dict[str, tuple[int, int]] = {}
    for pack in packs:
        for model_name, model_rank in (("symmetrized_logistic", 0), ("phase3a_shallow_xgboost", 1)):
            candidate_id = f"{pack.pack_id}__{model_name}"
            definitions[candidate_id] = (pack.added_feature_count, model_rank)
            for fold_id, members in fold_members.items():
                train, validation = (
                    keyed.loc[sorted(members[role])].reset_index(drop=True)
                    for role in ("train", "validation")
                )
                train_y, validation_y = (
                    frame[accepted.target_column].astype(int).to_numpy()
                    for frame in (train, validation)
                )
                if model_name == "symmetrized_logistic":
                    model: BaseEstimator = build_logistic_pipeline().fit(
                        _matrix(train, pack.feature_columns), train_y
                    )
                    best_iteration = 0
                else:
                    model = _build_xgboost(rounds=MAX_BOOSTING_ROUNDS)
                    fitting = _augment(
                        train, features=pack.feature_columns, target=accepted.target_column
                    )
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
                rows.append(
                    {
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
                )
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
                # XGBoost owns native histogram buffers.  Release each
                # development model before the next fold so repeated fixed
                # candidate evaluation is stable on constrained runners.
                del model
                gc.collect()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["candidate_id"])].append(row)
    aggregates = {candidate: _summary(value) for candidate, value in grouped.items()}
    selected_id, improvements = _select(aggregates, rows, definitions)
    comparison = _comparison(selected_id, aggregates, improvements)
    selected_pack_id, selected_model_name = selected_id.split("__", 1)
    selected_pack = next(pack for pack in packs if pack.pack_id == selected_pack_id)
    development, benchmark = (
        keyed.loc[sorted(keys)].reset_index(drop=True)
        for keys in (development_keys, benchmark_keys)
    )
    development_y = development[accepted.target_column].astype(int).to_numpy()
    if selected_model_name == "symmetrized_logistic":
        selected_model: BaseEstimator = build_logistic_pipeline().fit(
            _matrix(development, selected_pack.feature_columns), development_y
        )
        final_rounds, round_policy = 0, "not_applicable_logistic"
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
        "fighter_snapshots": run_dir / "m4_phase3c_fighter_opponent_adjusted_snapshots.parquet",
        "pairwise_features": run_dir / "m4_phase3c_pairwise_opponent_adjusted_performance.parquet",
        "feature_packs": run_dir / "m4_phase3c_feature_packs.json",
        "fold_candidate_results": run_dir / "m4_phase3c_rolling_candidate_results.parquet",
        "predictions": run_dir / "m4_phase3c_predictions.parquet",
        "metrics": run_dir / "m4_phase3c_metrics.json",
        "model_comparison": run_dir / "m4_phase3c_model_comparison.json",
        "feature_contract": run_dir / "m4_phase3c_feature_contract.json",
        "selected_model": run_dir / "m4_phase3c_selected_model.joblib",
    }
    snapshots_frame = pl.DataFrame(snapshots).sort(["canonical_bout_id", "canonical_fighter_id"])
    pairwise_frame = pl.DataFrame(pairwise).sort("canonical_bout_id")
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
    snapshots_frame.write_parquet(paths["fighter_snapshots"], compression="zstd")
    pairwise_frame.write_parquet(paths["pairwise_features"], compression="zstd")
    results.write_parquet(paths["fold_candidate_results"], compression="zstd")
    predictions.write_parquet(paths["predictions"], compression="zstd")
    joblib.dump(selected_model, paths["selected_model"], compress=3)
    _write_json(
        paths["feature_packs"],
        _to_builtin(
            {
                "schema_version": M4_PHASE3C_SCHEMA_VERSION,
                "packs": [
                    {
                        "pack_id": pack.pack_id,
                        "feature_count": len(pack.feature_columns),
                        "added_feature_count": pack.added_feature_count,
                        "feature_columns": pack.feature_columns,
                    }
                    for pack in packs
                ],
            }
        ),
    )
    contract = {
        "schema_version": M4_PHASE3C_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "accepted_m3_final_acceptance_report_sha256": ACCEPTED_M3_ACCEPTANCE_SHA256,
        "opponent_baseline_policy_id": OPPONENT_BASELINE_POLICY_ID,
        "historical_cutoff": "fight_date < target_fight_date",
        "same_date_policy": (
            "snapshot all fighter histories; emit all features; "
            "append same-date observations afterward"
        ),
        "null_policy": (
            "unavailable offensive or defensive opponent baseline yields a null "
            "adjusted observation and is excluded from counts and means"
        ),
        "performance_metrics": PERFORMANCE_METRICS,
        "unoriented_adjusted_features": adjusted_feature_names(),
        "feature_packs": {pack.pack_id: pack.feature_columns for pack in packs},
        "phase3a_split_identity_verified": True,
        "benchmark_selection_policy": (
            "benchmark excluded from candidate selection and early stopping"
        ),
        "swap_contract": "exchange all a/b values; negate diffs; complement target",
    }
    metrics = {
        "schema_version": M4_PHASE3C_SCHEMA_VERSION,
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
                "schema_version": M4_PHASE3C_SCHEMA_VERSION,
                **comparison,
                "inspected_benchmark": benchmark_report,
            }
        ),
    )
    _write_json(paths["feature_contract"], _to_builtin(contract))
    protected_after = {
        name: _artifact_hashes(directory) for name, directory in protected_dirs.items()
    }
    if protected_before != protected_after:
        raise ValueError("Phase 3C changed protected accepted artifacts")
    manifest_path = run_dir / "m4_phase3c_training_manifest.json"
    manifest = {
        "schema_version": M4_PHASE3C_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "input_hashes": {
            **m3_hashes,
            **b1_hashes,
            "phase3a_rolling_folds.parquet": _sha256_path(
                phase3a_dir / "m4_phase3a_rolling_folds.parquet"
            ),
            "phase3a_predictions.parquet": _sha256_path(
                phase3a_dir / "m4_phase3a_predictions.parquet"
            ),
        },
        "input_counts": {
            "performance_observations": len(performance),
            "pre_fight_performance_rows": len(history),
            "model_ready_bouts": len(base),
            "fighter_snapshots": len(snapshots),
            "pairwise_rows": len(pairwise),
        },
        "artifact_shapes": {
            "fighter_snapshots": {"rows": snapshots_frame.height, "columns": snapshots_frame.width},
            "pairwise_features": {"rows": pairwise_frame.height, "columns": pairwise_frame.width},
            "fold_candidate_results": {"rows": results.height, "columns": results.width},
            "predictions": {"rows": predictions.height, "columns": predictions.width},
        },
        "null_counts": {
            name: int(pairwise_frame[name].null_count()) for name in pairwise_frame.columns
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
