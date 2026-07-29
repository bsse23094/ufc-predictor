"""Read-only M5 runtime for the immutable M4 champion bundle.

The runtime deliberately resolves only rows already materialized by M3/M4 with
strict pre-fight cutoffs.  It does not attempt to invent a feature value, and
never reads the target label from the M3 model-ready artifact.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import joblib
import numpy as np
import pandas as pd
import polars as pl

from ufc_predictor.m3_materialization import (
    _pairwise_rows,
    _prefight_fighter_history_rows,
    _prefight_performance_rows,
)
from ufc_predictor.training.m4_opponent_adjusted_performance import (
    build_opponent_adjusted_snapshots,
    build_pairwise_opponent_adjusted,
)
from ufc_predictor.training.m4_opponent_strength import (
    build_pairwise_opponent_strength,
    build_prefight_opponent_strength,
    load_weight_classes_from_m3_provenance,
)

M5_SCHEMA_VERSION = "m5.champion_inference.v1"
EXPECTED_BUNDLE_SHA256 = "3ae750dddc4ffa740a4e0172ee4bad5a460e088703556d2edfec4a4b1bf379fe"
DEFAULT_BUNDLE_PATH = Path(
    "data/processed/m4-final-champion/m3-74eeb9b7f49b5adca45e461a/m4_final_champion_bundle.json"
)
DEFAULT_OUTPUT_ROOT = Path("data/processed/m5-phase2-runtime-materialization")


class ChampionRuntimeError(RuntimeError):
    """Fail-closed error for an invalid immutable runtime contract."""


class FeatureMaterializationUnavailable(ValueError):
    """No accepted, prediction-safe pre-fight vector exists for a request."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _stable_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True, slots=True)
class ChampionPrediction:
    """One symmetric champion probability and its input-quality indicators."""

    fighter_a_id: str
    fighter_b_id: str
    probability_a: float
    probability_b: float
    predicted_winner_id: str | None
    confidence: dict[str, dict[str, bool | float]]
    insufficient_history_indicators: tuple[str, ...]
    feature_source: str
    history_cutoff_date: str
    fighter_history_counts: dict[str, int]


class ChampionRuntime:
    """Validated model plus a read-only accepted pre-fight feature resolver."""

    def __init__(self, bundle_path: Path = DEFAULT_BUNDLE_PATH) -> None:
        self.bundle_path = bundle_path
        self.bundle_hash = _sha256(bundle_path) if bundle_path.is_file() else ""
        if self.bundle_hash != EXPECTED_BUNDLE_SHA256:
            raise ChampionRuntimeError("champion bundle hash validation failed")
        self.bundle = _read_json(bundle_path)
        self._validate_contract()
        self.model = self._load_model()
        self._rows, self._fighters = self._load_prediction_safe_rows()
        self._load_runtime_indexes()

    @property
    def feature_columns(self) -> tuple[str, ...]:
        return tuple(cast(list[str], self.bundle["feature_contract"]["ordered_feature_columns"]))

    def _validate_contract(self) -> None:
        if self.bundle.get("schema_version") != "m4.final_champion_registry.v1":
            raise ChampionRuntimeError("champion bundle schema is not accepted")
        contract = cast(dict[str, Any], self.bundle.get("feature_contract", {}))
        features = cast(list[str], contract.get("ordered_feature_columns", []))
        if len(features) != 167 or len(features) != len(set(features)):
            raise ChampionRuntimeError("ordered champion feature contract is invalid")
        if int(contract.get("feature_count", -1)) != len(features):
            raise ChampionRuntimeError("champion feature count does not match contract")
        inference = cast(dict[str, Any], self.bundle.get("inference_contract", {}))
        registry = cast(list[dict[str, str]], inference.get("fighter_corner_swap_registry", []))
        if len(registry) != len(features) or [item.get("feature") for item in registry] != features:
            raise ChampionRuntimeError("fighter-corner swap contract differs from feature contract")
        if not bool(inference.get("symmetrized_inference_required")):
            raise ChampionRuntimeError("champion bundle does not require symmetric inference")

    def _load_model(self) -> Any:
        model_meta = cast(dict[str, str], self.bundle["model"])
        model_path = self.bundle_path.parent / model_meta["filename"]
        if not model_path.is_file() or _sha256(model_path) != model_meta["sha256"]:
            raise ChampionRuntimeError("champion model hash validation failed")
        try:
            model = joblib.load(model_path)
        except Exception as exc:  # pragma: no cover - library-specific corrupt-file failures
            raise ChampionRuntimeError("champion model could not be loaded") from exc
        if not hasattr(model, "predict_proba") or getattr(model, "n_features_in_", 167) != 167:
            raise ChampionRuntimeError("champion model contract is invalid")
        return model

    def _load_prediction_safe_rows(
        self,
    ) -> tuple[dict[tuple[str, str, str, str], dict[str, Any]], set[str]]:
        generation = str(self.bundle["accepted_m3_generation_id"])
        root = self.bundle_path.parents[4]
        m3_dir = root / "data/processed/m3-v6/.m3-generations" / generation
        phase3b_dir = root / "data/processed/m4-phase3b1-opponent-strength" / generation
        phase3c_dir = root / "data/processed/m4-phase3c-opponent-adjusted-performance" / generation
        required = {
            "m3": m3_dir / "m3_model_ready_binary.parquet",
            "m3_acceptance": m3_dir / "m3_final_acceptance_report.json",
            "elo": phase3b_dir / "m4_phase3b1_pairwise_opponent_strength.parquet",
            "adjusted": phase3c_dir / "m4_phase3c_pairwise_opponent_adjusted_performance.parquet",
            "phase3c_manifest": phase3c_dir / "m4_phase3c_training_manifest.json",
        }
        if any(not path.is_file() for path in required.values()):
            raise ChampionRuntimeError("required accepted pre-fight materialization is unavailable")
        acceptance = _read_json(required["m3_acceptance"])
        m3_hash = _sha256(required["m3"])
        if acceptance["artifact_inventory"]["m3_model_ready_binary.parquet"]["sha256"] != m3_hash:
            raise ChampionRuntimeError("accepted M3 feature source hash validation failed")
        if (
            _sha256(required["phase3c_manifest"])
            != self.bundle["input_artifact_hashes"]["phase3c_manifest"]
        ):
            raise ChampionRuntimeError("accepted Phase 3C manifest hash validation failed")
        manifest = _read_json(required["phase3c_manifest"])
        checksums = cast(dict[str, str], manifest["output_checksums"])
        if checksums.get("pairwise_features") != _sha256(required["adjusted"]):
            raise ChampionRuntimeError("accepted Phase 3C adjusted feature hash validation failed")

        features = list(self.feature_columns)
        base = pl.read_parquet(required["m3"]).select(
            ["canonical_bout_id", "fight_date", "canonical_fighter_a_id", "canonical_fighter_b_id"]
            + [name for name in features if name in pl.read_parquet_schema(required["m3"])]
        )
        # The feature list is intentionally selected explicitly; target_fighter_a_won is never read.
        base_names = set(base.columns)
        elo = pl.read_parquet(required["elo"])
        adjusted = pl.read_parquet(required["adjusted"])
        keys = [
            "canonical_bout_id",
            "fight_date",
            "canonical_fighter_a_id",
            "canonical_fighter_b_id",
        ]
        additions = [name for name in features if name not in base_names]
        available = set(elo.columns) | set(adjusted.columns)
        if set(additions) - available:
            raise ChampionRuntimeError("accepted feature materialization does not satisfy contract")
        elo_columns = keys + [name for name in additions if name in elo.columns]
        adjusted_columns = keys + [name for name in additions if name in adjusted.columns]
        # M3 stores a date while the derived M4 tables retain a midnight timestamp.
        elo = elo.with_columns(pl.col("fight_date").cast(pl.Date))
        adjusted = adjusted.with_columns(pl.col("fight_date").cast(pl.Date))
        joined = base.join(elo.select(elo_columns), on=keys, how="left").join(
            adjusted.select(adjusted_columns), on=keys, how="left"
        )
        if joined.height != base.height or any(name not in joined.columns for name in features):
            raise ChampionRuntimeError("joined pre-fight feature materialization is incomplete")
        rows: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        fighters: set[str] = set()
        for row in joined.select(keys + features).to_dicts():
            key = (
                str(row["fight_date"]),
                str(row["canonical_fighter_a_id"]),
                str(row["canonical_fighter_b_id"]),
                str(row["canonical_bout_id"]),
            )
            rows[key] = row
            fighters.update((key[1], key[2]))
        return rows, fighters

    def _load_runtime_indexes(self) -> None:
        """Read immutable sources once; request handling never reopens Parquet."""
        generation = str(self.bundle["accepted_m3_generation_id"])
        root = self.bundle_path.parents[4]
        m3_dir = root / "data/processed/m3-v6/.m3-generations" / generation
        historical_path = m3_dir / "m3_canonical_historical_bouts.parquet"
        performance_path = m3_dir / "m3_fighter_bout_performance.parquet"
        if not historical_path.is_file() or not performance_path.is_file():
            raise ChampionRuntimeError("accepted historical source is unavailable")
        self._historical = pl.read_parquet(historical_path)
        self._performance = pl.read_parquet(performance_path)
        self._weight_classes, _ = load_weight_classes_from_m3_provenance(m3_dir)

    def _runtime_vector(
        self, fighter_a_id: str, fighter_b_id: str, target_date: date
    ) -> dict[str, Any]:
        """Rebuild the exact M3/3B1/3C vector with a no-outcome synthetic target.

        The cached tables are deliberately replayed through the accepted feature
        builders.  Their strict-date batch semantics exclude every same-date row.
        """
        target_id = f"runtime-as-of:{target_date.isoformat()}:{fighter_a_id}:{fighter_b_id}"
        historical_row: dict[str, Any] = {name: None for name in self._historical.columns}
        historical_row.update(
            {
                "canonical_bout_id": target_id,
                "fight_date": target_date,
                "canonical_fighter_a_id": fighter_a_id,
                "canonical_fighter_b_id": fighter_b_id,
                "is_no_contest": True,
                "is_draw": False,
                "winner_canonical_fighter_id": None,
                "canonical_finish_method": None,
            }
        )
        historical = self._historical.vstack(
            pl.DataFrame([historical_row], schema=self._historical.schema)
        )
        performance_rows: list[dict[str, Any]] = []
        for fighter, opponent, slot in (
            (fighter_a_id, fighter_b_id, "canonical_fighter_a"),
            (fighter_b_id, fighter_a_id, "canonical_fighter_b"),
        ):
            row: dict[str, Any] = {name: None for name in self._performance.columns}
            row.update(
                {
                    "canonical_bout_id": target_id,
                    "canonical_fighter_id": fighter,
                    "opponent_canonical_fighter_id": opponent,
                    "fight_date": target_date,
                    "fighter_slot": slot,
                }
            )
            for name in self._performance.columns:
                if name.endswith("_available"):
                    row[name] = False
            performance_rows.append(row)
        performance = self._performance.vstack(
            pl.DataFrame(performance_rows, schema=self._performance.schema)
        )
        prefight = pl.DataFrame(_prefight_fighter_history_rows(historical))
        prefight_performance = pl.DataFrame(_prefight_performance_rows(performance, historical))
        target_historical = historical.filter(pl.col("canonical_bout_id") == target_id)
        target_prefight = prefight.filter(pl.col("canonical_bout_id") == target_id)
        target_performance = prefight_performance.filter(pl.col("canonical_bout_id") == target_id)
        base = _pairwise_rows(target_historical, target_prefight, target_performance)[0]
        snapshots = build_prefight_opponent_strength(
            pd.DataFrame(historical.to_dicts()), weight_classes=self._weight_classes
        )
        target_model = pd.DataFrame([base])
        elo = build_pairwise_opponent_strength(snapshots, target_model).iloc[0].to_dict()
        adjusted_snapshots = build_opponent_adjusted_snapshots(
            pd.DataFrame(performance.to_dicts()), pd.DataFrame(prefight_performance.to_dicts())
        )
        adjusted = (
            build_pairwise_opponent_adjusted(adjusted_snapshots, target_model).iloc[0].to_dict()
        )
        values = {**base, **elo, **adjusted}
        if any(name not in values for name in self.feature_columns):
            raise ChampionRuntimeError("runtime feature materialization is incomplete")
        return {
            name: None if pd.isna(values[name]) else values[name] for name in self.feature_columns
        }

    def _swap_vector(self, vector: dict[str, Any]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        registry = cast(
            list[dict[str, str]], self.bundle["inference_contract"]["fighter_corner_swap_registry"]
        )
        for item in registry:
            feature, peer, transform = item["feature"], item["swap_feature"], item["transform"]
            value = vector[peer]
            if transform == "negate":
                output[feature] = -value if value is not None else None
            elif transform == "complement":
                output[feature] = 1.0 - value if value is not None else None
            elif transform == "exchange":
                output[feature] = value
            else:  # pragma: no cover - protected bundle validation makes this unreachable
                raise ChampionRuntimeError("unknown corner-swap transform")
        return output

    def _resolve_vector(
        self, fighter_a_id: str, fighter_b_id: str, fight_date: date
    ) -> tuple[dict[str, Any], str]:
        if fighter_a_id == fighter_b_id:
            raise FeatureMaterializationUnavailable("fighter IDs must be different")
        if fighter_a_id not in self._fighters or fighter_b_id not in self._fighters:
            raise FeatureMaterializationUnavailable("canonical fighter ID is not available")
        target = fight_date.isoformat()
        matches = [
            row
            for (row_date, a_id, b_id, _), row in self._rows.items()
            if row_date == target and a_id == fighter_a_id and b_id == fighter_b_id
        ]
        if matches:
            return {name: matches[0][name] for name in self.feature_columns}, "historical_exact_row"
        reverse = [
            row
            for (row_date, a_id, b_id, _), row in self._rows.items()
            if row_date == target and a_id == fighter_b_id and b_id == fighter_a_id
        ]
        if reverse:
            return self._swap_vector(
                {name: reverse[0][name] for name in self.feature_columns}
            ), "historical_exact_row"
        return self._runtime_vector(fighter_a_id, fighter_b_id, fight_date), "runtime_as_of_date"

    def predict(self, fighter_a_id: str, fighter_b_id: str, fight_date: date) -> ChampionPrediction:
        vector, feature_source = self._resolve_vector(fighter_a_id, fighter_b_id, fight_date)
        frame = pd.DataFrame(
            [[vector[name] for name in self.feature_columns]], columns=self.feature_columns
        )
        forward = float(self.model.predict_proba(frame.astype(float))[:, 1][0])
        swapped_vector = self._swap_vector(vector)
        swapped_frame = pd.DataFrame(
            [[swapped_vector[name] for name in self.feature_columns]], columns=self.feature_columns
        )
        swapped = float(self.model.predict_proba(swapped_frame.astype(float))[:, 1][0])
        probability_a = float(0.5 * (forward + (1.0 - swapped)))
        if not 0.0 <= probability_a <= 1.0:
            raise ChampionRuntimeError("symmetric probability is outside bounds")
        probability_b = float(1.0 - probability_a)
        points = cast(dict[str, float], self.bundle["confidence_operating_points"]["recommended"])
        confidence = {
            name: {"margin": margin, "covered": abs(probability_a - 0.5) >= margin}
            for name, margin in points.items()
        }
        indicators = tuple(
            name
            for name in self.feature_columns
            if name.endswith("_missing") and bool(vector[name])
        )
        if probability_a > 0.5:
            winner = fighter_a_id
        elif probability_a < 0.5:
            winner = fighter_b_id
        else:
            winner = None
        return ChampionPrediction(
            fighter_a_id=fighter_a_id,
            fighter_b_id=fighter_b_id,
            probability_a=probability_a,
            probability_b=probability_b,
            predicted_winner_id=winner,
            confidence=confidence,
            insufficient_history_indicators=indicators,
            feature_source=feature_source,
            history_cutoff_date=fight_date.isoformat(),
            fighter_history_counts={
                "fighter_a_prior_bouts": int(vector["a_prior_bouts"]),
                "fighter_b_prior_bouts": int(vector["b_prior_bouts"]),
            },
        )

    def runtime_contract(self) -> dict[str, object]:
        return {
            "schema_version": M5_SCHEMA_VERSION,
            "bundle_sha256": self.bundle_hash,
            "champion_id": self.bundle["champion_id"],
            "feature_schema_version": self.bundle["feature_contract"]["feature_schema_version"],
            "ordered_feature_columns": list(self.feature_columns),
            "missing_value_policy": self.bundle["feature_contract"][
                "preprocessing_and_missing_value_policy"
            ],
            "symmetrized_inference": self.bundle["inference_contract"]["probability_policy"],
            "confidence_operating_points": self.bundle["confidence_operating_points"][
                "recommended"
            ],
            "feature_resolution": (
                "accepted historical data replayed strictly before the target date; "
                "same-date and later fights are excluded"
            ),
        }


def write_m5_runtime_artifacts(
    runtime: ChampionRuntime, output_root: Path = DEFAULT_OUTPUT_ROOT
) -> dict[str, str]:
    """Persist the M5 contract and manifest without copying mutable model state."""

    generation = str(runtime.bundle["accepted_m3_generation_id"])
    output_dir = output_root / generation
    output_dir.mkdir(parents=True, exist_ok=True)
    contract_path = output_dir / "m5_champion_runtime_contract.json"
    _stable_json(contract_path, runtime.runtime_contract())
    manifest_path = output_dir / "m5_champion_service_manifest.json"
    report_path = output_dir / "m5_phase2_exhaustive_parity_report.json"
    manifest = {
        "schema_version": M5_SCHEMA_VERSION,
        "runtime_contract": {"path": contract_path.name, "sha256": _sha256(contract_path)},
        "immutable_champion_bundle": {
            "path": runtime.bundle_path.name,
            "sha256": runtime.bundle_hash,
        },
        "model_sha256": runtime.bundle["model"]["sha256"],
        "mutable_training_state_copied": False,
    }
    if report_path.is_file():
        manifest["exhaustive_parity_report"] = {
            "path": report_path.name,
            "sha256": _sha256(report_path),
        }
    _stable_json(manifest_path, manifest)
    return {"runtime_contract": _sha256(contract_path), "manifest": _sha256(manifest_path)}


def run_m5_phase2_exhaustive_parity(
    runtime: ChampionRuntime | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    tolerance: float = 1e-6,
) -> dict[str, object]:
    """Exhaustively verify the historical-exact M5 route against all Phase 3C rows."""

    active = runtime or ChampionRuntime()
    names = list(active.feature_columns)
    rows = list(active._rows.values())
    ordered_mismatches = null_mismatches = numeric_mismatches = 0
    maximum_numeric_difference = 0.0
    grouped: dict[str, int] = {}
    vectors: list[dict[str, Any]] = []
    for row in rows:
        vector, source = active._resolve_vector(
            str(row["canonical_fighter_a_id"]),
            str(row["canonical_fighter_b_id"]),
            row["fight_date"],
        )
        if source != "historical_exact_row" or list(vector) != names:
            ordered_mismatches += 1
        vectors.append(vector)
        for name in names:
            expected, actual = row[name], vector.get(name)
            if (expected is None) != (actual is None):
                null_mismatches += 1
                grouped[name] = grouped.get(name, 0) + 1
            elif expected is not None:
                assert actual is not None
                difference = abs(float(expected) - float(actual))
                maximum_numeric_difference = max(maximum_numeric_difference, difference)
                if difference > tolerance:
                    numeric_mismatches += 1
                    grouped[name] = grouped.get(name, 0) + 1
    matrix = pd.DataFrame(
        [[item[name] for name in names] for item in vectors], columns=names
    ).astype(float)
    swapped = pd.DataFrame(
        [[active._swap_vector(item)[name] for name in names] for item in vectors], columns=names
    ).astype(float)
    forward = active.model.predict_proba(matrix)[:, 1]
    reverse = active.model.predict_proba(swapped)[:, 1]
    probabilities = 0.5 * (forward + (1.0 - reverse))
    swapped_probabilities = 0.5 * (reverse + (1.0 - forward))
    probability_differences = np.abs(probabilities - (1.0 - swapped_probabilities))
    maximum_probability_difference = float(probability_differences.max())
    probability_mismatches = int((probability_differences > tolerance).sum())
    report: dict[str, object] = {
        "schema_version": "m5.phase2.exhaustive_parity.v1",
        "tolerance": tolerance,
        "rows_checked": len(rows),
        "feature_cells_checked": len(rows) * len(names),
        "ordered_feature_mismatches": ordered_mismatches,
        "null_placement_mismatches": null_mismatches,
        "numeric_mismatches": numeric_mismatches,
        "maximum_numeric_difference": maximum_numeric_difference,
        "probability_mismatches": probability_mismatches,
        "maximum_probability_difference": maximum_probability_difference,
        "mismatches_by_feature": grouped,
        "bundle_sha256": active.bundle_hash,
    }
    if any((ordered_mismatches, null_mismatches, numeric_mismatches, probability_mismatches)):
        raise ChampionRuntimeError("exhaustive Phase 2 parity verification failed")
    directory = output_root / str(active.bundle["accepted_m3_generation_id"])
    directory.mkdir(parents=True, exist_ok=True)
    _stable_json(directory / "m5_phase2_exhaustive_parity_report.json", report)
    write_m5_runtime_artifacts(active, output_root)
    return report
