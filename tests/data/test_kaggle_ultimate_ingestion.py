from __future__ import annotations

import json
import shutil
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from ufc_predictor.cli import app
from ufc_predictor.ingestion.kaggle_ultimate import (
    KAGGLE_ULTIMATE_UFC_DATASET_SCHEMA_VERSION,
    LeakageClassification,
    classify_leakage_column,
    ingest_local_kaggle_ultimate_dataset,
)
from ufc_predictor.ingestion.policies import (
    KAGGLE_ULTIMATE_UFC_DATASET_ATTRIBUTION,
    KAGGLE_ULTIMATE_UFC_DATASET_LICENSE,
    KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY,
    KAGGLE_ULTIMATE_UFC_DATASET_TERMS_VERSION,
    kaggle_ultimate_ufc_dataset_policy,
)
from ufc_predictor.ingestion.runner import IngestionRunState
from ufc_predictor.validation_support import content_sha256

FIXTURE = Path(__file__).parents[1] / "fixtures" / "kaggle_ultimate" / "ufc-master.csv"


def _incoming_fixture(tmp_path: Path) -> Path:
    incoming = tmp_path / "incoming" / "ultimate-ufc-dataset"
    incoming.mkdir(parents=True)
    shutil.copy2(FIXTURE, incoming / "ufc-master.csv")
    return incoming


@pytest.mark.anyio
async def test_local_kaggle_ingestion_preserves_raw_provenance_and_publishes_parquet(
    tmp_path: Path,
) -> None:
    incoming = _incoming_fixture(tmp_path)
    original_path = incoming / "ufc-master.csv"
    original_bytes = original_path.read_bytes()

    result = await ingest_local_kaggle_ultimate_dataset(
        incoming_directory=incoming,
        raw_root=tmp_path / "raw",
        interim_root=tmp_path / "interim",
    )

    assert result.execution.run.state is IngestionRunState.PUBLISHED
    assert result.replayed is False
    assert result.parquet_path is not None
    assert result.manifest_path is not None
    assert original_path.read_bytes() == original_bytes
    assert result.execution.run.accounting is not None
    assert result.execution.run.accounting.accepted_count == 2

    raw_reference = result.execution.raw_references[0]
    assert raw_reference.sha256 == content_sha256(original_bytes)
    assert (tmp_path / "raw" / raw_reference.object_uri).read_bytes() == original_bytes
    raw_manifest = json.loads(
        (tmp_path / "raw" / raw_reference.retrieval_manifest_uri).read_text(encoding="utf-8")
    )
    assert raw_manifest["source_key"] == KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY
    assert raw_manifest["dataset_license"] == KAGGLE_ULTIMATE_UFC_DATASET_LICENSE
    assert raw_manifest["terms_policy_version"] == KAGGLE_ULTIMATE_UFC_DATASET_TERMS_VERSION
    assert raw_manifest["attribution"] == KAGGLE_ULTIMATE_UFC_DATASET_ATTRIBUTION
    assert raw_manifest["original_filename"] == "ufc-master.csv"
    assert raw_manifest["source_schema_version"] == KAGGLE_ULTIMATE_UFC_DATASET_SCHEMA_VERSION
    assert raw_manifest["ingestion_run_id"] == result.execution.run.run_id
    assert raw_manifest["sha256"] == content_sha256(original_bytes)
    assert raw_manifest["requested_at"].endswith("+00:00")
    assert raw_manifest["retrieved_at"].endswith("+00:00")

    frame = pl.read_parquet(result.parquet_path)
    assert frame.height == 2
    assert {
        "Winner",
        "finish",
        "finish_round",
        "R_avg_SIG_STR_landed",
        "R_fighter",
        "B_fighter",
    }.isdisjoint(frame.columns)
    assert frame["quarantined_column_names"].to_list()[0] == [
        "B_current_win_streak",
        "B_fighter",
        "R_avg_SIG_STR_landed",
        "R_fighter",
        "R_wins",
        "Winner",
        "finish",
        "finish_round",
    ]
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["ingestion_run_id"] == result.execution.run.run_id
    assert manifest["dataset_license"] == KAGGLE_ULTIMATE_UFC_DATASET_LICENSE
    assert manifest["raw_references"][0]["sha256"] == raw_reference.sha256


@pytest.mark.anyio
async def test_local_kaggle_ingestion_is_idempotent_for_unchanged_input(tmp_path: Path) -> None:
    incoming = _incoming_fixture(tmp_path)
    kwargs = {
        "incoming_directory": incoming,
        "raw_root": tmp_path / "raw",
        "interim_root": tmp_path / "interim",
    }

    first = await ingest_local_kaggle_ultimate_dataset(**kwargs)
    second = await ingest_local_kaggle_ultimate_dataset(**kwargs)

    assert first.replayed is False
    assert second.replayed is True
    assert second.execution.run.run_id == first.execution.run.run_id
    assert second.parquet_path == first.parquet_path
    assert len(list((tmp_path / "raw" / "retrievals").rglob("*.json"))) == 1


@pytest.mark.anyio
async def test_duplicate_fights_quarantine_the_run_after_raw_preservation(tmp_path: Path) -> None:
    incoming = _incoming_fixture(tmp_path)
    input_path = incoming / "ufc-master.csv"
    lines = input_path.read_text(encoding="utf-8").splitlines()
    input_path.write_text("\n".join([*lines, lines[1]]) + "\n", encoding="utf-8")

    result = await ingest_local_kaggle_ultimate_dataset(
        incoming_directory=incoming,
        raw_root=tmp_path / "raw",
        interim_root=tmp_path / "interim",
    )

    assert result.execution.run.state is IngestionRunState.QUARANTINED
    assert result.parquet_path is None
    assert result.execution.run.accounting is not None
    assert result.execution.run.accounting.quarantined_count == 1
    assert (tmp_path / "raw" / result.execution.raw_references[0].object_uri).is_file()


@pytest.mark.anyio
async def test_schema_failure_preserves_raw_file_and_blocks_parquet(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming" / "ultimate-ufc-dataset"
    incoming.mkdir(parents=True)
    input_path = incoming / "ufc-master.csv"
    original = b"R_fighter,B_fighter,date,no_of_rounds\nAlpha,Beta,2024-01-20,3\n"
    input_path.write_bytes(original)

    result = await ingest_local_kaggle_ultimate_dataset(
        incoming_directory=incoming,
        raw_root=tmp_path / "raw",
        interim_root=tmp_path / "interim",
    )

    assert result.execution.run.state is IngestionRunState.QUARANTINED
    assert result.parquet_path is None
    assert input_path.read_bytes() == original
    raw_reference = result.execution.raw_references[0]
    assert raw_reference.sha256 == content_sha256(original)
    assert (tmp_path / "raw" / raw_reference.object_uri).read_bytes() == original


@pytest.mark.anyio
async def test_invalid_date_and_result_quarantine_after_raw_preservation(tmp_path: Path) -> None:
    incoming = _incoming_fixture(tmp_path)
    input_path = incoming / "ufc-master.csv"
    input_path.write_text(
        input_path.read_text(encoding="utf-8").replace("2024-01-20,Red", "not-a-date,Pending"),
        encoding="utf-8",
    )

    result = await ingest_local_kaggle_ultimate_dataset(
        incoming_directory=incoming,
        raw_root=tmp_path / "raw",
        interim_root=tmp_path / "interim",
    )

    assert result.execution.run.state is IngestionRunState.QUARANTINED
    assert result.execution.run.accounting is not None
    assert result.execution.run.accounting.quarantined_count == 1
    report = result.execution.run.report
    assert report is not None
    rule_ids = {issue.rule_id for issue in report.issues}
    assert {"DAT-004.invalid_fight_date", "DAT-004.invalid_result"} <= rule_ids
    assert (tmp_path / "raw" / result.execution.raw_references[0].object_uri).is_file()


def test_leakage_column_classification_quarantines_outcome_and_unverified_fields() -> None:
    assert classify_leakage_column("Winner") is LeakageClassification.OUTCOME
    assert classify_leakage_column("finish_round") is LeakageClassification.OUTCOME
    assert (
        classify_leakage_column("R_avg_SIG_STR_landed") is LeakageClassification.UNVERIFIED_TEMPORAL
    )
    assert (
        classify_leakage_column("B_current_win_streak") is LeakageClassification.UNVERIFIED_TEMPORAL
    )
    assert classify_leakage_column("R_wins") is LeakageClassification.UNVERIFIED_TEMPORAL
    assert classify_leakage_column("R_odds") is LeakageClassification.MARKET
    assert classify_leakage_column("R_fighter") is LeakageClassification.SOURCE_ORDERING
    assert classify_leakage_column("date") is LeakageClassification.SAFE_CONTEXT


def test_kaggle_source_policy_records_license_and_attribution() -> None:
    policy = kaggle_ultimate_ufc_dataset_policy()

    assert policy.enabled is True
    assert policy.source_key == KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY
    assert policy.dataset_license == KAGGLE_ULTIMATE_UFC_DATASET_LICENSE
    assert policy.terms_policy_version == KAGGLE_ULTIMATE_UFC_DATASET_TERMS_VERSION
    assert policy.attribution == KAGGLE_ULTIMATE_UFC_DATASET_ATTRIBUTION


def test_kaggle_local_ingestion_cli(tmp_path: Path) -> None:
    incoming = _incoming_fixture(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "ingest-kaggle-ultimate",
            "--incoming-directory",
            str(incoming),
            "--raw-root",
            str(tmp_path / "raw"),
            "--interim-root",
            str(tmp_path / "interim"),
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["state"] == "published"
    assert summary["replayed"] is False
