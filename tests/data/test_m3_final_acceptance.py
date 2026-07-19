from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import polars as pl
import pytest

from ufc_predictor.m3_materialization import (
    _PUBLISHED_ARTIFACTS,
    _model_ready_feature_columns,
    materialize_m3_v6,
    resolve_m3_current_generation,
)

ROOT = Path(__file__).parents[2]
ULTIMATE = ROOT / "data/incoming/ultimate-ufc-dataset/ufc-master.csv"
DATALAB = ROOT / "data/incoming/ufc-datalab/3268146c05211de9deab8b9b4c0bb4a954815f0b/stats_raw.csv"
V6_DIR = ROOT / "data/quarantine/reviews/m3-corrections-v6"


@pytest.fixture(scope="module")
def generation(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("m3-final-acceptance")
    materialize_m3_v6(
        ultimate_csv=ULTIMATE,
        datalab_csv=DATALAB,
        v6_dir=V6_DIR,
        output_dir=output,
    )
    return resolve_m3_current_generation(output)


def test_final_acceptance_report_is_complete_artifact_derived_and_canonical(
    generation: Path,
) -> None:
    report_path = generation / "m3_final_acceptance_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads((generation / "m3_phase2_manifest.json").read_text(encoding="utf-8"))
    assert report_path.read_bytes() == (
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    serialized = report_path.read_text(encoding="utf-8")
    assert "D:\\" not in serialized and "C:\\" not in serialized
    assert report["generation_id"] == manifest["generation_id"]
    assert report["validation_status"] == "passed"

    expected_artifacts = {name for name, _ in _PUBLISHED_ARTIFACTS} | {
        "m3_normalized_provenance.parquet"
    }
    inventory = report["artifact_inventory"]
    assert set(inventory) == expected_artifacts == set(manifest["artifacts"])
    for name, metadata in inventory.items():
        path = generation / name
        frame = pl.read_parquet(path)
        assert metadata == manifest["artifacts"][name]
        assert metadata["path"] == name
        assert metadata["row_count"] == frame.height
        assert metadata["column_count"] == frame.width
        assert metadata["sha256"] == sha256(path.read_bytes()).hexdigest()

    rows = report["cardinalities"]["artifact_rows"]
    assert (
        rows["m3_canonical_historical_bouts.parquet"]
        == rows["m3_bout_reconciliation.parquet"]
        == 9068
    )
    assert rows["m3_canonical_fighters.parquet"] == 2790
    assert report["cardinalities"]["provenance_denominator"] == 150162
    assert report["provenance"] == manifest["provenance"]
    assert report["provenance"]["unique_covered_rows"] == 150162
    assert report["provenance"]["coverage_percentage"] == 100

    for source in report["raw_sources"]:
        source_path = ROOT / source["path"]
        assert source_path.is_file()
        assert source["sha256"] == sha256(source_path.read_bytes()).hexdigest()
    for ledger in report["authority_ledgers"]:
        ledger_path = ROOT / ledger["path"]
        assert ledger_path.is_file()
        assert ledger["sha256"] == sha256(ledger_path.read_bytes()).hexdigest()
        assert ledger["record_count"] == len(ledger_path.read_text(encoding="utf-8").splitlines())
    assert (
        report["authority_resolution"]["numerator"] == report["authority_resolution"]["denominator"]
    )

    pairwise = pl.read_parquet(generation / "m3_prefight_pairwise_features.parquet")
    model = pl.read_parquet(generation / "m3_model_ready_binary.parquet")
    model_report = report["model_ready"]
    assert model_report["row_count"] == model.height == 8912
    assert model_report["column_count"] == model.width == 138
    assert model_report["feature_columns"] == _model_ready_feature_columns()
    assert model_report["feature_count"] == 130
    assert (
        model_report["positive_target_count"]
        == model.filter(pl.col("target_fighter_a_won") == 1).height
        == 4610
    )
    assert (
        model_report["negative_target_count"]
        == model.filter(pl.col("target_fighter_a_won") == 0).height
        == 4302
    )
    assert (
        pairwise.height
        - model_report["excluded_draw_count"]
        - model_report["excluded_no_contest_count"]
        == model.height
    )
    assert model_report["excluded_draw_count"] == 65
    assert model_report["excluded_no_contest_count"] == 91
    assert set(model["target_fighter_a_won"].to_list()) == {0, 1}

    assert report["audit"] == {
        "invalid_model_float_count": 0,
        "missingness_mismatch_count": 0,
        "provenance_orphan_count": 0,
        "target_null_count": 0,
        "unresolved_conflict_count": 0,
    }
    assert report["verification_contract"]["atomic_publication_failure_injections"] == [
        "after_staging_before_validation",
        "after_validation_before_commit",
        "during_publication_before_pointer",
    ]
