"""M4 Phase 3B1 leakage-safe opponent-strength features and ablation training."""

from __future__ import annotations

import json
import math
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
from ufc_predictor.training.m4_symmetry import symmetric_probability
from ufc_predictor.training.m4_xgboost import EARLY_STOPPING_ROUNDS, MAX_BOOSTING_ROUNDS

M4_PHASE3B1_SCHEMA_VERSION = "m4.phase3b1.opponent_strength_ablation.v1"
RATING_POLICY_ID = "m4.phase3b1.prefight_elo.k24.same_date_batch.v1"
INITIAL_ELO = 1500.0
K_FACTOR = 24.0
PHASE3A_SELECTED_CANDIDATE = "depth2_high_regularization__swap_augmented"
PRACTICAL_LOG_LOSS_IMPROVEMENT = 0.002
PHASE3A_XGBOOST_PARAMETERS: dict[str, float | int] = {
    "max_depth": 2,
    "min_child_weight": 6,
    "learning_rate": 0.04,
    "subsample": 0.9,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.15,
    "reg_lambda": 7.0,
}

OVERALL_FEATURES = (
    "pre_fight_overall_elo",
    "pre_fight_peak_overall_elo",
    "pre_fight_overall_elo_change_last_3",
    "pre_fight_rated_bout_count",
)
WEIGHT_CLASS_FEATURES = (
    "pre_fight_weight_class_elo",
    "pre_fight_weight_class_rated_bout_count",
    "pre_fight_current_weight_class_first_bout",
)
STRENGTH_FEATURES = (
    "pre_fight_average_opponent_elo_career",
    "pre_fight_average_opponent_elo_last_3",
    "pre_fight_average_opponent_elo_last_5",
    "pre_fight_average_defeated_opponent_elo",
    "pre_fight_strongest_defeated_opponent_elo",
)


@dataclass(frozen=True, slots=True)
class FeaturePack:
    """One fixed, additive Phase 3B1 feature-pack definition."""

    pack_id: str
    feature_columns: tuple[str, ...]
    added_feature_count: int
    complexity_rank: int


def _elo_expected(rating_a: float, rating_b: float) -> float:
    return float(1.0 / (1.0 + math.pow(10.0, (rating_b - rating_a) / 400.0)))


def _score(row: Mapping[str, object], fighter: str) -> float | None:
    if bool(row["is_no_contest"]):
        return None
    if bool(row["is_draw"]):
        return 0.5
    return 1.0 if str(row["winner_canonical_fighter_id"]) == fighter else 0.0


def _normalize_division(value: object) -> str | None:
    """Map accepted-source division strings to a fixed weight-class taxonomy."""

    if value is None:
        return None
    text = str(value).casefold()
    for label in (
        "women's strawweight",
        "women's flyweight",
        "women's bantamweight",
        "women's featherweight",
        "light heavyweight",
        "heavyweight",
        "middleweight",
        "welterweight",
        "lightweight",
        "featherweight",
        "bantamweight",
        "flyweight",
        "catch weight",
    ):
        if label in text:
            return label.replace(" ", "_").replace("'", "")
    return None


def load_weight_classes_from_m3_provenance(
    generation_path: Path,
) -> tuple[dict[str, str | None], dict[str, str]]:
    """Recover a reviewed-bout division label from immutable M3 source provenance.

    The accepted historical output does not retain a division column.  This
    joins only its accepted source-row crosswalk to the two hash-recorded M3
    interim inputs; it never reads outcome fields from those inputs.
    """

    root = generation_path.parents[4]
    ultimate_path = (
        root
        / "data/interim/kaggle-ultimate-ufc-dataset/parquet"
        / "5e4a50fa71c71a460d37cc5aada9fbaa336cf89e3fc014d6ae777bfd754a70f5.parquet"
    )
    datalab_path = (
        root
        / "data/interim/ufc-datalab/parquet"
        / "918700f092c088a945de0369d81271006beb7a001a80f6f45572233b16f4bd23.parquet"
    )
    if not ultimate_path.is_file() or not datalab_path.is_file():
        raise FileNotFoundError("M3 provenance division inputs are unavailable")
    crosswalk = pl.read_parquet(generation_path / "m3_source_bout_crosswalk.parquet")
    ultimate = pl.read_parquet(ultimate_path).select("source_record_key", "weight_class")
    datalab = pl.read_parquet(datalab_path).select("source_record_key", "division_source_value")
    ultimate_by_row = {
        str(row["source_record_key"]).rsplit(":", 1)[-1]: _normalize_division(row["weight_class"])
        for row in ultimate.to_dicts()
    }
    datalab_by_row = {
        str(row["source_record_key"]).rsplit(":", 1)[-1]: _normalize_division(
            row["division_source_value"]
        )
        for row in datalab.to_dicts()
    }
    grouped: dict[str, dict[str, str | None]] = defaultdict(dict)
    for row in crosswalk.select("canonical_bout_id", "source_name", "source_row_id").to_dicts():
        source = str(row["source_name"])
        source_row = str(row["source_row_id"])
        mapping = ultimate_by_row if source == "ultimate" else datalab_by_row
        grouped[str(row["canonical_bout_id"])][source] = mapping.get(source_row)
    divisions: dict[str, str | None] = {}
    for bout_id, values in grouped.items():
        # Ultimate labels are already a compact source taxonomy; the DataLab
        # value is used only when Ultimate is absent or unclassified.
        divisions[bout_id] = values.get("ultimate") or values.get("ufc-datalab")
    hashes = {
        "m3_source_bout_crosswalk.parquet": _sha256_path(
            generation_path / "m3_source_bout_crosswalk.parquet"
        ),
        "ultimate_division_input": _sha256_path(ultimate_path),
        "ufc_datalab_division_input": _sha256_path(datalab_path),
    }
    return divisions, hashes


def build_prefight_opponent_strength(
    historical: pd.DataFrame,
    *,
    weight_classes: Mapping[str, str | None],
) -> pd.DataFrame:
    """Build fighter snapshots with strict date-before-target semantics.

    Every bout on a date receives ratings and opponent aggregates before any
    outcomes from that date affect a rating.  Batch deltas make results
    invariant to source/Parquet row ordering within a date.
    """

    required = {
        "canonical_bout_id",
        "fight_date",
        "canonical_fighter_a_id",
        "canonical_fighter_b_id",
        "winner_canonical_fighter_id",
        "is_no_contest",
        "is_draw",
    }
    if missing := required - set(historical.columns):
        raise ValueError(f"historical bouts lack required columns: {sorted(missing)}")
    rows = historical.copy(deep=True)
    rows["fight_date"] = pd.to_datetime(rows["fight_date"], errors="raise").dt.normalize()
    rows["weight_class"] = rows["canonical_bout_id"].map(weight_classes)
    rows = rows.sort_values(["fight_date", "canonical_bout_id"], kind="stable")
    overall: dict[str, float] = defaultdict(lambda: INITIAL_ELO)
    peak: dict[str, float] = defaultdict(lambda: INITIAL_ELO)
    rated_count: dict[str, int] = defaultdict(int)
    rating_history: dict[str, list[float]] = defaultdict(list)
    class_rating: dict[tuple[str, str], float] = defaultdict(lambda: INITIAL_ELO)
    class_count: dict[tuple[str, str], int] = defaultdict(int)
    opponents: dict[str, list[float]] = defaultdict(list)
    defeated: dict[str, list[float]] = defaultdict(list)
    snapshots: list[dict[str, object]] = []

    def fighter_snapshot(
        fighter: str, opponent: str, bout: Mapping[str, object], division: str | None
    ) -> dict[str, object]:
        current = float(overall[fighter])
        history = rating_history[fighter]
        key = (fighter, division) if division is not None else None
        prior_opponents = opponents[fighter]
        prior_defeated = defeated[fighter]
        return {
            "canonical_bout_id": str(bout["canonical_bout_id"]),
            "fight_date": pd.Timestamp(cast(Any, bout["fight_date"])),
            "canonical_fighter_id": fighter,
            "opponent_canonical_fighter_id": opponent,
            "weight_class": division,
            "pre_fight_overall_elo": current,
            "pre_fight_peak_overall_elo": float(peak[fighter]),
            "pre_fight_overall_elo_change_last_3": (
                current - history[-3] if len(history) >= 3 else np.nan
            ),
            "pre_fight_rated_bout_count": float(rated_count[fighter]),
            "pre_fight_weight_class_elo": (float(class_rating[key]) if key is not None else np.nan),
            "pre_fight_weight_class_rated_bout_count": (
                float(class_count[key]) if key is not None else np.nan
            ),
            "pre_fight_current_weight_class_first_bout": (
                float(class_count[key] == 0) if key is not None else np.nan
            ),
            "pre_fight_average_opponent_elo_career": (
                float(np.mean(prior_opponents)) if prior_opponents else np.nan
            ),
            "pre_fight_average_opponent_elo_last_3": (
                float(np.mean(prior_opponents[-3:])) if prior_opponents else np.nan
            ),
            "pre_fight_average_opponent_elo_last_5": (
                float(np.mean(prior_opponents[-5:])) if prior_opponents else np.nan
            ),
            "pre_fight_average_defeated_opponent_elo": (
                float(np.mean(prior_defeated)) if prior_defeated else np.nan
            ),
            "pre_fight_strongest_defeated_opponent_elo": (
                float(max(prior_defeated)) if prior_defeated else np.nan
            ),
        }

    for _, date_rows in rows.groupby("fight_date", sort=True):
        date_records = date_rows.to_dict(orient="records")
        for bout in date_records:
            fighter_a = str(bout["canonical_fighter_a_id"])
            fighter_b = str(bout["canonical_fighter_b_id"])
            division = cast(str | None, bout["weight_class"])
            snapshots.append(fighter_snapshot(fighter_a, fighter_b, bout, division))
            snapshots.append(fighter_snapshot(fighter_b, fighter_a, bout, division))
        overall_delta: dict[str, float] = defaultdict(float)
        class_delta: dict[tuple[str, str], float] = defaultdict(float)
        # Keep the exact date-start opponent ratings alongside each result.
        # This is the value the strength-of-schedule features may consume;
        # neither the current bout nor a later bout can change it.
        rated_updates: list[tuple[str, str, str | None, float, float, float, float]] = []
        for bout in date_records:
            fighter_a = str(bout["canonical_fighter_a_id"])
            fighter_b = str(bout["canonical_fighter_b_id"])
            score_a = _score(bout, fighter_a)
            if score_a is None:
                continue
            score_b = 1.0 - score_a
            rating_a, rating_b = float(overall[fighter_a]), float(overall[fighter_b])
            overall_delta[fighter_a] += K_FACTOR * (score_a - _elo_expected(rating_a, rating_b))
            overall_delta[fighter_b] += K_FACTOR * (score_b - _elo_expected(rating_b, rating_a))
            division = cast(str | None, bout["weight_class"])
            if division is not None:
                key_a, key_b = (fighter_a, division), (fighter_b, division)
                class_a, class_b = float(class_rating[key_a]), float(class_rating[key_b])
                class_delta[key_a] += K_FACTOR * (score_a - _elo_expected(class_a, class_b))
                class_delta[key_b] += K_FACTOR * (score_b - _elo_expected(class_b, class_a))
            rated_updates.append(
                (fighter_a, fighter_b, division, score_a, score_b, rating_a, rating_b)
            )
        for fighter, delta in overall_delta.items():
            overall[fighter] += delta
            peak[fighter] = max(peak[fighter], overall[fighter])
        for key, delta in class_delta.items():
            class_rating[key] += delta
        for fighter_a, fighter_b, division, score_a, score_b, rating_a, rating_b in rated_updates:
            rating_history[fighter_a].append(float(overall[fighter_a]))
            rating_history[fighter_b].append(float(overall[fighter_b]))
            rated_count[fighter_a] += 1
            rated_count[fighter_b] += 1
            if division is not None:
                class_count[(fighter_a, division)] += 1
                class_count[(fighter_b, division)] += 1
            # These values were captured before any update from this date.
            opponents[fighter_a].append(rating_b)
            opponents[fighter_b].append(rating_a)
            if score_a == 1.0:
                defeated[fighter_a].append(rating_b)
            if score_b == 1.0:
                defeated[fighter_b].append(rating_a)
    result = pd.DataFrame(snapshots).sort_values(
        ["canonical_bout_id", "canonical_fighter_id"], kind="stable"
    )
    if result.duplicated(["canonical_bout_id", "canonical_fighter_id"]).any():
        raise ValueError("rating snapshot keys are not unique")
    return result.reset_index(drop=True)


def build_pairwise_opponent_strength(
    snapshots: pd.DataFrame, model_ready: pd.DataFrame
) -> pd.DataFrame:
    """Orient fighter snapshots to the immutable M3 A/B model-ready contract."""

    snapshot_columns = (*OVERALL_FEATURES, *WEIGHT_CLASS_FEATURES, *STRENGTH_FEATURES)
    index = snapshots.set_index(["canonical_bout_id", "canonical_fighter_id"])
    rows: list[dict[str, object]] = []
    for bout in model_ready.sort_values("canonical_bout_id", kind="stable").to_dict(
        orient="records"
    ):
        bout_id = str(bout["canonical_bout_id"])
        fighter_a = str(bout["canonical_fighter_a_id"])
        fighter_b = str(bout["canonical_fighter_b_id"])
        a = index.loc[(bout_id, fighter_a)]
        b = index.loc[(bout_id, fighter_b)]
        row: dict[str, object] = {
            "canonical_bout_id": bout_id,
            "fight_date": pd.Timestamp(cast(Any, bout["fight_date"])),
            "canonical_fighter_a_id": fighter_a,
            "canonical_fighter_b_id": fighter_b,
        }
        for feature in snapshot_columns:
            a_value, b_value = a[feature], b[feature]
            row[f"a_{feature}"] = a_value
            row[f"b_{feature}"] = b_value
            row[f"diff_{feature}"] = (
                float(a_value) - float(b_value)
                if pd.notna(a_value) and pd.notna(b_value)
                else np.nan
            )
        row["elo_expected_probability_a"] = _elo_expected(
            float(a["pre_fight_overall_elo"]), float(b["pre_fight_overall_elo"])
        )
        rows.append(row)
    result = pd.DataFrame(rows)
    if len(result) != len(model_ready) or result["canonical_bout_id"].duplicated().any():
        raise ValueError("pairwise opponent-strength keys do not match model-ready rows")
    return result


def feature_packs(base_features: tuple[str, ...]) -> tuple[FeaturePack, ...]:
    """Return the three required fixed feature packs, with no subset search."""

    def oriented(features: Iterable[str]) -> tuple[str, ...]:
        return tuple(
            f"{prefix}{feature}" for feature in features for prefix in ("a_", "b_")
        ) + tuple(f"diff_{feature}" for feature in features)

    overall = (*oriented(OVERALL_FEATURES), "elo_expected_probability_a")
    full = (*overall, *oriented(WEIGHT_CLASS_FEATURES), *oriented(STRENGTH_FEATURES))
    return (
        FeaturePack("base_130", base_features, 0, 0),
        FeaturePack("base_plus_overall_elo", (*base_features, *overall), len(overall), 1),
        FeaturePack("base_plus_opponent_strength", (*base_features, *full), len(full), 2),
    )


def swap_phase3b1_rows(
    frame: pd.DataFrame, *, feature_columns: Iterable[str], target_column: str
) -> pd.DataFrame:
    """Swap base and B1 pairwise features, including the Elo probability."""

    features = tuple(feature_columns)
    result = frame.copy(deep=True)
    feature_set = set(features)
    for feature in features:
        if feature.startswith("a_"):
            peer = f"b_{feature[2:]}"
            if peer not in feature_set:
                raise ValueError(f"swap contract has no B feature for {feature}")
            result[feature], result[peer] = frame[peer], frame[feature]
        elif feature.startswith("diff_"):
            result[feature] = -frame[feature]
        elif feature == "elo_expected_probability_a":
            result[feature] = 1.0 - frame[feature]
        elif not feature.startswith("b_"):
            raise ValueError(f"feature is outside the Phase 3B1 swap contract: {feature}")
    result[target_column] = 1 - frame[target_column].astype(int)
    if {"canonical_fighter_a_id", "canonical_fighter_b_id"}.issubset(frame.columns):
        result["canonical_fighter_a_id"], result["canonical_fighter_b_id"] = (
            frame["canonical_fighter_b_id"],
            frame["canonical_fighter_a_id"],
        )
    return result


def _augment(train: pd.DataFrame, *, features: tuple[str, ...], target: str) -> pd.DataFrame:
    canonical = train.copy(deep=True)
    swapped = swap_phase3b1_rows(train, feature_columns=features, target_column=target)
    result = pd.concat([canonical, swapped], ignore_index=True)
    if len(result) != 2 * len(train):
        raise ValueError("Phase 3B1 swap augmentation did not double training rows")
    return result


def _matrix(frame: pd.DataFrame, features: tuple[str, ...]) -> pd.DataFrame:
    return frame.loc[:, list(features)].astype(float).copy()


def _predict_triplet(
    model: BaseEstimator, frame: pd.DataFrame, features: tuple[str, ...], target: str
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    forward = cast(Any, model).predict_proba(_matrix(frame, features))[:, 1]
    swapped_frame = swap_phase3b1_rows(frame, feature_columns=features, target_column=target)
    swapped = cast(Any, model).predict_proba(_matrix(swapped_frame, features))[:, 1]
    return forward, swapped, symmetric_probability(forward, swapped)


def _audit(
    forward: np.ndarray[Any, Any], swapped: np.ndarray[Any, Any]
) -> dict[str, dict[str, float | int]]:
    symmetric = symmetric_probability(forward, swapped)
    errors = {
        "raw_forward": np.abs(forward - (1.0 - swapped)),
        "symmetrized": np.abs(symmetric - (1.0 - symmetric_probability(swapped, forward))),
    }
    return {
        name: {
            "mean_absolute_complement_error": float(error.mean()),
            "median_absolute_complement_error": float(np.median(error)),
            "maximum_absolute_complement_error": float(error.max()),
            "violations_above_1e-6": int((error > 1e-6).sum()),
            "violations_above_1e-3": int((error > 1e-3).sum()),
            "violations_above_1e-2": int((error > 1e-2).sum()),
        }
        for name, error in errors.items()
    }


def _build_xgboost(*, rounds: int) -> xgb.XGBClassifier:
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
        **PHASE3A_XGBOOST_PARAMETERS,
    )


def _best_iteration(model: xgb.XGBClassifier) -> int:
    value = getattr(model, "best_iteration", None)
    return int(value) + 1 if value is not None else MAX_BOOSTING_ROUNDS


def _summary(rows: list[dict[str, Any]]) -> dict[str, object]:
    metrics = [cast(dict[str, float], row["metrics"]) for row in rows]
    losses = [float(item["log_loss"]) for item in metrics]
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
    aggregates: Mapping[str, Mapping[str, object]], definitions: Mapping[str, tuple[int, int]]
) -> str:
    """Select strictly from rolling development metrics and fixed complexity rules."""

    return min(
        aggregates,
        key=lambda key: (
            float(cast(float, aggregates[key]["mean_log_loss"])),
            float(cast(float, aggregates[key]["mean_brier_score"])),
            -float(cast(float, aggregates[key]["mean_roc_auc"])),
            float(cast(float, aggregates[key]["std_log_loss"])),
            float(cast(float, aggregates[key]["worst_fold_log_loss"])),
            float(cast(float, aggregates[key]["mean_symmetric_complement_error"])),
            definitions[key][0],
            definitions[key][1],
            key,
        ),
    )


def _practical_improvement_report(
    *,
    selected_id: str,
    control_id: str,
    candidate_rows: Iterable[Mapping[str, Any]],
    aggregates: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Describe, but never use, a predeclared development-only effect threshold."""

    by_candidate_fold = {
        (str(row["candidate_id"]), str(row["fold_id"])): float(
            cast(Mapping[str, float], row["metrics"])["log_loss"]
        )
        for row in candidate_rows
    }
    selected_folds = sorted(
        fold_id for candidate_id, fold_id in by_candidate_fold if candidate_id == selected_id
    )
    fold_deltas = {
        fold_id: by_candidate_fold[(selected_id, fold_id)]
        - by_candidate_fold[(control_id, fold_id)]
        for fold_id in selected_folds
    }
    mean_delta = float(
        cast(float, aggregates[selected_id]["mean_log_loss"])
        - cast(float, aggregates[control_id]["mean_log_loss"])
    )
    all_folds_improve = all(delta < 0.0 for delta in fold_deltas.values())
    claimed = mean_delta <= -PRACTICAL_LOG_LOSS_IMPROVEMENT and all_folds_improve
    return {
        "scope": "development_rolling_validation_only",
        "control_candidate": control_id,
        "selected_candidate": selected_id,
        "mean_log_loss_delta_selected_minus_control": mean_delta,
        "per_fold_log_loss_deltas_selected_minus_control": fold_deltas,
        "predeclared_mean_log_loss_improvement_threshold": PRACTICAL_LOG_LOSS_IMPROVEMENT,
        "all_rolling_folds_improve": all_folds_improve,
        "practical_improvement_claimed": claimed,
        "interpretation": (
            "meaningful development-only improvement meets the predeclared mean-loss threshold "
            "and improves every rolling fold"
            if claimed
            else "no meaningful improvement is claimed; selection still follows the fixed rolling "
            "validation priority"
        ),
    }


def _artifact_hashes(directory: Path) -> dict[str, str]:
    return {path.name: _sha256_path(path) for path in sorted(directory.iterdir()) if path.is_file()}


def run_m4_opponent_strength_training(
    *,
    m3_root: Path = Path("data/processed/m3-v6"),
    phase1_root: Path = Path("data/processed/m4-baselines"),
    phase2_root: Path = Path("data/processed/m4-phase2-symmetry"),
    phase3a_root: Path = Path("data/processed/m4-phase3a-xgboost"),
    output_root: Path = Path("data/processed/m4-phase3b1-opponent-strength"),
) -> dict[str, object]:
    """Create additive B1 features, select on rolling folds, then inspect benchmark once."""

    np.random.seed(RANDOM_SEED)
    accepted = load_accepted_m3_data(m3_root)
    protected_dirs = {
        "phase1": phase1_root / accepted.generation_id,
        "phase2": phase2_root / accepted.generation_id,
        "phase3a": phase3a_root / accepted.generation_id,
    }
    if any(not path.is_dir() for path in protected_dirs.values()):
        raise FileNotFoundError("accepted M4 control artifacts are missing")
    protected_before = {name: _artifact_hashes(path) for name, path in protected_dirs.items()}
    phase3a_dir = protected_dirs["phase3a"]
    historical_path = accepted.generation_path / "m3_canonical_historical_bouts.parquet"
    historical = pd.DataFrame(pl.read_parquet(historical_path).to_dicts())
    divisions, input_hashes = load_weight_classes_from_m3_provenance(accepted.generation_path)
    snapshots = build_prefight_opponent_strength(historical, weight_classes=divisions)
    base = pd.DataFrame(accepted.frame.to_dicts())
    base["fight_date"] = pd.to_datetime(base["fight_date"], errors="raise").dt.normalize()
    pairwise = build_pairwise_opponent_strength(snapshots, base)
    augmented = base.merge(
        pairwise,
        on=["canonical_bout_id", "fight_date", "canonical_fighter_a_id", "canonical_fighter_b_id"],
        validate="one_to_one",
    )
    packs = feature_packs(accepted.feature_columns)
    split_frame = pl.read_parquet(phase3a_dir / "m4_phase3a_rolling_folds.parquet")
    phase3a_predictions = pl.read_parquet(phase3a_dir / "m4_phase3a_predictions.parquet")
    fold_members: dict[str, dict[str, set[str]]] = {}
    for fold_id in sorted(split_frame["fold_id"].unique().to_list()):
        fold_members[str(fold_id)] = {
            role: set(
                split_frame.filter((pl.col("fold_id") == fold_id) & (pl.col("role") == role))[
                    "canonical_bout_id"
                ].to_list()
            )
            for role in ("train", "validation")
        }
    benchmark_keys = set(
        phase3a_predictions.filter(pl.col("evaluation_partition") == "locked_benchmark")[
            "canonical_bout_id"
        ].to_list()
    )
    if len(benchmark_keys) != 1337 or any(
        ids["train"] & ids["validation"] for ids in fold_members.values()
    ):
        raise ValueError("accepted Phase 3A fold contract is invalid")
    development_keys = set().union(
        *(ids["train"] | ids["validation"] for ids in fold_members.values())
    )
    if development_keys & benchmark_keys or len(development_keys) != 7575:
        raise ValueError("Phase 3A development/benchmark membership leaks or changed")
    keyed = augmented.set_index("canonical_bout_id", drop=False)
    if set(keyed.index) != development_keys | benchmark_keys:
        raise ValueError("B1 feature rows do not exactly match accepted Phase 3A membership")
    candidate_rows: list[dict[str, Any]] = []
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
                audit = _audit(forward, swapped)
                row = {
                    "candidate_id": candidate_id,
                    "feature_pack": pack.pack_id,
                    "model": model_name,
                    "fold_id": fold_id,
                    "metrics": _metrics(validation_y, symmetric),
                    "calibration": calibration_summary(validation_y, symmetric),
                    "audit": audit,
                    "best_iteration_count": best_iteration,
                    "train_rows": len(train),
                    "validation_rows": len(validation),
                    "feature_count": len(pack.feature_columns),
                }
                candidate_rows.append(row)
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
    for row in candidate_rows:
        grouped[str(row["candidate_id"])].append(row)
    aggregates = {candidate_id: _summary(rows) for candidate_id, rows in grouped.items()}
    selected_id = _select(aggregates, definitions)
    phase3a_development_control_id = "base_130__phase3a_shallow_xgboost"
    practical_improvement = _practical_improvement_report(
        selected_id=selected_id,
        control_id=phase3a_development_control_id,
        candidate_rows=candidate_rows,
        aggregates=aggregates,
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
    phase3a_metrics = json.loads(
        (phase3a_dir / "m4_phase3a_metrics.json").read_text(encoding="utf-8")
    )
    phase3a_control = cast(dict[str, Any], phase3a_metrics["locked_benchmark"])
    phase3a_symmetric_metrics = cast(dict[str, float], phase3a_control["symmetric_metrics"])
    run_dir = output_root / accepted.generation_id
    run_dir.mkdir(parents=True, exist_ok=True)
    snapshots_path = run_dir / "m4_phase3b1_fighter_rating_snapshots.parquet"
    pairwise_path = run_dir / "m4_phase3b1_pairwise_opponent_strength.parquet"
    packs_path = run_dir / "m4_phase3b1_feature_packs.json"
    results_path = run_dir / "m4_phase3b1_rolling_candidate_results.parquet"
    predictions_path = run_dir / "m4_phase3b1_predictions.parquet"
    metrics_path = run_dir / "m4_phase3b1_metrics.json"
    comparison_path = run_dir / "m4_phase3b1_model_comparison.json"
    contract_path = run_dir / "m4_phase3b1_feature_contract.json"
    model_path = run_dir / "m4_phase3b1_selected_model.joblib"
    snapshots_frame = (
        pl.DataFrame(snapshots.to_dict(orient="list"))
        .with_columns(pl.col(pl.Float64).fill_nan(None))
        .sort(["canonical_bout_id", "canonical_fighter_id"])
    )
    pairwise_frame = (
        pl.DataFrame(pairwise.to_dict(orient="list"))
        .with_columns(pl.col(pl.Float64).fill_nan(None))
        .sort("canonical_bout_id")
    )
    flat_results = pl.DataFrame(
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
            for row in candidate_rows
        ]
    ).sort(["candidate_id", "fold_id"])
    predictions_frame = pl.DataFrame(pd.DataFrame(prediction_rows).to_dict(orient="list")).sort(
        ["evaluation_partition", "candidate_id", "fold_id", "canonical_bout_id"], nulls_last=True
    )
    snapshots_frame.write_parquet(snapshots_path, compression="zstd")
    pairwise_frame.write_parquet(pairwise_path, compression="zstd")
    _write_json(
        packs_path,
        _to_builtin(
            {
                "schema_version": M4_PHASE3B1_SCHEMA_VERSION,
                "packs": [
                    {
                        "pack_id": pack.pack_id,
                        "feature_count": len(pack.feature_columns),
                        "added_feature_count": pack.added_feature_count,
                        "feature_columns": list(pack.feature_columns),
                    }
                    for pack in packs
                ],
            }
        ),
    )
    flat_results.write_parquet(results_path, compression="zstd")
    predictions_frame.write_parquet(predictions_path, compression="zstd")
    joblib.dump(selected_model, model_path, compress=3)
    feature_contract = {
        "schema_version": M4_PHASE3B1_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "accepted_m3_final_acceptance_report_sha256": ACCEPTED_M3_ACCEPTANCE_SHA256,
        "rating_policy_id": RATING_POLICY_ID,
        "rating_constants": {"initial_elo": INITIAL_ELO, "k_factor": K_FACTOR},
        "same_date_policy": "snapshot_all_then_apply_aggregated_rating_updates",
        "null_policy": (
            "unknown opponent-history and unavailable weight class remain null; "
            "cold-start Elo is observed 1500"
        ),
        "pairwise_feature_columns": pairwise_frame.columns,
        "feature_packs": {pack.pack_id: list(pack.feature_columns) for pack in packs},
        "phase3a_split_identity_verified": True,
    }
    metrics = {
        "schema_version": M4_PHASE3B1_SCHEMA_VERSION,
        "candidate_aggregates": aggregates,
        "fold_results": candidate_rows,
        "selection": {
            "selected_candidate": selected_id,
            "selected_feature_pack": selected_pack_id,
            "selected_model": selected_model_name,
            "selection_scope": "development_period_rolling_validation_only",
            "benchmark_excluded": True,
            "priority": [
                "lowest_mean_log_loss",
                "lowest_mean_brier_score",
                "highest_mean_roc_auc",
                "lower_log_loss_standard_deviation",
                "better_worst_fold_log_loss",
                "exact_symmetry",
                "fewer_added_features",
                "simpler_model",
            ],
            "final_boosting_rounds": final_rounds,
            "final_boosting_round_policy": round_policy,
        },
        "practical_improvement_against_phase3a_development_control": practical_improvement,
        "inspected_locked_benchmark": benchmark_report,
    }
    comparison = {
        "schema_version": M4_PHASE3B1_SCHEMA_VERSION,
        "reporting_only_policy": "inspected benchmark metrics cannot alter B1 selection",
        "selected_b1": benchmark_report,
        "accepted_phase3a_xgboost": phase3a_control,
        "practical_improvement_against_phase3a_development_control": practical_improvement,
        "inspected_benchmark_difference_against_phase3a": {
            "benchmark_log_loss_delta": float(
                cast(dict[str, float], benchmark_report["metrics"])["log_loss"]
                - phase3a_symmetric_metrics["log_loss"]
            ),
            "interpretation": (
                "descriptive inspected-benchmark comparison only; no benchmark-based selection"
            ),
        },
    }
    _write_json(metrics_path, _to_builtin(metrics))
    _write_json(comparison_path, _to_builtin(comparison))
    _write_json(contract_path, _to_builtin(feature_contract))
    protected_after = {name: _artifact_hashes(path) for name, path in protected_dirs.items()}
    if protected_before != protected_after:
        raise ValueError("Phase 3B1 changed protected accepted M4 artifacts")
    output_paths = {
        "fighter_rating_snapshots": snapshots_path,
        "pairwise_opponent_strength": pairwise_path,
        "feature_packs": packs_path,
        "rolling_candidate_results": results_path,
        "predictions": predictions_path,
        "metrics": metrics_path,
        "model_comparison": comparison_path,
        "feature_contract": contract_path,
        "selected_model": model_path,
    }
    manifest_path = run_dir / "m4_phase3b1_training_manifest.json"
    manifest = {
        "schema_version": M4_PHASE3B1_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "rating_policy_id": RATING_POLICY_ID,
        "rating_constants": {"initial_elo": INITIAL_ELO, "k_factor": K_FACTOR},
        "same_date_policy": "snapshot_all_then_apply_aggregated_rating_updates",
        "input_hashes": {
            "m3_model_ready_binary.parquet": accepted.artifact_sha256,
            "m3_canonical_historical_bouts.parquet": _sha256_path(historical_path),
            "phase3a_rolling_folds.parquet": _sha256_path(
                phase3a_dir / "m4_phase3a_rolling_folds.parquet"
            ),
            "phase3a_predictions.parquet": _sha256_path(
                phase3a_dir / "m4_phase3a_predictions.parquet"
            ),
            **input_hashes,
        },
        "input_counts": {
            "historical_bouts": len(historical),
            "model_ready_bouts": len(base),
            "rating_snapshots": len(snapshots),
            "pairwise_rows": len(pairwise),
        },
        "artifact_shapes": {
            "fighter_rating_snapshots": {
                "rows": snapshots_frame.height,
                "columns": snapshots_frame.width,
            },
            "pairwise_opponent_strength": {
                "rows": pairwise_frame.height,
                "columns": pairwise_frame.width,
            },
            "rolling_candidate_results": {
                "rows": flat_results.height,
                "columns": flat_results.width,
            },
            "predictions": {"rows": predictions_frame.height, "columns": predictions_frame.width},
        },
        "null_counts": {
            name: int(pairwise_frame[name].null_count()) for name in pairwise_frame.columns
        },
        "date_ranges": {
            "historical": {
                "start": str(snapshots_frame["fight_date"].min()),
                "end": str(snapshots_frame["fight_date"].max()),
            },
            "model_ready": {
                "start": str(pairwise_frame["fight_date"].min()),
                "end": str(pairwise_frame["fight_date"].max()),
            },
        },
        "protected_artifacts_sha256": protected_before,
        "selection": metrics["selection"],
        "output_paths": {name: str(path) for name, path in output_paths.items()},
        "output_checksums": {name: _sha256_path(path) for name, path in output_paths.items()},
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "xgboost": xgb.__version__,
            "n_jobs": 1,
            "random_seed": RANDOM_SEED,
        },
    }
    _write_json(manifest_path, _to_builtin(manifest))
    return {
        "run_directory": str(run_dir),
        "selected_candidate": selected_id,
        "metrics_path": str(metrics_path),
        "metrics_sha256": _sha256_path(metrics_path),
        "training_manifest_path": str(manifest_path),
        "training_manifest_sha256": _sha256_path(manifest_path),
    }
