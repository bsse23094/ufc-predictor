"""M4 immutable champion registry and deployment bundle assembly."""

from __future__ import annotations

import json
import platform
import shutil
from pathlib import Path
from typing import Any, cast

import joblib
import numpy as np
import polars as pl
import sklearn
import xgboost as xgb

from ufc_predictor.training.m4_baselines import (
    _sha256_path,
    _to_builtin,
    _write_json,
    load_accepted_m3_data,
)
from ufc_predictor.training.m4_opponent_adjusted_performance import (
    PHASE3A_FOLDS_SHA256,
    PHASE3A_PREDICTIONS_SHA256,
)
from ufc_predictor.training.m4_opponent_strength import _artifact_hashes
from ufc_predictor.training.m4_optuna_tuning import (
    PHASE3C_CHAMPION_ID as PHASE3C_CHAMPION_ID,
)
from ufc_predictor.training.m4_optuna_tuning import (
    PHASE3C_CHAMPION_PACK,
    PHASE3C_MANIFEST_SHA256,
)

M4_FINAL_SCHEMA_VERSION = "m4.final_champion_registry.v1"
PHASE4B_MANIFEST_SHA256 = "2d0230af18283e682be8fd0cbb50f52f413d066f6bf8c2a9089d97e9875c4d49"
RECOMMENDED_OPERATING_POINTS = {
    "default_full_coverage": 0.0,
    "medium_confidence": 0.075,
    "high_confidence": 0.125,
}


def _load_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _feature_swap_registry(features: list[str]) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    names = set(features)
    for name in features:
        if name.startswith("a_"):
            peer = f"b_{name[2:]}"
            if peer not in names:
                raise ValueError(f"missing swap peer for {name}")
            values.append({"feature": name, "swap_feature": peer, "transform": "exchange"})
        elif name.startswith("b_"):
            values.append(
                {"feature": name, "swap_feature": f"a_{name[2:]}", "transform": "exchange"}
            )
        elif name.startswith("diff_"):
            values.append({"feature": name, "swap_feature": name, "transform": "negate"})
        elif name.endswith("_a"):
            peer = f"{name[:-2]}_b"
            values.append(
                {"feature": name, "swap_feature": peer, "transform": "exchange"}
                if peer in names
                else {"feature": name, "swap_feature": name, "transform": "complement"}
            )
        elif name.endswith("_b"):
            values.append(
                {"feature": name, "swap_feature": f"{name[:-2]}_a", "transform": "exchange"}
            )
        else:
            raise ValueError(f"unsupported champion feature orientation: {name}")
    return values


def run_m4_final_champion_bundle(
    *,
    m3_root: Path = Path("data/processed/m3-v6"),
    phase1_root: Path = Path("data/processed/m4-baselines"),
    phase2_root: Path = Path("data/processed/m4-phase2-symmetry"),
    phase3a_root: Path = Path("data/processed/m4-phase3a-xgboost"),
    phase3b1_root: Path = Path("data/processed/m4-phase3b1-opponent-strength"),
    phase3c_root: Path = Path("data/processed/m4-phase3c-opponent-adjusted-performance"),
    phase3d_root: Path = Path("data/processed/m4-phase3d-optuna"),
    phase4a_root: Path = Path("data/processed/m4-phase4a-calibration-blending"),
    phase4b_root: Path = Path("data/processed/m4-phase4b-confidence-coverage"),
    output_root: Path = Path("data/processed/m4-final-champion"),
) -> dict[str, object]:
    """Publish a byte-stable deployment bundle from accepted immutable artifacts."""

    accepted = load_accepted_m3_data(m3_root)
    protected_dirs = {
        "phase1": phase1_root / accepted.generation_id,
        "phase2": phase2_root / accepted.generation_id,
        "phase3a": phase3a_root / accepted.generation_id,
        "phase3b1": phase3b1_root / accepted.generation_id,
        "phase3c": phase3c_root / accepted.generation_id,
        "phase3d": phase3d_root / accepted.generation_id,
        "phase4a": phase4a_root / accepted.generation_id,
        "phase4b": phase4b_root / accepted.generation_id,
    }
    if any(not path.is_dir() for path in protected_dirs.values()):
        raise FileNotFoundError("accepted M4 artifacts are missing")
    protected_before = {name: _artifact_hashes(path) for name, path in protected_dirs.items()}
    phase3a_dir, phase3c_dir, phase4b_dir = (
        protected_dirs["phase3a"],
        protected_dirs["phase3c"],
        protected_dirs["phase4b"],
    )
    if _sha256_path(phase3c_dir / "m4_phase3c_training_manifest.json") != PHASE3C_MANIFEST_SHA256:
        raise ValueError("accepted Phase 3C manifest hash changed")
    if _sha256_path(phase4b_dir / "m4_phase4b_training_manifest.json") != PHASE4B_MANIFEST_SHA256:
        raise ValueError("accepted Phase 4B manifest hash changed")
    if (
        _sha256_path(phase3a_dir / "m4_phase3a_rolling_folds.parquet") != PHASE3A_FOLDS_SHA256
        or _sha256_path(phase3a_dir / "m4_phase3a_predictions.parquet")
        != PHASE3A_PREDICTIONS_SHA256
    ):
        raise ValueError("accepted Phase 3A split hashes changed")
    phase3c_manifest = _load_json(phase3c_dir / "m4_phase3c_training_manifest.json")
    for name, expected in cast(dict[str, str], phase3c_manifest["output_checksums"]).items():
        filename = str(phase3c_manifest["output_paths"][name]).replace("\\", "/").split("/")[-1]
        if _sha256_path(phase3c_dir / filename) != expected:
            raise ValueError(f"accepted Phase 3C output hash changed: {name}")
    phase4b_manifest = _load_json(phase4b_dir / "m4_phase4b_training_manifest.json")
    for name, expected in cast(dict[str, str], phase4b_manifest["output_checksums"]).items():
        filename = str(phase4b_manifest["output_paths"][name]).replace("\\", "/").split("/")[-1]
        if _sha256_path(phase4b_dir / filename) != expected:
            raise ValueError(f"accepted Phase 4B output hash changed: {name}")
    packs = _load_json(phase3c_dir / "m4_phase3c_feature_packs.json")
    pack = next(item for item in packs["packs"] if item["pack_id"] == PHASE3C_CHAMPION_PACK)
    features = list(cast(list[str], pack["feature_columns"]))
    metrics = _load_json(phase3c_dir / "m4_phase3c_metrics.json")
    if metrics["selection"]["selected_leader"] != PHASE3C_CHAMPION_ID:
        raise ValueError("official Phase 3C champion changed")
    operating = _load_json(phase4b_dir / "m4_phase4b_frozen_operating_points.json")
    points = cast(dict[str, float], operating["operating_points"])
    if {
        "full_coverage",
        "highest_accuracy_at_least_50pct_coverage",
        "highest_accuracy_at_least_25pct_coverage",
    } - set(points):
        raise ValueError("Phase 4B operating points are incomplete")
    if (
        points["full_coverage"] != RECOMMENDED_OPERATING_POINTS["default_full_coverage"]
        or points["highest_accuracy_at_least_50pct_coverage"]
        != RECOMMENDED_OPERATING_POINTS["medium_confidence"]
        or points["highest_accuracy_at_least_25pct_coverage"]
        != RECOMMENDED_OPERATING_POINTS["high_confidence"]
    ):
        raise ValueError("Phase 4B accepted operating points changed")
    benchmark_results = _load_json(phase4b_dir / "m4_phase4b_benchmark_results.json")
    folds = pl.read_parquet(phase3a_dir / "m4_phase3a_rolling_folds.parquet")
    benchmark = pl.read_parquet(phase3a_dir / "m4_phase3a_predictions.parquet").filter(
        pl.col("evaluation_partition") == "locked_benchmark"
    )
    model_source = phase3c_dir / "m4_phase3c_selected_model.joblib"
    model = joblib.load(model_source)
    if not hasattr(model, "predict_proba"):
        raise ValueError("champion model cannot perform probability inference")
    run_dir = output_root / accepted.generation_id
    run_dir.mkdir(parents=True, exist_ok=True)
    model_path = run_dir / "m4_final_champion_model.joblib"
    shutil.copyfile(model_source, model_path)
    bundle_path = run_dir / "m4_final_champion_bundle.json"
    pointer_path = run_dir / "m4_final_champion_pointer.json"
    bundle = {
        "schema_version": M4_FINAL_SCHEMA_VERSION,
        "champion_id": PHASE3C_CHAMPION_ID,
        "accepted_m3_generation_id": accepted.generation_id,
        "model": {
            "filename": model_path.name,
            "sha256": _sha256_path(model_path),
            "family": "phase3a_shallow_xgboost",
            "model_schema_version": phase3c_manifest["schema_version"],
        },
        "feature_contract": {
            "feature_schema_version": phase3c_manifest["schema_version"],
            "ordered_feature_columns": features,
            "feature_count": len(features),
            "preprocessing_and_missing_value_policy": (
                "XGBoost native missing-value routing; no imputation outside the fitted model"
            ),
        },
        "inference_contract": {
            "probability_policy": "p = 0.5 * (p_forward + (1 - p_swapped))",
            "symmetrized_inference_required": True,
            "fighter_corner_swap_registry": _feature_swap_registry(features),
            "confidence_rule": "abs(probability_a - 0.5) >= margin",
            "confidence_threshold_center": 0.5,
        },
        "input_artifact_hashes": {
            "phase3c_manifest": PHASE3C_MANIFEST_SHA256,
            "phase3c_selected_model": _sha256_path(model_source),
            "phase3c_feature_contract": _sha256_path(
                phase3c_dir / "m4_phase3c_feature_contract.json"
            ),
            "phase3c_metrics": _sha256_path(phase3c_dir / "m4_phase3c_metrics.json"),
            "phase4b_manifest": PHASE4B_MANIFEST_SHA256,
            "phase4b_contract": _sha256_path(phase4b_dir / "m4_phase4b_confidence_contract.json"),
            "phase4b_operating_points": _sha256_path(
                phase4b_dir / "m4_phase4b_frozen_operating_points.json"
            ),
        },
        "training_date_cutoff": str(
            folds.filter(pl.col("role") == "validation")["fight_date"].max()
        ),
        "inspected_benchmark": {
            "date_start": str(benchmark["fight_date"].min()),
            "date_end": str(benchmark["fight_date"].max()),
            "labels_not_used_for_champion_decision": True,
        },
        "full_coverage_metrics": benchmark_results["results"]["full_coverage"],
        "confidence_operating_points": {
            "recommended": RECOMMENDED_OPERATING_POINTS,
            "frozen_phase4b_points": points,
            "selective_accuracy_label": "covered-row accuracy only; not full-coverage accuracy",
        },
        "champion_selection_rationale": {
            "phase3c_selection": metrics["selection"],
            "official_champion_unchanged_by_later_phases": True,
        },
        "limitations": [
            "probabilities depend on accepted pre-fight feature availability",
            (
                "confidence margins abstain from low-confidence fights and do not improve "
                "full-coverage accuracy"
            ),
            "selective accuracy is reported only for covered rows",
            "benchmark dates are inspected only and were not used for champion selection",
        ],
    }
    _write_json(bundle_path, _to_builtin(bundle))
    pointer = {
        "schema_version": M4_FINAL_SCHEMA_VERSION,
        "champion_id": PHASE3C_CHAMPION_ID,
        "immutable_bundle": {"path": bundle_path.name, "sha256": _sha256_path(bundle_path)},
        "model": {"path": model_path.name, "sha256": _sha256_path(model_path)},
        "mutable_training_state_copied": False,
    }
    _write_json(pointer_path, _to_builtin(pointer))
    protected_after = {name: _artifact_hashes(path) for name, path in protected_dirs.items()}
    if protected_before != protected_after:
        raise ValueError("finalization changed protected artifacts")
    manifest_path = run_dir / "m4_final_champion_manifest.json"
    manifest = {
        "schema_version": M4_FINAL_SCHEMA_VERSION,
        "accepted_m3_generation_id": accepted.generation_id,
        "protected_artifacts_sha256": protected_before,
        "bundle": {"path": str(bundle_path), "sha256": _sha256_path(bundle_path)},
        "pointer": {"path": str(pointer_path), "sha256": _sha256_path(pointer_path)},
        "model": {"path": str(model_path), "sha256": _sha256_path(model_path)},
        "input_hashes": bundle["input_artifact_hashes"],
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "xgboost": xgb.__version__,
        },
    }
    _write_json(manifest_path, _to_builtin(manifest))
    checksums_path = run_dir / "m4_final_champion_checksums.json"
    _write_json(
        checksums_path,
        _to_builtin(
            {
                "schema_version": M4_FINAL_SCHEMA_VERSION,
                "bundle": _sha256_path(bundle_path),
                "pointer": _sha256_path(pointer_path),
                "model": _sha256_path(model_path),
                "manifest": _sha256_path(manifest_path),
            }
        ),
    )
    return {
        "run_directory": str(run_dir),
        "champion_id": PHASE3C_CHAMPION_ID,
        "bundle_sha256": _sha256_path(bundle_path),
        "manifest_sha256": _sha256_path(manifest_path),
    }
