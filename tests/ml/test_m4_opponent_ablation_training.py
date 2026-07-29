from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl
import pytest

from ufc_predictor.training.m4_baselines import ACCEPTED_M3_GENERATION_ID, load_accepted_m3_data
from ufc_predictor.training.m4_opponent_ablation import (
    B1_CONTRACT_SHA256,
    B1_PAIRWISE_SHA256,
    B1_SNAPSHOTS_SHA256,
    PHASE3A_CONTROL_ID,
    feature_groups,
    feature_packs,
    run_m4_opponent_ablation_training,
)

ROOT = Path(__file__).parents[2]


def test_feature_groups_are_complete_unique_and_pack_membership_is_exact() -> None:
    accepted = load_accepted_m3_data(ROOT / "data/processed/m3-v6")
    groups = feature_groups()
    assigned = [feature for group in groups.values() for feature in group]
    assert len(assigned) == len(set(assigned)) == 37
    assert {name: len(group) for name, group in groups.items()} == {
        "overall_elo": 13,
        "weight_class_elo": 9,
        "career_opponent_quality": 3,
        "recent_opponent_quality": 6,
        "defeated_opponent_quality": 6,
    }
    packs = feature_packs(accepted.feature_columns)
    assert [len(pack.feature_columns) for pack in packs] == [130, 143, 152, 146, 149, 149, 158, 167]
    assert packs[0].feature_columns == accepted.feature_columns
    assert set(packs[-1].feature_columns[-37:]) == set(assigned)


def test_locked_b1_input_hashes_match_the_accepted_contract() -> None:
    directory = ROOT / "data/processed/m4-phase3b1-opponent-strength" / ACCEPTED_M3_GENERATION_ID
    assert (
        hashlib.sha256(
            (directory / "m4_phase3b1_fighter_rating_snapshots.parquet").read_bytes()
        ).hexdigest()
        == B1_SNAPSHOTS_SHA256
    )
    assert (
        hashlib.sha256(
            (directory / "m4_phase3b1_pairwise_opponent_strength.parquet").read_bytes()
        ).hexdigest()
        == B1_PAIRWISE_SHA256
    )
    assert (
        hashlib.sha256((directory / "m4_phase3b1_feature_contract.json").read_bytes()).hexdigest()
        == B1_CONTRACT_SHA256
    )


@pytest.fixture(scope="module")
def phase3b2_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("m4-phase3b2-output")
    run_m4_opponent_ablation_training(
        m3_root=ROOT / "data/processed/m3-v6",
        phase1_root=ROOT / "data/processed/m4-baselines",
        phase2_root=ROOT / "data/processed/m4-phase2-symmetry",
        phase3a_root=ROOT / "data/processed/m4-phase3a-xgboost",
        phase3b1_root=ROOT / "data/processed/m4-phase3b1-opponent-strength",
        output_root=root,
    )
    return root / ACCEPTED_M3_GENERATION_ID


def test_controls_folds_selection_and_protected_artifacts(phase3b2_output: Path) -> None:
    metrics = json.loads((phase3b2_output / "m4_phase3b2_metrics.json").read_text())
    manifest = json.loads((phase3b2_output / "m4_phase3b2_training_manifest.json").read_text())
    comparison = json.loads((phase3b2_output / "m4_phase3b2_model_comparison.json").read_text())
    b1_metrics = json.loads(
        (
            ROOT
            / "data/processed/m4-phase3b1-opponent-strength"
            / ACCEPTED_M3_GENERATION_ID
            / "m4_phase3b1_metrics.json"
        ).read_text()
    )
    assert len(metrics["candidate_aggregates"]) == 16
    assert metrics["candidate_aggregates"][PHASE3A_CONTROL_ID]["mean_log_loss"] == pytest.approx(
        b1_metrics["candidate_aggregates"]["base_130__phase3a_shallow_xgboost"]["mean_log_loss"]
    )
    assert metrics["candidate_aggregates"]["pack_h_full_phase3b1__phase3a_shallow_xgboost"][
        "mean_log_loss"
    ] == pytest.approx(
        b1_metrics["candidate_aggregates"]["base_plus_opponent_strength__phase3a_shallow_xgboost"][
            "mean_log_loss"
        ]
    )
    assert metrics["selection"]["benchmark_excluded"] is True
    assert comparison["selection_scope"] == "development_rolling_validation_only"
    assert comparison["champion_promoted"] is False
    assert comparison["mean_log_loss_delta_vs_phase3a"] > -comparison["champion_threshold"]
    predictions = pl.read_parquet(phase3b2_output / "m4_phase3b2_predictions.parquet")
    folds = pl.read_parquet(
        ROOT
        / "data/processed/m4-phase3a-xgboost"
        / ACCEPTED_M3_GENERATION_ID
        / "m4_phase3a_rolling_folds.parquet"
    )
    for fold_id in folds["fold_id"].unique().to_list():
        expected = set(
            folds.filter((pl.col("fold_id") == fold_id) & (pl.col("role") == "validation"))[
                "canonical_bout_id"
            ].to_list()
        )
        actual = set(
            predictions.filter(
                (pl.col("evaluation_partition") == "rolling_validation")
                & (pl.col("candidate_id") == PHASE3A_CONTROL_ID)
                & (pl.col("fold_id") == fold_id)
            )["canonical_bout_id"].to_list()
        )
        assert actual == expected
    assert (
        predictions.filter(pl.col("evaluation_partition") == "inspected_locked_benchmark")[
            "candidate_id"
        ].n_unique()
        == 1
    )
    for phase, root in {
        "phase1": ROOT / "data/processed/m4-baselines",
        "phase2": ROOT / "data/processed/m4-phase2-symmetry",
        "phase3a": ROOT / "data/processed/m4-phase3a-xgboost",
        "phase3b1": ROOT / "data/processed/m4-phase3b1-opponent-strength",
    }.items():
        for filename, digest in manifest["protected_artifacts_sha256"][phase].items():
            assert (
                hashlib.sha256(
                    (root / ACCEPTED_M3_GENERATION_ID / filename).read_bytes()
                ).hexdigest()
                == digest
            )


def test_phase3b2_replay_is_byte_deterministic(tmp_path: Path) -> None:
    kwargs = {
        "m3_root": ROOT / "data/processed/m3-v6",
        "phase1_root": ROOT / "data/processed/m4-baselines",
        "phase2_root": ROOT / "data/processed/m4-phase2-symmetry",
        "phase3a_root": ROOT / "data/processed/m4-phase3a-xgboost",
        "phase3b1_root": ROOT / "data/processed/m4-phase3b1-opponent-strength",
        "output_root": tmp_path / "replay",
    }
    run_m4_opponent_ablation_training(**kwargs)
    output = kwargs["output_root"] / ACCEPTED_M3_GENERATION_ID
    first = {path.name: path.read_bytes() for path in output.iterdir() if path.is_file()}
    run_m4_opponent_ablation_training(**kwargs)
    assert first == {path.name: path.read_bytes() for path in output.iterdir() if path.is_file()}
