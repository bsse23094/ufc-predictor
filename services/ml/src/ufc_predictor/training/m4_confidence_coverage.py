"""M4 Phase 4B confidence and coverage evaluation for the accepted Phase 3C champion."""

from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import polars as pl
import sklearn
import xgboost as xgb

from ufc_predictor.training.m4_baselines import (
    _metrics,
    _sha256_path,
    _to_builtin,
    _write_json,
    calibration_summary,
    load_accepted_m3_data,
)
from ufc_predictor.training.m4_opponent_adjusted_performance import (
    PHASE3A_FOLDS_SHA256,
    PHASE3A_PREDICTIONS_SHA256,
)
from ufc_predictor.training.m4_opponent_strength import _artifact_hashes
from ufc_predictor.training.m4_optuna_tuning import (
    PHASE3C_CHAMPION_ID,
    PHASE3C_MANIFEST_SHA256,
)

M4_PHASE4B_SCHEMA_VERSION = "m4.phase4b.confidence_coverage.v1"
CONFIDENCE_MARGINS = tuple(round(value * 0.025, 3) for value in range(9))
OPERATING_POINT_COVERAGES = (1.0, 0.75, 0.50, 0.25)


def _class_coverage(target: np.ndarray[Any, Any], covered: np.ndarray[Any, Any]) -> dict[str, Any]:
    return {
        str(label): {
            "rows": int((target == label).sum()),
            "covered_rows": int(((target == label) & covered).sum()),
            "coverage": float(covered[target == label].mean()) if (target == label).any() else None,
        }
        for label in (0, 1)
    }


def _year_coverage(frame: pd.DataFrame, covered: np.ndarray[Any, Any]) -> dict[str, Any]:
    years = pd.to_datetime(frame["fight_date"], errors="raise").dt.year.to_numpy()
    return {
        str(year): {
            "rows": int((years == year).sum()),
            "covered_rows": int(((years == year) & covered).sum()),
            "coverage": float(covered[years == year].mean()),
        }
        for year in sorted(np.unique(years))
    }


def _margin_report(
    frame: pd.DataFrame, margin: float
) -> tuple[dict[str, Any], np.ndarray[Any, Any]]:
    probability = frame["symmetric_probability"].to_numpy(dtype=float)
    target = frame["target_fighter_a_won"].to_numpy(dtype=int)
    covered = np.abs(probability - 0.5) >= margin
    rejected = ~covered
    if not covered.any():
        raise ValueError("configured confidence margin rejected every row")
    metrics = _metrics(target[covered], probability[covered])
    rejected_accuracy = (
        float(((probability[rejected] >= 0.5).astype(int) == target[rejected]).mean())
        if rejected.any()
        else None
    )
    return {
        "margin": margin,
        "coverage": float(covered.mean()),
        "covered_rows": int(covered.sum()),
        "rejected_rows": int(rejected.sum()),
        "covered_metrics": metrics,
        "rejected_row_accuracy": rejected_accuracy,
        "class_coverage": _class_coverage(target, covered),
        "year_coverage": _year_coverage(frame, covered),
        "calibration": calibration_summary(target[covered], probability[covered]),
    }, covered


def _aggregate_margin(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [cast(dict[str, Any], row["covered_metrics"]) for row in rows]
    accuracy = [float(item["accuracy"]) for item in metrics]
    return {
        "coverage": float(np.mean([row["coverage"] for row in rows])),
        "covered_rows": int(sum(int(row["covered_rows"]) for row in rows)),
        "accuracy": float(np.mean(accuracy)),
        "balanced_accuracy": float(np.mean([item["balanced_accuracy"] for item in metrics])),
        "precision": float(np.mean([item["precision"] for item in metrics])),
        "recall": float(np.mean([item["recall"] for item in metrics])),
        "f1_score": float(np.mean([item["f1_score"] for item in metrics])),
        "log_loss": float(np.mean([item["log_loss"] for item in metrics])),
        "brier_score": float(np.mean([item["brier_score"] for item in metrics])),
        "roc_auc": float(
            np.mean([item["roc_auc"] for item in metrics if item["roc_auc"] is not None])
        ),
        "expected_calibration_error": float(
            np.mean([row["calibration"]["expected_calibration_error"] for row in rows])
        ),
        "rejected_row_accuracy": float(
            np.mean(
                [
                    row["rejected_row_accuracy"]
                    for row in rows
                    if row["rejected_row_accuracy"] is not None
                ]
            )
        )
        if any(row["rejected_row_accuracy"] is not None for row in rows)
        else None,
        "fold_accuracy_mean": float(np.mean(accuracy)),
        "fold_accuracy_standard_deviation": float(np.std(accuracy)),
        "worst_fold_accuracy": float(min(accuracy)),
    }


def select_operating_points(aggregates: dict[float, dict[str, Any]]) -> dict[str, float]:
    """Freeze coverage-constrained operating points from development folds only."""

    selected: dict[str, float] = {"full_coverage": 0.0}
    for minimum in OPERATING_POINT_COVERAGES[1:]:
        eligible = [
            (margin, report)
            for margin, report in aggregates.items()
            if float(report["coverage"]) >= minimum
        ]
        if not eligible:
            raise ValueError(f"no confidence margin reaches {minimum:.0%} coverage")
        selected[f"highest_accuracy_at_least_{int(minimum * 100)}pct_coverage"] = min(
            eligible,
            key=lambda item: (
                -float(item[1]["fold_accuracy_mean"]),
                -float(item[1]["coverage"]),
                float(item[0]),
            ),
        )[0]
    return selected


def _symmetry_audit(frame: pd.DataFrame, margin: float) -> dict[str, Any]:
    probability = frame["symmetric_probability"].to_numpy(dtype=float)
    swapped_probability = 1.0 - probability
    covered = np.abs(probability - 0.5) >= margin
    swapped_covered = np.abs(swapped_probability - 0.5) >= margin
    predictions = (probability >= 0.5).astype(int)
    swapped_predictions = (swapped_probability >= 0.5).astype(int)
    non_ties = probability != 0.5
    return {
        "maximum_coverage_decision_difference": int(
            np.abs(covered.astype(int) - swapped_covered).max()
        ),
        "coverage_decision_violations": int((covered != swapped_covered).sum()),
        "winner_complement_violations_non_ties": int(
            (predictions[non_ties] != (1 - swapped_predictions[non_ties])).sum()
        ),
        "exact_half_probability_ties": int((~non_ties).sum()),
        "threshold_center": 0.5,
    }


def run_m4_confidence_coverage(
    *,
    m3_root: Path = Path("data/processed/m3-v6"),
    phase1_root: Path = Path("data/processed/m4-baselines"),
    phase2_root: Path = Path("data/processed/m4-phase2-symmetry"),
    phase3a_root: Path = Path("data/processed/m4-phase3a-xgboost"),
    phase3b1_root: Path = Path("data/processed/m4-phase3b1-opponent-strength"),
    phase3c_root: Path = Path("data/processed/m4-phase3c-opponent-adjusted-performance"),
    phase3d_root: Path = Path("data/processed/m4-phase3d-optuna"),
    phase4a_root: Path = Path("data/processed/m4-phase4a-calibration-blending"),
    output_root: Path = Path("data/processed/m4-phase4b-confidence-coverage"),
) -> dict[str, object]:
    """Evaluate fixed selective-prediction margins without changing the champion."""

    accepted = load_accepted_m3_data(m3_root)
    protected_dirs = {
        "phase1": phase1_root / accepted.generation_id,
        "phase2": phase2_root / accepted.generation_id,
        "phase3a": phase3a_root / accepted.generation_id,
        "phase3b1": phase3b1_root / accepted.generation_id,
        "phase3c": phase3c_root / accepted.generation_id,
        "phase3d": phase3d_root / accepted.generation_id,
        "phase4a": phase4a_root / accepted.generation_id,
    }
    if any(not path.is_dir() for path in protected_dirs.values()):
        raise FileNotFoundError("accepted M4 artifacts are missing")
    protected_before = {name: _artifact_hashes(path) for name, path in protected_dirs.items()}
    phase3a_dir, phase3c_dir = protected_dirs["phase3a"], protected_dirs["phase3c"]
    if (
        _sha256_path(phase3a_dir / "m4_phase3a_rolling_folds.parquet") != PHASE3A_FOLDS_SHA256
        or _sha256_path(phase3a_dir / "m4_phase3a_predictions.parquet")
        != PHASE3A_PREDICTIONS_SHA256
    ):
        raise ValueError("accepted Phase 3A fold contract changed")
    manifest_path = phase3c_dir / "m4_phase3c_training_manifest.json"
    if _sha256_path(manifest_path) != PHASE3C_MANIFEST_SHA256:
        raise ValueError("accepted Phase 3C manifest hash changed")
    phase3c_manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    for name, expected in cast(dict[str, str], phase3c_manifest["output_checksums"]).items():
        filename = str(phase3c_manifest["output_paths"][name]).replace("\\", "/").split("/")[-1]
        if _sha256_path(phase3c_dir / filename) != expected:
            raise ValueError(f"accepted Phase 3C output hash changed: {name}")
    predictions = pl.read_parquet(phase3c_dir / "m4_phase3c_predictions.parquet").filter(
        pl.col("candidate_id") == PHASE3C_CHAMPION_ID
    )
    if predictions.height != 4751:
        raise ValueError("accepted Phase 3C champion prediction count changed")
    frame = pd.DataFrame(predictions.to_dicts())
    frame["fight_date"] = pd.to_datetime(frame["fight_date"], errors="raise").dt.normalize()
    development = frame[frame["evaluation_partition"] == "rolling_validation"].copy()
    benchmark = frame[frame["evaluation_partition"] == "inspected_locked_benchmark"].copy()
    if (
        len(development) != 3414
        or len(benchmark) != 1337
        or set(development["fold_id"].unique()) != {"fold_1", "fold_2", "fold_3"}
    ):
        raise ValueError("Phase 3C prediction partitions changed")
    splits = pl.read_parquet(phase3a_dir / "m4_phase3a_rolling_folds.parquet")
    for fold_id in ("fold_1", "fold_2", "fold_3"):
        expected_keys = set(
            splits.filter((pl.col("fold_id") == fold_id) & (pl.col("role") == "validation"))[
                "canonical_bout_id"
            ].to_list()
        )
        actual = set(development.loc[development["fold_id"] == fold_id, "canonical_bout_id"])
        if actual != expected_keys:
            raise ValueError(f"Phase 3C prediction keys do not reuse {fold_id}")

    fold_rows: list[dict[str, Any]] = []
    development_rows: list[dict[str, Any]] = []
    aggregate_by_margin: dict[float, dict[str, Any]] = {}
    for margin in CONFIDENCE_MARGINS:
        reports: list[dict[str, Any]] = []
        for fold_id in sorted(development["fold_id"].unique()):
            subset = development[development["fold_id"] == fold_id].copy()
            report, covered = _margin_report(subset, margin)
            report["fold_id"] = fold_id
            report["symmetry"] = _symmetry_audit(subset, margin)
            reports.append(report)
            fold_rows.append(report)
            for source, flag in zip(subset.to_dict(orient="records"), covered, strict=True):
                development_rows.append(
                    {
                        "canonical_bout_id": source["canonical_bout_id"],
                        "fight_date": source["fight_date"],
                        "fold_id": fold_id,
                        "margin": margin,
                        "target_fighter_a_won": int(source["target_fighter_a_won"]),
                        "symmetric_probability": float(source["symmetric_probability"]),
                        "covered": bool(flag),
                        "rejected": bool(not flag),
                        "predicted_fighter_a_wins": int(source["symmetric_probability"] >= 0.5),
                    }
                )
        aggregate_by_margin[margin] = _aggregate_margin(reports)
    operating_points = select_operating_points(aggregate_by_margin)
    benchmark_results: dict[str, Any] = {}
    for name, margin in operating_points.items():
        report, _covered = _margin_report(benchmark, margin)
        report["symmetry"] = _symmetry_audit(benchmark, margin)
        report["selection_scope"] = "frozen_from_development_rolling_folds_only"
        benchmark_results[name] = report

    run_dir = output_root / accepted.generation_id
    run_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "margin_grid": run_dir / "m4_phase4b_margin_grid.parquet",
        "fold_metrics": run_dir / "m4_phase4b_fold_metrics.parquet",
        "development_predictions": run_dir / "m4_phase4b_development_coverage_predictions.parquet",
        "operating_points": run_dir / "m4_phase4b_frozen_operating_points.json",
        "benchmark_results": run_dir / "m4_phase4b_benchmark_results.json",
        "metrics": run_dir / "m4_phase4b_metrics.json",
        "contract": run_dir / "m4_phase4b_confidence_contract.json",
    }
    grid_frame = pl.DataFrame(
        [{"margin": margin, **aggregate_by_margin[margin]} for margin in CONFIDENCE_MARGINS]
    ).sort("margin")
    folds_frame = pl.DataFrame(
        [
            {
                "fold_id": row["fold_id"],
                "margin": row["margin"],
                "coverage": row["coverage"],
                "covered_rows": row["covered_rows"],
                "rejected_rows": row["rejected_rows"],
                "accuracy": row["covered_metrics"]["accuracy"],
                "balanced_accuracy": row["covered_metrics"]["balanced_accuracy"],
                "precision": row["covered_metrics"]["precision"],
                "recall": row["covered_metrics"]["recall"],
                "f1_score": row["covered_metrics"]["f1_score"],
                "log_loss": row["covered_metrics"]["log_loss"],
                "brier_score": row["covered_metrics"]["brier_score"],
                "roc_auc": row["covered_metrics"]["roc_auc"],
                "expected_calibration_error": row["calibration"]["expected_calibration_error"],
                "rejected_row_accuracy": row["rejected_row_accuracy"],
                "worst_order_invariant": row["symmetry"]["coverage_decision_violations"] == 0,
            }
            for row in fold_rows
        ]
    ).sort(["margin", "fold_id"])
    development_frame = pl.DataFrame(pd.DataFrame(development_rows).to_dict(orient="list")).sort(
        ["margin", "fold_id", "canonical_bout_id"]
    )
    grid_frame.write_parquet(paths["margin_grid"], compression="zstd")
    folds_frame.write_parquet(paths["fold_metrics"], compression="zstd")
    development_frame.write_parquet(paths["development_predictions"], compression="zstd")
    metrics = {
        "schema_version": M4_PHASE4B_SCHEMA_VERSION,
        "champion_id": PHASE3C_CHAMPION_ID,
        "margins": list(CONFIDENCE_MARGINS),
        "development_margin_aggregates": aggregate_by_margin,
        "development_fold_results": fold_rows,
        "selection": {
            "scope": "development_rolling_folds_only",
            "operating_points": operating_points,
            "tie_breaking": ["highest_fold_mean_accuracy", "higher_coverage", "lower_margin"],
        },
        "inspected_locked_benchmark": benchmark_results,
    }
    contract = {
        "schema_version": M4_PHASE4B_SCHEMA_VERSION,
        "champion_id": PHASE3C_CHAMPION_ID,
        "phase3c_manifest_sha256": PHASE3C_MANIFEST_SHA256,
        "prediction_source": "accepted Phase 3C symmetrized probabilities",
        "coverage_rule": "abs(probability_a - 0.5) >= margin",
        "margins": list(CONFIDENCE_MARGINS),
        "benchmark_policy": "benchmark excluded from operating-point selection",
        "symmetry_policy": "coverage is centered at 0.5 and invariant under probability complement",
    }
    _write_json(
        paths["operating_points"],
        _to_builtin(
            {
                "schema_version": M4_PHASE4B_SCHEMA_VERSION,
                "operating_points": operating_points,
                "development_reports": {
                    name: aggregate_by_margin[margin] for name, margin in operating_points.items()
                },
            }
        ),
    )
    _write_json(
        paths["benchmark_results"],
        _to_builtin(
            {
                "schema_version": M4_PHASE4B_SCHEMA_VERSION,
                "operating_points": operating_points,
                "results": benchmark_results,
            }
        ),
    )
    _write_json(paths["metrics"], _to_builtin(metrics))
    _write_json(paths["contract"], _to_builtin(contract))
    protected_after = {name: _artifact_hashes(path) for name, path in protected_dirs.items()}
    if protected_before != protected_after:
        raise ValueError("Phase 4B changed protected accepted artifacts")
    manifest = {
        "schema_version": M4_PHASE4B_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "input_hashes": {
            "phase3c_manifest": PHASE3C_MANIFEST_SHA256,
            "phase3c_predictions": _sha256_path(phase3c_dir / "m4_phase3c_predictions.parquet"),
            "phase3a_rolling_folds": PHASE3A_FOLDS_SHA256,
            "phase3a_predictions": PHASE3A_PREDICTIONS_SHA256,
        },
        "protected_artifacts_sha256": protected_before,
        "artifact_shapes": {
            "margin_grid": {"rows": grid_frame.height, "columns": grid_frame.width},
            "fold_metrics": {"rows": folds_frame.height, "columns": folds_frame.width},
            "development_predictions": {
                "rows": development_frame.height,
                "columns": development_frame.width,
            },
        },
        "selection": metrics["selection"],
        "output_paths": {name: str(path) for name, path in paths.items()},
        "output_checksums": {name: _sha256_path(path) for name, path in paths.items()},
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "xgboost": xgb.__version__,
        },
    }
    manifest_path = run_dir / "m4_phase4b_training_manifest.json"
    _write_json(manifest_path, _to_builtin(manifest))
    return {
        "run_directory": str(run_dir),
        "operating_points": operating_points,
        "training_manifest_path": str(manifest_path),
        "training_manifest_sha256": _sha256_path(manifest_path),
    }
