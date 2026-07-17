"""Local-file adapter for Kaggle's licensed Ultimate UFC Dataset.

The adapter never contacts Kaggle, UFCStats, or any upstream website.  A user
places an explicitly acquired ``ufc-master.csv`` in the ignored incoming zone;
this module copies its exact bytes to the immutable raw store before examining
the CSV and publishes only a narrow, source-shaped interim Parquet projection.
All potential model features and outcome fields are kept out of that Parquet
projection until Milestones 3 and 4 establish canonical and temporal lineage.
"""

from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

import polars as pl

from ufc_predictor.ingestion.base import (
    FetchResponse,
    ParsedRecord,
    RawReference,
    SchemaFingerprint,
    WorkUnit,
)
from ufc_predictor.ingestion.policies import (
    KAGGLE_ULTIMATE_UFC_DATASET_ATTRIBUTION,
    KAGGLE_ULTIMATE_UFC_DATASET_LICENSE,
    KAGGLE_ULTIMATE_UFC_DATASET_REF,
    KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY,
    kaggle_ultimate_ufc_dataset_policy,
)
from ufc_predictor.ingestion.raw_store import LocalRawStore
from ufc_predictor.ingestion.registry import SourceRegistry
from ufc_predictor.ingestion.runner import (
    IngestionExecutionResult,
    IngestionExecutor,
    IngestionRun,
    IngestionRunState,
)
from ufc_predictor.ingestion.validation import (
    IssueSeverity,
    RecordDisposition,
    RowAccounting,
    SchemaGate,
    TransportPolicy,
    ValidatedRecord,
    ValidationIssue,
)
from ufc_predictor.validation_support import content_sha256

KAGGLE_ULTIMATE_UFC_DATASET_SCHEMA_VERSION = "completed-bouts-v1"
KAGGLE_ULTIMATE_UFC_MASTER_FILENAME = "ufc-master.csv"
KAGGLE_ULTIMATE_UFC_DATASET_PARSER_VERSION = "kaggle-ultimate-ufc-dataset-v1"
_REQUIRED_COLUMNS = frozenset({"R_fighter", "B_fighter", "date", "Winner", "no_of_rounds"})
_SAFE_CONTEXT_COLUMNS = frozenset(
    {
        "R_fighter",
        "B_fighter",
        "date",
        "location",
        "country",
        "title_bout",
        "weight_class",
        "gender",
        "no_of_rounds",
    }
)
_RESULT_VALUES = frozenset({"red", "blue", "draw", "nc", "no contest", "no_contest"})


class LeakageClassification(StrEnum):
    """Why a source column cannot become an ML feature at the M2 boundary."""

    SAFE_CONTEXT = "safe_context_not_yet_feature_approved"
    SOURCE_ORDERING = "winner_derived_ordering_unverified"
    OUTCOME = "outcome_or_finish"
    MARKET = "market_timestamp_not_audited"
    UNVERIFIED_TEMPORAL = "current_fight_or_rolling_temporal_provenance_unverified"
    UNREVIEWED = "unreviewed_source_column"


def classify_leakage_column(column: str) -> LeakageClassification:
    """Classify every observed source column conservatively.

    Classifications deliberately over-quarantine.  The source describes merged
    statistics, odds, rankings, and results, but it cannot prove whether a
    supplied aggregate was visible before the target fight.
    """

    normalized = column.strip().casefold()
    if column in {"R_fighter", "B_fighter"}:
        return LeakageClassification.SOURCE_ORDERING
    if column in _SAFE_CONTEXT_COLUMNS:
        return LeakageClassification.SAFE_CONTEXT
    if normalized in {
        "winner",
        "finish",
        "finish_details",
        "finish_round",
        "finish_round_time",
        "total_fight_time_secs",
    }:
        return LeakageClassification.OUTCOME
    if normalized.endswith("_odds") or normalized in {"r_ev", "b_ev"}:
        return LeakageClassification.MARKET
    if (
        normalized.startswith(("r_", "b_"))
        or normalized.endswith("_dif")
        or "rank" in normalized
        or "streak" in normalized
        or normalized in {"better_rank", "empty_arena"}
    ):
        return LeakageClassification.UNVERIFIED_TEMPORAL
    return LeakageClassification.UNREVIEWED


def known_schema_fingerprint() -> SchemaFingerprint:
    """Return the intentionally narrow completed-bouts contract fingerprint."""

    return SchemaFingerprint.from_markers(
        (
            "file=ufc-master.csv",
            f"schema={KAGGLE_ULTIMATE_UFC_DATASET_SCHEMA_VERSION}",
            *[f"required={column}" for column in sorted(_REQUIRED_COLUMNS)],
        ),
        parser_version=KAGGLE_ULTIMATE_UFC_DATASET_PARSER_VERSION,
    )


@dataclass(frozen=True, slots=True)
class LocalKaggleIngestionResult:
    """Published local-file ingestion evidence and its immutable interim output."""

    execution: IngestionExecutionResult
    parquet_path: Path | None
    manifest_path: Path | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class InterimParquetManifest:
    """Sidecar for an immutable source-shaped Parquet projection."""

    source_identifier: str
    dataset_ref: str
    dataset_license: str
    attribution: str
    ingestion_run_id: str
    source_schema_version: str
    parser_version: str
    input_set_sha256: str
    raw_references: tuple[dict[str, str], ...]
    row_accounting: dict[str, int]
    leakage_policy: str
    parquet_uri: str
    parquet_sha256: str


class KaggleUltimateUfcDatasetAdapter:
    """Read an explicitly downloaded completed-bout CSV without network access."""

    source_key = KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY
    parser_version = KAGGLE_ULTIMATE_UFC_DATASET_PARSER_VERSION

    def __init__(
        self,
        incoming_directory: Path = Path("data/incoming/ultimate-ufc-dataset"),
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._incoming_directory = incoming_directory.resolve()
        self._now = now or (lambda: datetime.now(UTC))
        self._seen_fights: set[tuple[str, str, str, str]] = set()

    @property
    def incoming_file(self) -> Path:
        return self._incoming_directory / KAGGLE_ULTIMATE_UFC_MASTER_FILENAME

    def input_set_sha256(self) -> str:
        """Digest the exact local input identity without modifying it."""

        input_path = self.incoming_file
        if not input_path.is_file():
            raise FileNotFoundError(
                "expected manually downloaded Kaggle file at "
                f"{input_path}; see DATA_SOURCE_AUDIT.md for the official command"
            )
        payload = {
            "dataset_ref": KAGGLE_ULTIMATE_UFC_DATASET_REF,
            "filename": input_path.name,
            "sha256": content_sha256(input_path.read_bytes()),
            "schema_version": KAGGLE_ULTIMATE_UFC_DATASET_SCHEMA_VERSION,
        }
        return content_sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())

    def discover(self, checkpoint: Mapping[str, object] | None) -> Iterable[WorkUnit]:
        """Expose the single audited completed-bout file as one bounded work unit."""

        input_path = self.incoming_file
        if not input_path.is_file():
            raise FileNotFoundError(
                f"expected {KAGGLE_ULTIMATE_UFC_MASTER_FILENAME} in {self._incoming_directory}"
            )
        yield WorkUnit(
            source_key=self.source_key,
            unit_key=KAGGLE_ULTIMATE_UFC_MASTER_FILENAME,
            locator=(
                f"kaggle://{KAGGLE_ULTIMATE_UFC_DATASET_REF}/{KAGGLE_ULTIMATE_UFC_MASTER_FILENAME}"
            ),
            discovered_at=self._now(),
            attributes={
                "local_path": str(input_path),
                "original_filename": input_path.name,
                "source_schema_version": KAGGLE_ULTIMATE_UFC_DATASET_SCHEMA_VERSION,
                "input_set_sha256": self.input_set_sha256(),
            },
        )

    async def fetch(self, work_unit: WorkUnit) -> FetchResponse:
        """Read exact local bytes; this does not invoke an HTTP client or Kaggle API."""

        local_path = _required_attribute(work_unit, "local_path")
        requested_at = self._now()
        content = Path(local_path).read_bytes()
        retrieved_at = self._now()
        return FetchResponse(
            work_unit=work_unit,
            requested_at=requested_at,
            retrieved_at=retrieved_at,
            status_code=200,
            headers={"content-length": str(len(content)), "content-type": "text/csv"},
            content=content,
            content_type="text/csv",
        )

    def fingerprint(self, response: FetchResponse) -> SchemaFingerprint:
        """Accept only a CSV with the audited completed-bout required columns."""

        try:
            fieldnames = _csv_fieldnames(response.content)
        except UnicodeDecodeError:
            return SchemaFingerprint.from_markers(
                ("file=unreadable", "encoding=not-utf-8"), parser_version=self.parser_version
            )
        missing = sorted(_REQUIRED_COLUMNS.difference(fieldnames))
        if missing:
            return SchemaFingerprint.from_markers(
                ("file=ufc-master.csv", *[f"missing={column}" for column in missing]),
                parser_version=self.parser_version,
            )
        return known_schema_fingerprint()

    def parse(self, response: FetchResponse, raw_reference: RawReference) -> Iterable[ParsedRecord]:
        """Create source-shaped records; unsafe values never leave this adapter as features."""

        text = response.content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        fieldnames = tuple(reader.fieldnames or ())
        classifications = {column: classify_leakage_column(column).value for column in fieldnames}
        original_filename = _required_attribute(response.work_unit, "original_filename")
        for row_number, row in enumerate(reader, start=2):
            yield ParsedRecord(
                record_key=f"{original_filename}:row-{row_number}",
                raw_reference=raw_reference,
                payload={
                    "source_fields": {key: value for key, value in row.items() if key is not None},
                    "column_classifications": classifications,
                    "original_filename": original_filename,
                    "source_schema_version": KAGGLE_ULTIMATE_UFC_DATASET_SCHEMA_VERSION,
                },
            )

    def validate(self, records: Iterable[ParsedRecord]) -> Iterable[ValidatedRecord]:
        """Quarantine invalid types, results, and duplicate completed fights."""

        self._seen_fights.clear()
        for record in records:
            fields = _source_fields(record)
            issues: list[ValidationIssue] = []
            red_fighter = _nonempty_text(fields.get("R_fighter"))
            blue_fighter = _nonempty_text(fields.get("B_fighter"))
            fight_date = _parse_date(fields.get("date"))
            scheduled_rounds = _parse_positive_int(fields.get("no_of_rounds"))
            winner = _nonempty_text(fields.get("Winner"))

            if (
                red_fighter is None
                or blue_fighter is None
                or red_fighter.casefold() == blue_fighter.casefold()
            ):
                issues.append(
                    _issue("DAT-004.invalid_participants", record, "fighters must be distinct")
                )
            if fight_date is None:
                issues.append(_issue("DAT-004.invalid_fight_date", record, "date must be ISO-8601"))
            if scheduled_rounds is None:
                issues.append(
                    _issue(
                        "DAT-004.invalid_scheduled_rounds", record, "no_of_rounds must be positive"
                    )
                )
            if winner is None or winner.casefold() not in _RESULT_VALUES:
                issues.append(
                    _issue("DAT-004.invalid_result", record, "Winner is not an allowed result")
                )

            if (
                not issues
                and red_fighter is not None
                and blue_fighter is not None
                and fight_date is not None
            ):
                fighter_pair = tuple(sorted((red_fighter.casefold(), blue_fighter.casefold())))
                duplicate_key = (
                    fight_date.isoformat(),
                    fighter_pair[0],
                    fighter_pair[1],
                    _nonempty_text(fields.get("weight_class")) or "",
                )
                if duplicate_key in self._seen_fights:
                    issues.append(
                        _issue(
                            "DAT-004.duplicate_fight",
                            record,
                            "duplicate unordered fighter pair on the same date and weight class",
                        )
                    )
                else:
                    self._seen_fights.add(duplicate_key)

            if issues:
                yield ValidatedRecord(
                    record=record,
                    disposition=RecordDisposition.QUARANTINED,
                    issues=tuple(issues),
                )
            else:
                yield ValidatedRecord(record=record, disposition=RecordDisposition.ACCEPTED)


async def ingest_local_kaggle_ultimate_dataset(
    *,
    incoming_directory: Path = Path("data/incoming/ultimate-ufc-dataset"),
    raw_root: Path = Path("data/raw"),
    interim_root: Path = Path("data/interim"),
) -> LocalKaggleIngestionResult:
    """Ingest the manually acquired dataset and publish an idempotent Parquet projection."""

    adapter = KaggleUltimateUfcDatasetAdapter(incoming_directory)
    input_set_sha256 = adapter.input_set_sha256()
    replay_path = _replay_path(interim_root, input_set_sha256)
    replay = _load_replay(replay_path)
    if replay is not None:
        return _replayed_result(replay)

    fingerprint = known_schema_fingerprint()
    executor = IngestionExecutor(
        registry=SourceRegistry([kaggle_ultimate_ufc_dataset_policy()]),
        raw_store=LocalRawStore(raw_root),
        schema_gate=SchemaGate(frozenset({fingerprint.value})),
        transport_policy=TransportPolicy(max_response_bytes=10_485_760),
        max_work_units=1,
    )
    checkpoint = {
        "input_set_sha256": input_set_sha256,
        "source_schema_version": KAGGLE_ULTIMATE_UFC_DATASET_SCHEMA_VERSION,
    }
    execution = await executor.execute(
        adapter=adapter,
        mode="local-file",
        previous_checkpoint=checkpoint,
        candidate_checkpoint=checkpoint,
    )
    if execution.run.state is not IngestionRunState.PUBLISHED:
        return LocalKaggleIngestionResult(execution, None, None, replayed=False)

    parquet_path, manifest_path = _publish_interim_parquet(
        records=execution.records,
        run=execution.run,
        input_set_sha256=input_set_sha256,
        interim_root=interim_root,
    )
    _write_replay(
        replay_path,
        execution=execution,
        parquet_path=parquet_path,
        manifest_path=manifest_path,
    )
    return LocalKaggleIngestionResult(execution, parquet_path, manifest_path, replayed=False)


def _publish_interim_parquet(
    *,
    records: Sequence[ParsedRecord],
    run: IngestionRun,
    input_set_sha256: str,
    interim_root: Path,
) -> tuple[Path, Path]:
    source_root = interim_root.resolve() / KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY
    parquet_path = source_root / "parquet" / f"{input_set_sha256}.parquet"
    manifest_path = source_root / "manifests" / f"{input_set_sha256}.json"
    rows = [_interim_row(record, run.run_id) for record in records]
    frame = pl.DataFrame(
        rows,
        schema={
            "source_record_key": pl.String,
            "fight_date": pl.Date,
            "fighter_one_source_name": pl.String,
            "fighter_two_source_name": pl.String,
            "location": pl.String,
            "country": pl.String,
            "title_bout": pl.String,
            "weight_class": pl.String,
            "gender": pl.String,
            "scheduled_rounds": pl.Int64,
            "source_raw_sha256": pl.String,
            "original_filename": pl.String,
            "source_schema_version": pl.String,
            "ingestion_run_id": pl.String,
            "quarantined_column_names": pl.List(pl.String),
        },
        strict=True,
    )
    _write_parquet_once(frame, parquet_path)
    parquet_sha256 = content_sha256(parquet_path.read_bytes())
    accounting = run.accounting
    if accounting is None:
        raise RuntimeError("published ingestion run has no row accounting")
    manifest = InterimParquetManifest(
        source_identifier=KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY,
        dataset_ref=KAGGLE_ULTIMATE_UFC_DATASET_REF,
        dataset_license=KAGGLE_ULTIMATE_UFC_DATASET_LICENSE,
        attribution=KAGGLE_ULTIMATE_UFC_DATASET_ATTRIBUTION,
        ingestion_run_id=run.run_id,
        source_schema_version=KAGGLE_ULTIMATE_UFC_DATASET_SCHEMA_VERSION,
        parser_version=KAGGLE_ULTIMATE_UFC_DATASET_PARSER_VERSION,
        input_set_sha256=input_set_sha256,
        raw_references=tuple(
            {
                "sha256": record.raw_reference.sha256,
                "object_uri": record.raw_reference.object_uri,
                "retrieval_manifest_uri": record.raw_reference.retrieval_manifest_uri,
            }
            for record in records
        ),
        row_accounting={
            "input_count": accounting.input_count,
            "accepted_count": accounting.accepted_count,
            "quarantined_count": accounting.quarantined_count,
            "filtered_count": accounting.filtered_count,
        },
        leakage_policy="all non-context source columns are quarantined from features in M2",
        parquet_uri=str(parquet_path),
        parquet_sha256=parquet_sha256,
    )
    _write_once(manifest_path, json.dumps(asdict(manifest), sort_keys=True).encode("utf-8"))
    return parquet_path, manifest_path


def _interim_row(record: ParsedRecord, run_id: str) -> dict[str, object]:
    fields = _source_fields(record)
    classifications = _column_classifications(record)
    parsed_date = _parse_date(fields.get("date"))
    scheduled_rounds = _parse_positive_int(fields.get("no_of_rounds"))
    if parsed_date is None or scheduled_rounds is None:
        raise RuntimeError("only validated records may be written to interim Parquet")
    return {
        "source_record_key": record.record_key,
        "fight_date": parsed_date,
        "fighter_one_source_name": _nonempty_text(fields.get("R_fighter")) or "",
        "fighter_two_source_name": _nonempty_text(fields.get("B_fighter")) or "",
        "location": _nonempty_text(fields.get("location")) or "",
        "country": _nonempty_text(fields.get("country")) or "",
        "title_bout": _nonempty_text(fields.get("title_bout")) or "",
        "weight_class": _nonempty_text(fields.get("weight_class")) or "",
        "gender": _nonempty_text(fields.get("gender")) or "",
        "scheduled_rounds": scheduled_rounds,
        "source_raw_sha256": record.raw_reference.sha256,
        "original_filename": _required_payload_string(record, "original_filename"),
        "source_schema_version": _required_payload_string(record, "source_schema_version"),
        "ingestion_run_id": run_id,
        "quarantined_column_names": sorted(
            column
            for column, classification in classifications.items()
            if classification != LeakageClassification.SAFE_CONTEXT.value
        ),
    }


def _write_parquet_once(frame: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = path.with_name(f".{path.name}.{uuid4().hex}.staging")
    try:
        frame.write_parquet(staging_path, compression="zstd")
        # Windows requires a writable descriptor for fsync; the Parquet writer
        # has already closed its handle before this durability barrier.
        with staging_path.open("r+b") as stream:
            os.fsync(stream.fileno())
        try:
            os.link(staging_path, path)
        except FileExistsError:
            if content_sha256(path.read_bytes()) != content_sha256(staging_path.read_bytes()):
                raise RuntimeError(
                    "immutable interim Parquet path has conflicting content"
                ) from None
    finally:
        staging_path.unlink(missing_ok=True)


def _write_once(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = path.with_name(f".{path.name}.{uuid4().hex}.staging")
    try:
        with staging_path.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(staging_path, path)
        except FileExistsError:
            if path.read_bytes() != content:
                raise RuntimeError("immutable manifest path has conflicting content") from None
    finally:
        staging_path.unlink(missing_ok=True)


def _replay_path(interim_root: Path, input_set_sha256: str) -> Path:
    return (
        interim_root.resolve()
        / KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY
        / "replays"
        / f"{input_set_sha256}.json"
    )


def _write_replay(
    path: Path,
    *,
    execution: IngestionExecutionResult,
    parquet_path: Path,
    manifest_path: Path,
) -> None:
    accounting = execution.run.accounting
    if accounting is None:
        raise RuntimeError("published ingestion run has no row accounting")
    payload = {
        "run_id": execution.run.run_id,
        "accounting": asdict(accounting),
        "checkpoint": dict(execution.run.new_checkpoint or {}),
        "parquet_path": str(parquet_path),
        "manifest_path": str(manifest_path),
    }
    _write_once(path, json.dumps(payload, sort_keys=True).encode("utf-8"))


def _load_replay(path: Path) -> Mapping[str, object] | None:
    if not path.is_file():
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError("local ingestion replay record is malformed")
    return loaded


def _replayed_result(replay: Mapping[str, object]) -> LocalKaggleIngestionResult:
    run_id = _required_mapping_string(replay, "run_id")
    accounting_values = replay.get("accounting")
    checkpoint = replay.get("checkpoint")
    if not isinstance(accounting_values, Mapping) or not isinstance(checkpoint, Mapping):
        raise RuntimeError("local ingestion replay record is malformed")
    accounting = RowAccounting(
        input_count=_required_mapping_int(accounting_values, "input_count"),
        accepted_count=_required_mapping_int(accounting_values, "accepted_count"),
        quarantined_count=_required_mapping_int(accounting_values, "quarantined_count"),
        filtered_count=_required_mapping_int(accounting_values, "filtered_count"),
    )
    run = IngestionRun(
        source_key=KAGGLE_ULTIMATE_UFC_DATASET_SOURCE_KEY,
        mode="local-file",
        previous_checkpoint=checkpoint,
    )
    run.restore_persisted(
        run_id=run_id,
        state=IngestionRunState.PUBLISHED,
        accounting=accounting,
        new_checkpoint=checkpoint,
    )
    execution = IngestionExecutionResult(run, (), (), replayed=True)
    return LocalKaggleIngestionResult(
        execution,
        Path(_required_mapping_string(replay, "parquet_path")),
        Path(_required_mapping_string(replay, "manifest_path")),
        replayed=True,
    )


def _csv_fieldnames(content: bytes) -> frozenset[str]:
    text = content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text, newline=""))
    fieldnames = next(reader, ())
    return frozenset(name.strip() for name in fieldnames if name.strip())


def _source_fields(record: ParsedRecord) -> Mapping[str, object]:
    value = record.payload.get("source_fields")
    if not isinstance(value, Mapping):
        raise ValueError("parsed Kaggle record is missing source fields")
    return value


def _column_classifications(record: ParsedRecord) -> Mapping[str, str]:
    value = record.payload.get("column_classifications")
    if not isinstance(value, Mapping) or not all(
        isinstance(column, str) and isinstance(classification, str)
        for column, classification in value.items()
    ):
        raise ValueError("parsed Kaggle record has invalid column classifications")
    return value


def _required_payload_string(record: ParsedRecord, name: str) -> str:
    value = record.payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"parsed Kaggle record is missing {name}")
    return value


def _required_attribute(work_unit: WorkUnit, name: str) -> str:
    value = work_unit.attributes.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Kaggle work unit is missing {name}")
    return value


def _nonempty_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _parse_date(value: object) -> date | None:
    normalized = _nonempty_text(value)
    if normalized is None:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _parse_positive_int(value: object) -> int | None:
    normalized = _nonempty_text(value)
    if normalized is None or not normalized.isdecimal():
        return None
    parsed = int(normalized)
    return parsed if parsed > 0 else None


def _issue(rule_id: str, record: ParsedRecord, summary: str) -> ValidationIssue:
    return ValidationIssue(
        rule_id=rule_id,
        severity=IssueSeverity.QUARANTINE,
        summary=summary,
        raw_sha256=record.raw_reference.sha256,
    )


def _required_mapping_string(mapping: Mapping[str, object], name: str) -> str:
    value = mapping.get(name)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"local ingestion replay record is missing {name}")
    return value


def _required_mapping_int(mapping: Mapping[str, object], name: str) -> int:
    value = mapping.get(name)
    if not isinstance(value, int):
        raise RuntimeError(f"local ingestion replay record is missing {name}")
    return value
