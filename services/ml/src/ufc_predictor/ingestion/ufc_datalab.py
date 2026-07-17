"""Local-only, pinned UFC-DataLab ``stats_raw.csv`` ingestion.

Acquisition and ingestion are deliberately separate operations. This adapter
accepts a byte-for-byte local copy from a commit-named incoming directory and
never imports a Git, HTTP, or scraping client. Detailed statistics remain
explicit post-fight facts in this source-shaped output; they are not features.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import polars as pl

from ufc_predictor.ingestion.policies import (
    UFC_DATALAB_ATTRIBUTION,
    UFC_DATALAB_LICENSE,
    UFC_DATALAB_REPOSITORY_URL,
    UFC_DATALAB_SOURCE_KEY,
    UFC_DATALAB_TERMS_VERSION,
)
from ufc_predictor.ingestion.raw_store import LocalRawStore, RawWriteRequest
from ufc_predictor.validation_support import content_sha256

UFC_DATALAB_RAW_FILENAME = "stats_raw.csv"
UFC_DATALAB_SCHEMA_VERSION = "stats-raw-semicolon-v1"
UFC_DATALAB_PARSER_VERSION = "ufc-datalab-local-v3"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_OUTCOMES = frozenset(
    {"red", "blue", "red_win", "blue_win", "draw", "nc", "no contest", "no_contest"}
)
_HEADER_ALIASES = {
    "fight_date": ("date", "fight_date", "event_date"),
    "red_fighter": ("red_fighter", "red_fighter_name", "r_fighter", "red", "red fighter"),
    "blue_fighter": ("blue_fighter", "blue_fighter_name", "b_fighter", "blue", "blue fighter"),
    "outcome": ("winner", "fight_outcome", "result", "outcome"),
    "scheduled_rounds": ("no_of_rounds", "scheduled_rounds", "rounds", "time_format"),
    "finish_round": ("finish_round", "round", "ending_round"),
    "method": ("method", "finish", "result_method"),
    "event_name": ("event", "event_name"),
    "division": ("weight_class", "division", "bout_type"),
    "location": ("location", "event_location"),
}


@dataclass(frozen=True, slots=True)
class UfcDataLabIngestionResult:
    """A fully accounted immutable local ingestion result."""

    ingestion_run_id: str
    state: str
    replayed: bool
    parquet_path: Path | None
    manifest_path: Path | None
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UfcDataLabManifest:
    """Provenance plus parsing facts for an immutable normalised projection."""

    source_identifier: str
    repository_url: str
    commit_sha: str
    upstream_path: str
    dataset_license: str
    attribution: str
    ingestion_run_id: str
    acquisition_timestamp: str
    source_schema_version: str
    parser_version: str
    input_sha256: str
    artifact_identity_sha256: str
    byte_length: int
    row_count: int
    column_count: int
    delimiter: str
    encoding: str
    raw_reference: dict[str, str]
    post_fight_statistics: str
    parquet_uri: str | None
    parquet_sha256: str | None
    issues: tuple[str, ...]


def ingest_local_ufc_datalab_stats(
    *,
    input_file: Path,
    raw_root: Path = Path("data/raw"),
    interim_root: Path = Path("data/interim"),
) -> UfcDataLabIngestionResult:
    """Read exactly one local pinned raw file and publish a write-once Parquet.

    A malformed file is still immutably retained with a provenance manifest, but
    receives no Parquet publication. The content digest is also the idempotency
    key, so an unchanged input never triggers a second raw retrieval record.
    """

    file_path, commit_sha = _validate_pinned_path(input_file)
    source_bytes = file_path.read_bytes()
    input_sha256 = content_sha256(source_bytes)
    artifact_identity_sha256 = content_sha256(
        f"{input_sha256}:{UFC_DATALAB_PARSER_VERSION}".encode()
    )
    source_root = interim_root.resolve() / UFC_DATALAB_SOURCE_KEY
    replay_path = source_root / "replays" / f"{artifact_identity_sha256}.json"
    if replay_path.is_file():
        return _load_replay(replay_path)

    run_id = str(
        uuid5(
            NAMESPACE_URL,
            f"{UFC_DATALAB_SOURCE_KEY}:{commit_sha}:{artifact_identity_sha256}",
        )
    )
    now = datetime.now(UTC)
    raw_reference = LocalRawStore(raw_root).persist(
        RawWriteRequest(
            source_key=UFC_DATALAB_SOURCE_KEY,
            ingestion_run_id=run_id,
            source_locator=f"{UFC_DATALAB_REPOSITORY_URL}@{commit_sha}:data/stats/stats_raw.csv",
            requested_at=now,
            retrieved_at=now,
            content=source_bytes,
            retrieval_code_version=UFC_DATALAB_PARSER_VERSION,
            terms_policy_version=UFC_DATALAB_TERMS_VERSION,
            dataset_license=UFC_DATALAB_LICENSE,
            content_type="text/csv; charset=utf-8; delimiter=semicolon",
            original_filename=UFC_DATALAB_RAW_FILENAME,
            source_schema_version=UFC_DATALAB_SCHEMA_VERSION,
            attribution=UFC_DATALAB_ATTRIBUTION,
        )
    )
    encoding, fieldnames, source_rows, raw_issues = _parse_semicolon_csv(source_bytes)
    normalized_rows = _normalise_rows(source_rows, fieldnames, raw_reference.sha256, raw_issues)
    issues = tuple(sorted(set(raw_issues)))
    blocking_issues = tuple(issue for issue in issues if issue.startswith("DAT-011"))
    parquet_path: Path | None = None
    manifest_path = source_root / "manifests" / f"{artifact_identity_sha256}.json"
    if not blocking_issues:
        parquet_path = source_root / "parquet" / f"{artifact_identity_sha256}.parquet"
        frame = pl.DataFrame(normalized_rows, schema=_PARQUET_SCHEMA, strict=True)
        _write_parquet_once(frame, parquet_path)
    manifest = UfcDataLabManifest(
        source_identifier=UFC_DATALAB_SOURCE_KEY,
        repository_url=UFC_DATALAB_REPOSITORY_URL,
        commit_sha=commit_sha,
        upstream_path="data/stats/stats_raw.csv",
        dataset_license=UFC_DATALAB_LICENSE,
        attribution=UFC_DATALAB_ATTRIBUTION,
        ingestion_run_id=run_id,
        acquisition_timestamp=now.isoformat(),
        source_schema_version=UFC_DATALAB_SCHEMA_VERSION,
        parser_version=UFC_DATALAB_PARSER_VERSION,
        input_sha256=input_sha256,
        artifact_identity_sha256=artifact_identity_sha256,
        byte_length=len(source_bytes),
        row_count=len(source_rows),
        column_count=len(fieldnames),
        delimiter=";",
        encoding=encoding,
        raw_reference={
            "sha256": raw_reference.sha256,
            "object_uri": raw_reference.object_uri,
            "retrieval_manifest_uri": raw_reference.retrieval_manifest_uri,
        },
        post_fight_statistics="post_fight_fact_never_current_fight_feature",
        parquet_uri=str(parquet_path) if parquet_path else None,
        parquet_sha256=content_sha256(parquet_path.read_bytes()) if parquet_path else None,
        issues=issues,
    )
    _write_once(manifest_path, json.dumps(asdict(manifest), sort_keys=True).encode("utf-8"))
    result = UfcDataLabIngestionResult(
        ingestion_run_id=run_id,
        state="published" if parquet_path else "quarantined",
        replayed=False,
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        issues=issues,
    )
    _write_once(replay_path, json.dumps(_serialise_result(result), sort_keys=True).encode("utf-8"))
    return result


_PARQUET_SCHEMA = {
    "source_record_key": pl.String,
    "source_raw_sha256": pl.String,
    "fight_date": pl.Date,
    "red_fighter_source_name": pl.String,
    "blue_fighter_source_name": pl.String,
    "outcome_source_value": pl.String,
    "scheduled_rounds": pl.Int64,
    "finish_round": pl.Int64,
    "method_source_value": pl.String,
    "event_name": pl.String,
    "division_source_value": pl.String,
    "location": pl.String,
    "detailed_statistics": pl.String,
    "detailed_statistics_temporal_status": pl.String,
}


def _validate_pinned_path(input_file: Path) -> tuple[Path, str]:
    path = input_file.resolve()
    commit_sha = path.parent.name
    if (
        not path.is_file()
        or path.name != UFC_DATALAB_RAW_FILENAME
        or not _COMMIT.fullmatch(commit_sha)
    ):
        raise ValueError(
            "input_file must be a local data/incoming/ufc-datalab/<40-hex-commit>/stats_raw.csv"
        )
    return path, commit_sha


def _parse_semicolon_csv(
    content: bytes,
) -> tuple[str, tuple[str, ...], list[dict[str, str]], list[str]]:
    try:
        text = content.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        return "unknown", (), [], ["DAT-011.invalid_encoding"]
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=";")
    fieldnames = tuple(name.strip() for name in reader.fieldnames or () if name and name.strip())
    issues: list[str] = []
    if not fieldnames or len(fieldnames) < 2:
        issues.append("DAT-011.invalid_semicolon_schema")
    columns = {_normalise_header(name) for name in fieldnames}
    for semantic in ("fight_date", "red_fighter", "blue_fighter", "outcome", "scheduled_rounds"):
        if not any(_normalise_header(alias) in columns for alias in _HEADER_ALIASES[semantic]):
            issues.append(f"DAT-011.missing_{semantic}")
    rows = [
        {key.strip(): (value or "").strip() for key, value in row.items() if key} for row in reader
    ]
    return encoding, fieldnames, rows, issues


def _normalise_rows(
    rows: list[dict[str, str]], fieldnames: tuple[str, ...], raw_sha256: str, issues: list[str]
) -> list[dict[str, object]]:
    lookup = {_normalise_header(name): name for name in fieldnames}
    output: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, row in enumerate(rows, start=2):
        values = {
            semantic: _value(row, lookup, aliases) for semantic, aliases in _HEADER_ALIASES.items()
        }
        fight_date = _parse_date(values["fight_date"])
        red, blue, outcome = (
            values["red_fighter"],
            values["blue_fighter"],
            values["outcome"].casefold(),
        )
        rounds, finish_round = (
            _positive_int(values["scheduled_rounds"]),
            _optional_positive_int(values["finish_round"]),
        )
        row_issues: list[str] = []
        if not fight_date:
            row_issues.append("DAT-011.invalid_fight_date")
        if not red or not blue or red.casefold() == blue.casefold():
            row_issues.append("DAT-011.invalid_participants")
        if outcome not in _OUTCOMES:
            row_issues.append("DAT-011.invalid_outcome")
        no_time_limit = values["scheduled_rounds"].casefold().strip() == "no time limit"
        if rounds is None and not no_time_limit:
            row_issues.append("DAT-011.invalid_scheduled_rounds")
        if finish_round is not None and rounds is not None and finish_round > rounds:
            row_issues.append("REV-011.finish_round_exceeds_scheduled_rounds")
        if fight_date and red and blue:
            first_fighter, second_fighter = sorted((red.casefold(), blue.casefold()))
            duplicate_key = (fight_date.isoformat(), first_fighter, second_fighter)
            if duplicate_key in seen:
                row_issues.append("REV-011.duplicate_unordered_bout")
            seen.add(duplicate_key)
        blocking_row_issues = tuple(issue for issue in row_issues if issue.startswith("DAT-011"))
        if blocking_row_issues:
            issues.extend(f"{issue}:row-{index}" for issue in blocking_row_issues)
            continue
        issues.extend(f"{issue}:row-{index}" for issue in row_issues if issue.startswith("REV-011"))
        output.append(
            {
                "source_record_key": f"{UFC_DATALAB_RAW_FILENAME}:row-{index}",
                "source_raw_sha256": raw_sha256,
                "fight_date": fight_date,
                "red_fighter_source_name": red,
                "blue_fighter_source_name": blue,
                "outcome_source_value": outcome,
                "scheduled_rounds": rounds,
                "finish_round": finish_round,
                "method_source_value": values["method"],
                "event_name": values["event_name"],
                "division_source_value": values["division"],
                "location": values["location"],
                "detailed_statistics": json.dumps(row, sort_keys=True),
                "detailed_statistics_temporal_status": "post_fight_fact",
            }
        )
    return output


def _normalise_header(value: str) -> str:
    return " ".join(value.strip().casefold().replace("_", " ").split())


def _value(row: dict[str, str], lookup: dict[str, str], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        name = lookup.get(_normalise_header(alias))
        if name is not None:
            return row.get(name, "")
    return ""


def _parse_date(value: str) -> date | None:
    for parser in (
        date.fromisoformat,
        lambda candidate: datetime.strptime(candidate, "%d/%m/%Y").date(),
    ):
        try:
            return parser(value)
        except ValueError:
            continue
    return None


def _positive_int(value: str) -> int | None:
    normalized = value.strip()
    overtime = re.fullmatch(r"(\d+)\s*Rnd\s*\+\s*(\d*)OT(?:\s*\([^)]*\))?", normalized)
    if overtime is not None:
        overtime_rounds = int(overtime.group(2)) if overtime.group(2) else 1
        parsed = int(overtime.group(1)) + overtime_rounds
        return parsed if parsed > 0 else None
    leading_digits = re.match(r"^(\d+)", normalized)
    if leading_digits is None:
        return None
    parsed = int(leading_digits.group(1))
    return parsed if parsed > 0 else None


def _optional_positive_int(value: str) -> int | None:
    return None if not value else _positive_int(value)


def _write_once(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise RuntimeError(f"immutable path has conflicting content: {path}")
        return
    staging = path.with_name(f".{path.name}.staging")
    with staging.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def _write_parquet_once(frame: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    staging = path.with_name(f".{path.name}.staging")
    try:
        frame.write_parquet(staging, compression="zstd")
        with staging.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.link(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def _serialise_result(result: UfcDataLabIngestionResult) -> dict[str, object]:
    return {
        "ingestion_run_id": result.ingestion_run_id,
        "state": result.state,
        "parquet_path": str(result.parquet_path) if result.parquet_path else None,
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "issues": list(result.issues),
    }


def _load_replay(path: Path) -> UfcDataLabIngestionResult:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return UfcDataLabIngestionResult(
        ingestion_run_id=str(raw["ingestion_run_id"]),
        state=str(raw["state"]),
        replayed=True,
        parquet_path=Path(raw["parquet_path"]) if raw["parquet_path"] else None,
        manifest_path=Path(raw["manifest_path"]) if raw["manifest_path"] else None,
        issues=tuple(str(item) for item in raw["issues"]),
    )
