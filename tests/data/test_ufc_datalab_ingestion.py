from __future__ import annotations

import json
import shutil
from pathlib import Path

import polars as pl
from typer.testing import CliRunner

from ufc_predictor.cli import app
from ufc_predictor.ingestion.ufc_datalab import ingest_local_ufc_datalab_stats
from ufc_predictor.validation_support import content_sha256

FIXTURE = Path(__file__).parents[1] / "fixtures" / "ufc_datalab" / "stats_raw.csv"
OBSERVED_SCHEMA_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "ufc_datalab" / "stats_raw_observed_schema.csv"
)
COMMIT = "a" * 40


def _pinned_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "incoming" / "ufc-datalab" / COMMIT / "stats_raw.csv"
    path.parent.mkdir(parents=True)
    shutil.copy2(FIXTURE, path)
    return path


def test_local_datalab_ingestion_preserves_bytes_provenance_and_post_fight_facts(
    tmp_path: Path,
) -> None:
    input_file = _pinned_fixture(tmp_path)
    original = input_file.read_bytes()
    result = ingest_local_ufc_datalab_stats(
        input_file=input_file, raw_root=tmp_path / "raw", interim_root=tmp_path / "interim"
    )

    assert result.state == "published"
    assert input_file.read_bytes() == original
    assert result.parquet_path is not None and result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["commit_sha"] == COMMIT
    assert manifest["input_sha256"] == content_sha256(original)
    assert manifest["delimiter"] == ";"
    assert manifest["column_count"] == 11
    assert manifest["post_fight_statistics"] == "post_fight_fact_never_current_fight_feature"
    assert (tmp_path / "raw" / manifest["raw_reference"]["object_uri"]).read_bytes() == original
    frame = pl.read_parquet(result.parquet_path)
    assert frame["red_fighter_source_name"].to_list() == ["Alpha Fighter", "Gamma Fighter"]
    assert set(frame["detailed_statistics_temporal_status"].to_list()) == {"post_fight_fact"}


def test_local_datalab_ingestion_replays_and_quarantines_invalid_rows(tmp_path: Path) -> None:
    input_file = _pinned_fixture(tmp_path)
    kwargs = {
        "input_file": input_file,
        "raw_root": tmp_path / "raw",
        "interim_root": tmp_path / "interim",
    }
    first = ingest_local_ufc_datalab_stats(**kwargs)
    second = ingest_local_ufc_datalab_stats(**kwargs)
    assert first.replayed is False
    assert second.replayed is True
    assert first.ingestion_run_id == second.ingestion_run_id

    input_file.write_text(
        "date;red_fighter;blue_fighter;winner;no_of_rounds\n2024-01-01;A;B;Pending;3\n",
        encoding="utf-8",
    )
    failed = ingest_local_ufc_datalab_stats(**kwargs)
    assert failed.state == "quarantined"
    assert any("invalid_outcome" in issue for issue in failed.issues)


def test_datalab_cli_only_reads_an_explicit_local_file(tmp_path: Path) -> None:
    input_file = _pinned_fixture(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "ingest-ufc-datalab",
            "--input-file",
            str(input_file),
            "--raw-root",
            str(tmp_path / "raw"),
            "--interim-root",
            str(tmp_path / "interim"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["state"] == "published"


def test_local_datalab_ingestion_accepts_observed_raw_schema_and_day_first_dates(
    tmp_path: Path,
) -> None:
    input_file = _pinned_fixture(tmp_path)
    shutil.copy2(OBSERVED_SCHEMA_FIXTURE, input_file)

    result = ingest_local_ufc_datalab_stats(
        input_file=input_file, raw_root=tmp_path / "raw", interim_root=tmp_path / "interim"
    )

    assert result.state == "published"
    assert result.parquet_path is not None
    frame = pl.read_parquet(result.parquet_path)
    assert frame["fight_date"].to_list()[0].isoformat() == "2024-01-20"
    assert frame["scheduled_rounds"].to_list() == [3, 3]
    assert frame["outcome_source_value"].to_list() == ["red_win", "draw"]


def test_nonstandard_legacy_format_and_duplicate_candidate_are_published_for_review(
    tmp_path: Path,
) -> None:
    input_file = _pinned_fixture(tmp_path)
    input_file.write_text(
        "red_fighter_name;blue_fighter_name;event_date;fight_outcome;method;round;time_format\n"
        "Alpha;Beta;01/01/1995;red_win;Submission;1;No Time Limit\n"
        "Alpha;Beta;01/01/1995;no_contest;Overturned;1;No Time Limit\n",
        encoding="utf-8",
    )

    result = ingest_local_ufc_datalab_stats(
        input_file=input_file, raw_root=tmp_path / "raw", interim_root=tmp_path / "interim"
    )

    assert result.state == "published"
    assert "REV-011.duplicate_unordered_bout:row-3" in result.issues
