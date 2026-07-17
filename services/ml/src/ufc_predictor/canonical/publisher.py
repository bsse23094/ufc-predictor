"""Immutable local Parquet publication for fully mapped canonical observations."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import polars as pl

from ufc_predictor.canonical.models import CanonicalMappingResult
from ufc_predictor.validation_support import content_sha256

CANONICAL_SCHEMA_VERSION = "canonical-bouts-v1"


@dataclass(frozen=True, slots=True)
class CanonicalParquetManifest:
    """Content-addressed evidence for one immutable canonical Parquet partition."""

    canonical_schema_version: str
    source_identifier: str
    source_schema_version: str
    taxonomy_version: str
    input_count: int
    accepted_count: int
    raw_references: tuple[dict[str, str], ...]
    parquet_uri: str
    parquet_sha256: str


@dataclass(frozen=True, slots=True)
class CanonicalPublication:
    """Locations and digest of a newly published or replayed canonical projection."""

    parquet_path: Path
    manifest_path: Path
    replayed: bool


def publish_canonical_parquet(
    result: CanonicalMappingResult,
    *,
    canonical_root: Path = Path("data/canonical"),
) -> CanonicalPublication:
    """Publish only a fully mapped, balanced source slice with immutable paths."""

    if result.quarantined_record_keys:
        raise ValueError("canonical publication is blocked while source records remain quarantined")
    if not result.accepted:
        raise ValueError("canonical publication requires at least one accepted observation")
    source_identifiers = {record.source_identifier for record in result.accepted}
    schema_versions = {record.source_schema_version for record in result.accepted}
    taxonomy_versions = {record.taxonomy_version for record in result.accepted}
    if {len(source_identifiers), len(schema_versions), len(taxonomy_versions)} != {1}:
        raise ValueError("one canonical publication must have one source/schema/taxonomy version")

    digest = _publication_digest(result)
    source_identifier = next(iter(source_identifiers))
    root = canonical_root.resolve() / source_identifier
    parquet_path = root / "parquet" / f"{digest}.parquet"
    manifest_path = root / "manifests" / f"{digest}.json"
    if parquet_path.exists() or manifest_path.exists():
        if parquet_path.is_file() and manifest_path.is_file():
            return CanonicalPublication(parquet_path, manifest_path, replayed=True)
        raise FileExistsError("canonical immutable publication path is incomplete")

    frame = pl.DataFrame(
        [_row(record) for record in result.accepted],
        schema={
            "canonical_source_fight_key": pl.String,
            "source_identifier": pl.String,
            "source_schema_version": pl.String,
            "source_record_key": pl.String,
            "source_raw_sha256": pl.String,
            "raw_object_uri": pl.String,
            "raw_retrieval_manifest_uri": pl.String,
            "fighter_one_id": pl.String,
            "fighter_two_id": pl.String,
            "fight_date": pl.Date,
            "scheduled_rounds": pl.Int64,
            "canonical_division_code": pl.String,
            "source_division_label": pl.String,
            "location": pl.String,
            "country": pl.String,
            "title_bout": pl.Boolean,
            "outcome_type": pl.String,
            "winner_fighter_id": pl.String,
            "source_outcome_label": pl.String,
            "canonical_method_code": pl.String,
            "source_method_label": pl.String,
            "ingested_at": pl.Datetime(time_zone="UTC"),
            "identity_resolution_decision_ids": pl.List(pl.String),
            "taxonomy_version": pl.String,
        },
        strict=True,
    )
    _write_parquet_once(frame, parquet_path)
    raw_references = tuple(
        {
            "sha256": record.raw_reference.sha256,
            "object_uri": record.raw_reference.object_uri,
            "retrieval_manifest_uri": record.raw_reference.retrieval_manifest_uri,
        }
        for record in result.accepted
    )
    manifest = CanonicalParquetManifest(
        canonical_schema_version=CANONICAL_SCHEMA_VERSION,
        source_identifier=source_identifier,
        source_schema_version=next(iter(schema_versions)),
        taxonomy_version=next(iter(taxonomy_versions)),
        input_count=result.input_count,
        accepted_count=len(result.accepted),
        raw_references=raw_references,
        parquet_uri=str(parquet_path),
        parquet_sha256=content_sha256(parquet_path.read_bytes()),
    )
    _write_once(manifest_path, json.dumps(asdict(manifest), sort_keys=True).encode("utf-8"))
    return CanonicalPublication(parquet_path, manifest_path, replayed=False)


def _publication_digest(result: CanonicalMappingResult) -> str:
    payload = [
        {
            "canonical_source_fight_key": record.canonical_source_fight_key,
            "raw_sha256": record.raw_reference.sha256,
            "fighter_one_id": str(record.fighter_one_id),
            "fighter_two_id": str(record.fighter_two_id),
            "taxonomy_version": record.taxonomy_version,
        }
        for record in result.accepted
    ]
    return content_sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _row(record: object) -> dict[str, object]:
    from ufc_predictor.canonical.models import CanonicalFightObservation

    if not isinstance(record, CanonicalFightObservation):
        raise TypeError("canonical publication accepts only canonical fight observations")
    return {
        "canonical_source_fight_key": record.canonical_source_fight_key,
        "source_identifier": record.source_identifier,
        "source_schema_version": record.source_schema_version,
        "source_record_key": record.source_record_key,
        "source_raw_sha256": record.raw_reference.sha256,
        "raw_object_uri": record.raw_reference.object_uri,
        "raw_retrieval_manifest_uri": record.raw_reference.retrieval_manifest_uri,
        "fighter_one_id": str(record.fighter_one_id),
        "fighter_two_id": str(record.fighter_two_id),
        "fight_date": record.fight_date,
        "scheduled_rounds": record.scheduled_rounds,
        "canonical_division_code": record.canonical_division_code,
        "source_division_label": record.source_division_label,
        "location": record.location,
        "country": record.country,
        "title_bout": record.title_bout,
        "outcome_type": record.outcome_type.value,
        "winner_fighter_id": (
            str(record.winner_fighter_id) if record.winner_fighter_id is not None else None
        ),
        "source_outcome_label": record.source_outcome_label,
        "canonical_method_code": record.canonical_method_code,
        "source_method_label": record.source_method_label,
        "ingested_at": record.ingested_at,
        "identity_resolution_decision_ids": [
            str(decision_id) for decision_id in record.identity_resolution_decision_ids
        ],
        "taxonomy_version": record.taxonomy_version,
    }


def _write_parquet_once(frame: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = path.with_suffix(path.suffix + ".staging")
    if staging_path.exists():
        raise FileExistsError(f"staging path already exists: {staging_path}")
    try:
        frame.write_parquet(staging_path)
        with staging_path.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging_path, path)
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"immutable publication path already exists: {path}")
    staging_path = path.with_suffix(path.suffix + ".staging")
    if staging_path.exists():
        raise FileExistsError(f"staging path already exists: {staging_path}")
    try:
        with staging_path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging_path, path)
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise
