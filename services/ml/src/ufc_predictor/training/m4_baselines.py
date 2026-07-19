"""Deterministic M4 Phase 1 temporal baseline training.

This module deliberately consumes only the accepted M3 binary projection.  It
does not materialize data, change a feature definition, or infer a generation
from a loose artifact path.
"""

from __future__ import annotations

import hashlib
import json
import platform
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import joblib
import numpy as np
import pandas as pd
import polars as pl
import sklearn
from sklearn.base import BaseEstimator
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ufc_predictor.m3_materialization import resolve_m3_current_generation, swap_model_ready_row

M4_SCHEMA_VERSION = "m4.phase1.temporal_baselines.v1"
SPLIT_POLICY_VERSION = "m4.phase1.distinct_fight_dates_70_15_15.v1"
ACCEPTED_M3_GENERATION_ID = "m3-74eeb9b7f49b5adca45e461a"
ACCEPTED_M3_ACCEPTANCE_SHA256 = "5844d6b59ea693c8620a3443d82f4d704254023eba32e8967d1d280c9cc02c5c"
RANDOM_SEED = 20260719
CALIBRATION_BIN_COUNT = 10

MetadataColumns = tuple[str, ...]
SplitName = Literal["train", "validation", "test"]


@dataclass(frozen=True, slots=True)
class AcceptedM3Data:
    """The loaded accepted artifact and its closed M3 contract."""

    frame: pl.DataFrame
    generation_id: str
    generation_path: Path
    artifact_path: Path
    artifact_sha256: str
    feature_columns: tuple[str, ...]
    metadata_columns: MetadataColumns
    target_column: str
    feature_schema_version: str


@dataclass(frozen=True, slots=True)
class TemporalSplit:
    """Deterministic assignment of each input row to one chronological split."""

    assignments: pd.Series
    boundaries: dict[str, str]


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_stable_json(value))


def _to_builtin(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return [_to_builtin(item) for item in value.tolist()]
    if isinstance(value, Mapping):
        return {str(key): _to_builtin(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_to_builtin(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    return value


def load_accepted_m3_data(
    m3_root: Path = Path("data/processed/m3-v6"),
) -> AcceptedM3Data:
    """Resolve and validate the one M3 generation accepted for M4 Phase 1."""

    generation_path = resolve_m3_current_generation(m3_root)
    if generation_path.name != ACCEPTED_M3_GENERATION_ID:
        raise ValueError(
            "M4 training is locked to the accepted M3 generation "
            f"{ACCEPTED_M3_GENERATION_ID}, got {generation_path.name}"
        )
    acceptance_path = generation_path / "m3_final_acceptance_report.json"
    if (
        not acceptance_path.is_file()
        or _sha256_path(acceptance_path) != ACCEPTED_M3_ACCEPTANCE_SHA256
    ):
        raise ValueError(
            "M3 final acceptance report is missing or does not match the accepted checksum"
        )
    acceptance = cast(dict[str, Any], json.loads(acceptance_path.read_text(encoding="utf-8")))
    if acceptance.get("acceptance_schema_version") != "m3-final-acceptance-v1":
        raise ValueError("M3 acceptance report schema is not accepted")

    manifest_path = generation_path / "m3_phase2_manifest.json"
    artifact_path = generation_path / "m3_model_ready_binary.parquet"
    if not manifest_path.is_file() or not artifact_path.is_file():
        raise FileNotFoundError("accepted M3 model-ready artifact or manifest is missing")
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    phase = cast(dict[str, Any], manifest.get("phase_3c2", {}))
    feature_columns = tuple(cast(list[str], phase.get("prediction_safe_feature_columns", [])))
    metadata_columns = tuple(cast(list[str], phase.get("metadata_columns", [])))
    target_columns = cast(list[str], phase.get("target_columns", []))
    if len(feature_columns) != 130 or len(set(feature_columns)) != 130:
        raise ValueError(
            "accepted M3 feature contract does not contain 130 unique ordered features"
        )
    if target_columns != ["target_fighter_a_won"]:
        raise ValueError("accepted M3 target contract changed")
    if len(metadata_columns) != 7:
        raise ValueError("accepted M3 metadata contract changed")

    frame = pl.read_parquet(artifact_path)
    expected_columns = [*metadata_columns, *feature_columns, target_columns[0]]
    if frame.columns != expected_columns:
        raise ValueError("model-ready columns do not exactly match the accepted ordered manifest")
    if frame.height != 8912 or frame["canonical_bout_id"].n_unique() != 8912:
        raise ValueError("accepted M3 model-ready artifact cardinality changed")
    if frame["canonical_bout_id"].is_duplicated().any():
        raise ValueError("model-ready artifact contains duplicate canonical bout IDs")
    target = target_columns[0]
    if frame[target].null_count() or set(frame[target].to_list()) != {0, 1}:
        raise ValueError("model-ready target must contain only 0 and 1")
    if int(frame[target].sum()) != 4610 or frame.filter(pl.col(target) == 0).height != 4302:
        raise ValueError("accepted M3 target distribution changed")
    if frame["fight_date"].null_count():
        raise ValueError("model-ready artifact contains null fight dates")
    float_columns = [
        name for name, dtype in frame.schema.items() if dtype in {pl.Float32, pl.Float64}
    ]
    if any(
        frame.filter(pl.col(name).is_not_null() & ~pl.col(name).is_finite()).height
        for name in float_columns
    ):
        raise ValueError("model-ready artifact contains NaN or infinite values")
    inventory = cast(dict[str, Any], acceptance.get("artifact_inventory", {}))
    accepted_artifact = cast(dict[str, Any], inventory.get("m3_model_ready_binary.parquet", {}))
    artifact_sha256 = _sha256_path(artifact_path)
    if accepted_artifact.get("sha256") != artifact_sha256:
        raise ValueError("model-ready artifact checksum does not match final M3 acceptance")
    return AcceptedM3Data(
        frame=frame,
        generation_id=generation_path.name,
        generation_path=generation_path,
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha256,
        feature_columns=feature_columns,
        metadata_columns=metadata_columns,
        target_column=target,
        feature_schema_version=str(phase["model_ready_schema_version"]),
    )


def create_temporal_split(frame: pd.DataFrame) -> TemporalSplit:
    """Split by whole dates nearest to 70% and 85% cumulative input rows."""

    if frame.empty or "fight_date" not in frame:
        raise ValueError("temporal split needs non-empty rows with fight_date")
    dates = pd.to_datetime(frame["fight_date"], errors="raise").dt.normalize()
    date_counts = dates.value_counts().sort_index()
    if len(date_counts) < 3:
        raise ValueError("temporal split requires at least three distinct fight dates")
    cumulative = date_counts.cumsum()
    row_count = len(frame)

    def boundary(target: float, start_index: int = 0) -> int:
        candidates = list(range(start_index, len(date_counts)))
        return min(candidates, key=lambda index: (abs(int(cumulative.iloc[index]) - target), index))

    train_index = boundary(row_count * 0.70)
    validation_index = boundary(row_count * 0.85, train_index + 1)
    if validation_index >= len(date_counts) - 1:
        validation_index = len(date_counts) - 2
    if train_index >= validation_index:
        train_index = validation_index - 1
    train_end = date_counts.index[train_index]
    validation_end = date_counts.index[validation_index]
    assignment = pd.Series("test", index=frame.index, dtype="string")
    assignment.loc[dates <= train_end] = "train"
    assignment.loc[(dates > train_end) & (dates <= validation_end)] = "validation"
    if not {"train", "validation", "test"} == set(assignment.unique()):
        raise ValueError("temporal split produced an empty partition")
    return TemporalSplit(
        assignments=assignment,
        boundaries={
            "train_end_date": train_end.date().isoformat(),
            "validation_start_date": (train_end + pd.Timedelta(days=1)).date().isoformat(),
            "validation_end_date": validation_end.date().isoformat(),
            "test_start_date": (validation_end + pd.Timedelta(days=1)).date().isoformat(),
        },
    )


def _feature_matrix(frame: pd.DataFrame, feature_columns: Iterable[str]) -> pd.DataFrame:
    features = frame.loc[:, list(feature_columns)].copy()
    return features.astype(float)


def build_logistic_pipeline() -> Pipeline:
    """Return the fixed training-only preprocessing and linear baseline."""

    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            (
                "model",
                LogisticRegression(C=1.0, max_iter=1000, random_state=RANDOM_SEED, solver="lbfgs"),
            ),
        ]
    )


def build_tree_pipeline() -> Pipeline:
    """Return the intentionally small deterministic histogram-tree baseline."""

    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            (
                "model",
                HistGradientBoostingClassifier(
                    learning_rate=0.08,
                    max_iter=120,
                    max_leaf_nodes=15,
                    l2_regularization=1.0,
                    random_state=RANDOM_SEED,
                ),
            ),
        ]
    )


def _metrics(target: np.ndarray[Any, Any], probability: np.ndarray[Any, Any]) -> dict[str, Any]:
    prediction = (probability >= 0.5).astype(int)
    values: dict[str, Any] = {
        "row_count": len(target),
        "accuracy": float(accuracy_score(target, prediction)),
        "balanced_accuracy": float(balanced_accuracy_score(target, prediction)),
        "log_loss": float(log_loss(target, probability, labels=[0, 1])),
        "brier_score": float(brier_score_loss(target, probability)),
        "precision": float(precision_score(target, prediction, zero_division=0)),
        "recall": float(recall_score(target, prediction, zero_division=0)),
        "f1_score": float(f1_score(target, prediction, zero_division=0)),
        "confusion_matrix": confusion_matrix(target, prediction, labels=[0, 1]).tolist(),
        "positive_prediction_rate": float(prediction.mean()),
    }
    values["roc_auc"] = (
        float(roc_auc_score(target, probability)) if len(np.unique(target)) == 2 else None
    )
    return values


def calibration_summary(
    target: np.ndarray[Any, Any], probability: np.ndarray[Any, Any]
) -> dict[str, Any]:
    """Uniform ten-bin reliability summary; empty bins are explicit."""

    edges = np.linspace(0.0, 1.0, CALIBRATION_BIN_COUNT + 1)
    bins: list[dict[str, Any]] = []
    ece = 0.0
    for index in range(CALIBRATION_BIN_COUNT):
        low, high = float(edges[index]), float(edges[index + 1])
        selected = (probability >= low) & (
            (probability < high) if index < 9 else (probability <= high)
        )
        count = int(selected.sum())
        if count:
            mean_probability = float(probability[selected].mean())
            observed_rate = float(target[selected].mean())
            ece += (count / len(target)) * abs(mean_probability - observed_rate)
        else:
            mean_probability = None
            observed_rate = None
        bins.append(
            {
                "lower_inclusive": low,
                "upper_inclusive": high if index == 9 else None,
                "upper_exclusive": None if index == 9 else high,
                "count": count,
                "mean_predicted_probability": mean_probability,
                "observed_positive_rate": observed_rate,
            }
        )
    return {
        "binning_policy": "10_uniform_bins_closed_on_final_bin",
        "expected_calibration_error": ece,
        "bins": bins,
    }


def _split_summary(frame: pd.DataFrame, assignments: pd.Series) -> dict[str, object]:
    summaries: dict[str, object] = {}
    for split in ("train", "validation", "test"):
        subset = frame.loc[assignments == split]
        target = subset["target_fighter_a_won"].astype(int)
        cold_start = subset["a_cold_start"].fillna(True).astype(bool) | subset[
            "b_cold_start"
        ].fillna(True).astype(bool)
        missingness = subset.filter(like="_missing").fillna(True).astype(bool)
        years = pd.to_datetime(subset["fight_date"]).dt.year
        year_distribution = {
            str(year): {
                "row_count": int((years == year).sum()),
                "positive_count": int(target.loc[years == year].sum()),
                "positive_prevalence": float(target.loc[years == year].mean()),
            }
            for year in sorted(years.unique())
        }
        summaries[split] = {
            "row_count": len(subset),
            "positive_count": int(target.sum()),
            "negative_count": int(len(target) - target.sum()),
            "positive_prevalence": float(target.mean()),
            "earliest_fight_date": pd.to_datetime(subset["fight_date"]).min().date().isoformat(),
            "latest_fight_date": pd.to_datetime(subset["fight_date"]).max().date().isoformat(),
            "cold_start_any_count": int(cold_start.sum()),
            "cold_start_any_rate": float(cold_start.mean()),
            "missing_feature_cell_count": int(missingness.to_numpy().sum()),
            "missing_feature_cell_rate": float(missingness.to_numpy().mean()),
            "year_distribution": year_distribution,
        }
    return summaries


def _year_summary(
    frame: pd.DataFrame, target: np.ndarray[Any, Any], probability: np.ndarray[Any, Any]
) -> dict[str, object]:
    result: dict[str, object] = {}
    years = pd.to_datetime(frame["fight_date"]).dt.year
    for year in sorted(years.unique()):
        selected = (years == year).to_numpy()
        year_target, year_probability = target[selected], probability[selected]
        base: dict[str, object] = {
            "row_count": len(year_target),
            "positive_count": int(year_target.sum()),
            "positive_prevalence": float(year_target.mean()),
        }
        if len(np.unique(year_target)) == 2:
            metrics = _metrics(year_target, year_probability)
            base.update(
                {key: metrics[key] for key in ("accuracy", "roc_auc", "log_loss", "brier_score")}
            )
            base["metrics_defined"] = True
        else:
            base.update(
                {
                    "accuracy": None,
                    "roc_auc": None,
                    "log_loss": None,
                    "brier_score": None,
                    "metrics_defined": False,
                }
            )
        result[str(year)] = base
    return result


def _swap_audit(
    model: BaseEstimator | None,
    frame: pd.DataFrame,
    feature_columns: tuple[str, ...],
    majority_probability: float | None = None,
) -> tuple[np.ndarray[Any, Any], dict[str, object]]:
    rows = frame.to_dict(orient="records")
    swapped = pd.DataFrame([swap_model_ready_row(cast(dict[str, object], row)) for row in rows])
    original_x = _feature_matrix(frame, feature_columns)
    swapped_x = _feature_matrix(swapped, feature_columns)
    if model is None:
        if majority_probability is None:
            raise ValueError("majority probability is required for a constant baseline")
        swapped_probability = np.full(len(frame), majority_probability, dtype=float)
        original_probability = np.full(len(frame), majority_probability, dtype=float)
    else:
        original_probability = cast(Any, model).predict_proba(original_x)[:, 1]
        swapped_probability = cast(Any, model).predict_proba(swapped_x)[:, 1]
    error = np.abs(original_probability - (1.0 - swapped_probability))
    original_prediction = (original_probability >= 0.5).astype(int)
    swapped_prediction = (swapped_probability >= 0.5).astype(int)
    return swapped_probability, {
        "mean_absolute_complement_error": float(error.mean()),
        "median_absolute_complement_error": float(np.median(error)),
        "maximum_absolute_complement_error": float(error.max()),
        "violations_above_1e-6": int((error > 1e-6).sum()),
        "violations_above_1e-3": int((error > 1e-3).sum()),
        "violations_above_1e-2": int((error > 1e-2).sum()),
        "hard_prediction_complement_consistent_count": int(
            (original_prediction == (1 - swapped_prediction)).sum()
        ),
        "hard_prediction_complement_consistency_rate": float(
            (original_prediction == (1 - swapped_prediction)).mean()
        ),
    }


def _pipeline_state(pipeline: Pipeline, feature_columns: tuple[str, ...]) -> dict[str, object]:
    imputer = cast(SimpleImputer, pipeline.named_steps["imputer"])
    state: dict[str, object] = {
        "imputation_policy": "median fitted only on chronological training rows",
        "imputation_values": dict(zip(feature_columns, imputer.statistics_.tolist(), strict=True)),
    }
    if "scaler" in pipeline.named_steps:
        scaler = cast(StandardScaler, pipeline.named_steps["scaler"])
        state["scaling_policy"] = "standard scaling fitted only on chronological training rows"
        state["scaling_mean"] = dict(zip(feature_columns, scaler.mean_.tolist(), strict=True))
        state["scaling_scale"] = dict(zip(feature_columns, scaler.scale_.tolist(), strict=True))
    return state


def run_m4_baseline_training(
    *,
    m3_root: Path = Path("data/processed/m3-v6"),
    output_root: Path = Path("data/processed/m4-baselines"),
) -> dict[str, object]:
    """Train and publish exactly the Phase 1 majority, logistic, and tree baselines."""

    np.random.seed(RANDOM_SEED)
    accepted = load_accepted_m3_data(m3_root)
    frame = pd.DataFrame(accepted.frame.to_dicts())
    split = create_temporal_split(frame)
    assignments = split.assignments
    train = frame.loc[assignments == "train"].reset_index(drop=True)
    validation = frame.loc[assignments == "validation"].reset_index(drop=True)
    test = frame.loc[assignments == "test"].reset_index(drop=True)
    partitions = {"train": train, "validation": validation, "test": test}
    train_x = _feature_matrix(train, accepted.feature_columns)
    train_y = train[accepted.target_column].astype(int).to_numpy()
    majority_probability = float(train_y.mean())
    majority_class = int(majority_probability >= 0.5)
    logistic = build_logistic_pipeline().fit(train_x, train_y)
    tree = build_tree_pipeline().fit(train_x, train_y)
    models: dict[str, BaseEstimator | None] = {
        "majority": None,
        "logistic_regression": logistic,
        "hist_gradient_boosting": tree,
    }
    configurations: dict[str, object] = {
        "majority": {
            "probability": majority_probability,
            "predicted_class": majority_class,
            "fit_scope": "training only",
        },
        "logistic_regression": {
            "C": 1.0,
            "max_iter": 1000,
            "random_state": RANDOM_SEED,
            "solver": "lbfgs",
        },
        "hist_gradient_boosting": {
            "learning_rate": 0.08,
            "max_iter": 120,
            "max_leaf_nodes": 15,
            "l2_regularization": 1.0,
            "random_state": RANDOM_SEED,
        },
    }
    metric_report: dict[str, Any] = {"schema_version": M4_SCHEMA_VERSION, "models": {}}
    prediction_rows: list[dict[str, object]] = []
    for model_name, model in models.items():
        per_model: dict[str, Any] = {"splits": {}, "corner_swap_audit": {}, "test_by_year": {}}
        for split_name, subset in partitions.items():
            target = subset[accepted.target_column].astype(int).to_numpy()
            x = _feature_matrix(subset, accepted.feature_columns)
            probability = (
                np.full(len(subset), majority_probability, dtype=float)
                if model is None
                else cast(Any, model).predict_proba(x)[:, 1]
            )
            swapped_probability, audit = _swap_audit(
                model, subset, accepted.feature_columns, majority_probability
            )
            per_model["splits"][split_name] = {
                "metrics": _metrics(target, probability),
                "calibration": calibration_summary(target, probability),
            }
            if split_name != "train":
                per_model["corner_swap_audit"][split_name] = audit
            if split_name == "test":
                per_model["test_by_year"] = _year_summary(subset, target, probability)
            predicted = (probability >= 0.5).astype(int)
            for row, predicted_class, p, swapped_p in zip(
                subset[["canonical_bout_id", "fight_date", accepted.target_column]].to_dict(
                    orient="records"
                ),
                predicted,
                probability,
                swapped_probability,
                strict=True,
            ):
                prediction_rows.append(
                    {
                        "canonical_bout_id": row["canonical_bout_id"],
                        "fight_date": row["fight_date"],
                        "split": split_name,
                        "target_fighter_a_won": int(row[accepted.target_column]),
                        "model_name": model_name,
                        "predicted_class": int(predicted_class),
                        "probability_fighter_a_wins": float(p),
                        "swapped_probability_fighter_a_wins": float(swapped_p),
                        "complement_error": float(abs(p - (1.0 - swapped_p))),
                    }
                )
        metric_report["models"][model_name] = per_model

    selected_model = min(
        ("logistic_regression", "hist_gradient_boosting"),
        key=lambda name: (
            cast(dict[str, Any], cast(dict[str, Any], metric_report["models"])[name])["splits"][
                "validation"
            ]["metrics"]["log_loss"],
            -cast(dict[str, Any], cast(dict[str, Any], metric_report["models"])[name])["splits"][
                "validation"
            ]["metrics"]["roc_auc"],
            name,
        ),
    )
    metric_report["selected_model"] = {
        "name": selected_model,
        "selection_policy": (
            "lowest validation log loss; ROC-AUC then name break ties; test excluded"
        ),
        "selected_test_metrics": cast(
            dict[str, Any], cast(dict[str, Any], metric_report["models"])[selected_model]
        )["splits"]["test"]["metrics"],
    }

    run_dir = output_root / accepted.generation_id
    run_dir.mkdir(parents=True, exist_ok=True)
    split_records = (
        frame[["canonical_bout_id", "fight_date", accepted.target_column]]
        .assign(split=assignments)
        .sort_values("canonical_bout_id")
        .loc[:, ["canonical_bout_id", "fight_date", "split", accepted.target_column]]
        .to_dict(orient="list")
    )
    split_frame = pl.DataFrame(split_records)
    prediction_frame = pl.DataFrame(pd.DataFrame(prediction_rows).to_dict(orient="list")).sort(
        ["model_name", "split", "canonical_bout_id"]
    )
    split_path = run_dir / "m4_temporal_splits.parquet"
    predictions_path = run_dir / "m4_baseline_predictions.parquet"
    metrics_path = run_dir / "m4_baseline_metrics.json"
    feature_contract_path = run_dir / "m4_feature_contract.json"
    manifest_path = run_dir / "m4_training_manifest.json"
    logistic_path = run_dir / "m4_logistic_regression.joblib"
    tree_path = run_dir / "m4_hist_gradient_boosting.joblib"
    split_frame.write_parquet(split_path, compression="zstd")
    prediction_frame.write_parquet(predictions_path, compression="zstd")
    joblib.dump(logistic, logistic_path, compress=3)
    joblib.dump(tree, tree_path, compress=3)
    constant_features = [
        name for name in accepted.feature_columns if train_x[name].nunique(dropna=False) <= 1
    ]
    feature_contract = {
        "schema_version": M4_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "feature_schema_version": accepted.feature_schema_version,
        "feature_count": len(accepted.feature_columns),
        "ordered_feature_columns": list(accepted.feature_columns),
        "metadata_columns": list(accepted.metadata_columns),
        "target_column": accepted.target_column,
        "constant_or_unusable_features_detected_on_training_only": constant_features,
        "logistic_regression_preprocessing": _pipeline_state(logistic, accepted.feature_columns),
        "hist_gradient_boosting_preprocessing": _pipeline_state(tree, accepted.feature_columns),
    }
    _write_json(feature_contract_path, _to_builtin(feature_contract))
    _write_json(metrics_path, _to_builtin(metric_report))
    output_paths = {
        "temporal_splits": split_path,
        "baseline_predictions": predictions_path,
        "baseline_metrics": metrics_path,
        "feature_contract": feature_contract_path,
        "logistic_model": logistic_path,
        "tree_model": tree_path,
    }
    manifest = {
        "schema_version": M4_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "accepted_m3_final_acceptance_report_sha256": ACCEPTED_M3_ACCEPTANCE_SHA256,
        "model_ready_artifact_path": str(accepted.artifact_path),
        "model_ready_artifact_sha256": accepted.artifact_sha256,
        "feature_registry_version": accepted.feature_schema_version,
        "ordered_feature_columns": list(accepted.feature_columns),
        "feature_count": len(accepted.feature_columns),
        "metadata_columns": list(accepted.metadata_columns),
        "target_column": accepted.target_column,
        "split_policy": {"version": SPLIT_POLICY_VERSION, "boundaries": split.boundaries},
        "split_summary": _split_summary(frame, assignments),
        "preprocessing": {
            "missing_value_policy": "median imputation fit only on training rows",
            "constant_feature_policy": "detected and persisted; no accepted features dropped",
        },
        "model_configurations": configurations,
        "random_seeds": {"numpy": RANDOM_SEED, "scikit_learn_estimators": RANDOM_SEED},
        "output_paths": {key: str(path) for key, path in output_paths.items()},
        "output_row_counts": {
            "temporal_splits": split_frame.height,
            "baseline_predictions": prediction_frame.height,
        },
        "output_checksums": {key: _sha256_path(path) for key, path in output_paths.items()},
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "polars": pl.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "metric_summary": metric_report,
        "corner_swap_audit_summary": {
            name: cast(dict[str, Any], metric_report["models"])[name]["corner_swap_audit"]
            for name in models
        },
        "determinism_replay_summary": (
            "fixed seeds, stable sorted JSON, sorted row outputs, and date-only split policy"
        ),
    }
    _write_json(manifest_path, _to_builtin(manifest))
    return {
        "run_directory": str(run_dir),
        "training_manifest_path": str(manifest_path),
        "training_manifest_sha256": _sha256_path(manifest_path),
        "baseline_metrics_path": str(metrics_path),
        "baseline_metrics_sha256": _sha256_path(metrics_path),
        "baseline_predictions_path": str(predictions_path),
        "baseline_predictions_sha256": _sha256_path(predictions_path),
        "selected_model": selected_model,
        "split_summary": manifest["split_summary"],
    }
