"""Deterministic M3 reviewer packet generation and guarded decision intake.

This boundary records a human decision for later canonical validation.  It
never changes an immutable raw object, a source-shaped observation, an alias,
or a taxonomy mapping by itself.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from ufc_predictor.identity.normalize import normalize_fighter_alias

PACKET_VERSION = "m3-reviewer-packet-v1"
_DECISION_COLUMNS = (
    "review_id",
    "category",
    "source_values",
    "proposed_canonical_value_or_action",
    "affected_row_count",
    "affected_bout_count",
    "representative_evidence",
    "confidence",
    "recommended_decision",
    "source_evidence_sha256",
    "reviewer_decision",
    "reviewer",
    "decision_timestamp",
    "reviewer_notes",
)
_STANDARD_DECISIONS = frozenset(
    {
        "approve",
        "approve_corrected_mapping",
        "preserve_null",
        "exclude_affected_record",
        "reject",
        "defer",
    }
)
_OUTCOME_DECISIONS = frozenset(
    {
        "select_ultimate",
        "select_ufc_datalab",
        "confirm_draw",
        "confirm_no_contest",
        "confirm_overturned",
        "source_parsing_error",
        "defer",
    }
)


class ReviewerDecisionImportError(ValueError):
    """A reviewer file is incomplete, stale, contradictory, or unknown."""


@dataclass(frozen=True, slots=True)
class ReviewerPacketItem:
    review_id: str
    category: str
    source_values: tuple[str, ...]
    proposed_canonical_value_or_action: str
    affected_row_count: int
    affected_bout_count: int
    representative_evidence: str
    confidence: str
    recommended_decision: str

    @property
    def source_evidence_sha256(self) -> str:
        payload = {
            "packet_version": PACKET_VERSION,
            "review_id": self.review_id,
            "category": self.category,
            "source_values": self.source_values,
            "proposed_canonical_value_or_action": self.proposed_canonical_value_or_action,
            "affected_row_count": self.affected_row_count,
            "affected_bout_count": self.affected_bout_count,
            "representative_evidence": self.representative_evidence,
        }
        return _sha256_json(payload)

    def csv_row(self) -> dict[str, str]:
        return {
            "review_id": self.review_id,
            "category": self.category,
            "source_values": " || ".join(self.source_values),
            "proposed_canonical_value_or_action": self.proposed_canonical_value_or_action,
            "affected_row_count": str(self.affected_row_count),
            "affected_bout_count": str(self.affected_bout_count),
            "representative_evidence": self.representative_evidence,
            "confidence": self.confidence,
            "recommended_decision": self.recommended_decision,
            "source_evidence_sha256": self.source_evidence_sha256,
            "reviewer_decision": "",
            "reviewer": "",
            "decision_timestamp": "",
            "reviewer_notes": "",
        }


@dataclass(frozen=True, slots=True)
class ReviewerPacketReport:
    identity_count: int
    taxonomy_count: int
    outcome_count: int
    packet_path: Path
    identity_csv_path: Path
    taxonomy_csv_path: Path
    outcome_csv_path: Path


@dataclass(frozen=True, slots=True)
class DecisionImportReport:
    applied: int
    replayed: int
    ledger_path: Path


@dataclass(frozen=True, slots=True)
class CorrectionPacketReport:
    identity_replacement_id: str
    taxonomy_replacement_count: int
    bout_review_count: int
    proposed_exclusion_count: int
    output_dir: Path


@dataclass(frozen=True, slots=True)
class V6ReviewerPackageReport:
    """Completion state for the closed set of v6 M3 review decisions."""

    identity_count: int
    taxonomy_mapping_count: int
    null_policy_count: int
    special_format_count: int
    ultimate_four_round_count: int
    unresolved_bout_count: int
    outcome_count: int
    completed_count: int
    blank_count: int
    valid_completed_count: int

    @property
    def total_required_count(self) -> int:
        return (
            self.identity_count
            + self.taxonomy_mapping_count
            + self.null_policy_count
            + self.special_format_count
            + self.ultimate_four_round_count
            + self.unresolved_bout_count
            + self.outcome_count
        )

    @property
    def is_complete(self) -> bool:
        return self.blank_count == 0 and self.valid_completed_count == self.total_required_count


@dataclass(frozen=True, slots=True)
class LegacyAuthorityMigrationReport:
    accepted_identity_count: int
    accepted_taxonomy_count: int
    retired_or_superseded_count: int
    rejected_count: int
    ledger_path: Path
    report_path: Path


@dataclass(frozen=True, slots=True)
class RoundSemanticsProfile:
    """Read-only findings from the UFC-DataLab bout-format detector."""

    row_count: int
    unique_bout_count: int
    violation_row_count: int
    violation_unique_bout_count: int
    special_format_row_count: int
    special_format_unique_bout_count: int


def generate_m3_reviewer_packet(
    *,
    ultimate_identity_queue: Path,
    datalab_identity_queue: Path,
    ultimate_taxonomy_queue: Path,
    datalab_taxonomy_queue: Path,
    residual_outcome_conflicts: Path,
    output_dir: Path,
) -> ReviewerPacketReport:
    """Consolidate source review queues into non-mutating reviewer artifacts."""

    identity = _consolidate_queue(
        (
            ("ultimate", _read_markdown_queue(ultimate_identity_queue)),
            ("ufc-datalab", _read_markdown_queue(datalab_identity_queue)),
        ),
        kind="identity",
    )
    taxonomy = _consolidate_queue(
        (
            ("ultimate", _read_markdown_queue(ultimate_taxonomy_queue)),
            ("ufc-datalab", _read_markdown_queue(datalab_taxonomy_queue)),
        ),
        kind="taxonomy",
    )
    outcomes = _outcome_items(residual_outcome_conflicts)
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_path = output_dir / "m3_reviewer_packet.md"
    identity_path = output_dir / "m3_identity_decisions.csv"
    taxonomy_path = output_dir / "m3_taxonomy_decisions.csv"
    outcome_path = output_dir / "m3_outcome_conflict_decisions.csv"
    _write_once_or_same(packet_path, _packet_markdown(identity, taxonomy, outcomes))
    _write_csv_once_or_same(identity_path, identity)
    _write_csv_once_or_same(taxonomy_path, taxonomy)
    _write_csv_once_or_same(outcome_path, outcomes)
    return ReviewerPacketReport(
        len(identity),
        len(taxonomy),
        len(outcomes),
        packet_path,
        identity_path,
        taxonomy_path,
        outcome_path,
    )


def import_m3_reviewer_decisions(
    *,
    packet_dir: Path,
    decision_files: tuple[Path, ...],
    ledger_path: Path | None = None,
    require_complete: bool = False,
) -> DecisionImportReport:
    """Validate reviewer rows and append accepted decisions idempotently.

    An accepted row is a durable review record only.  Identity and taxonomy
    application remain separate, reviewer-attributed canonical-gate actions.
    """

    packet_rows = _packet_registry(packet_dir)
    if require_complete:
        report = validate_m3_v6_reviewer_package(packet_dir)
        if not report.is_complete:
            raise ReviewerDecisionImportError(
                "v6 reviewer package has blank or invalid active decisions; import is blocked"
            )
    retired_ids = _retired_review_ids(packet_dir)
    submitted: dict[str, dict[str, str]] = {}
    for path in decision_files:
        for row in _read_decision_csv(path):
            if not row["reviewer_decision"].strip():
                continue
            review_id = row["review_id"]
            if review_id in submitted:
                raise ReviewerDecisionImportError(f"duplicate decision for review ID: {review_id}")
            if review_id in retired_ids:
                raise ReviewerDecisionImportError(f"retired review ID: {review_id}")
            _validate_submitted_row(row, packet_rows)
            submitted[review_id] = row
    actual_ledger = ledger_path or packet_dir / "m3_imported_decisions.jsonl"
    existing = _read_ledger(actual_ledger)
    additions: list[dict[str, str]] = []
    replayed = 0
    for review_id in sorted(submitted):
        row = submitted[review_id]
        previous = existing.get(review_id)
        if previous is None:
            additions.append(_ledger_record(row))
        elif _decision_identity(previous) == _decision_identity(_ledger_record(row)):
            replayed += 1
        else:
            raise ReviewerDecisionImportError(f"contradictory decision for review ID: {review_id}")
    if additions:
        actual_ledger.parent.mkdir(parents=True, exist_ok=True)
        with actual_ledger.open("a", encoding="utf-8", newline="\n") as stream:
            for record in additions:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
    return DecisionImportReport(len(additions), replayed, actual_ledger)


def prepare_m3_v6_reviewer_package(
    *,
    outcome_source_csv: Path,
    output_dir: Path,
) -> Path:
    """Authorize the prior outcome decisions in v6 without changing their evidence.

    The source is read only during package preparation.  Once emitted, the v6
    importer reads its closed packet directory exclusively.
    """

    source_rows = _read_decision_csv(outcome_source_csv)
    if len(source_rows) != 14 or any(
        not row["category"].startswith("outcome.") for row in source_rows
    ):
        raise ReviewerDecisionImportError(
            "outcome source must contain exactly 14 outcome decisions"
        )
    actions: defaultdict[str, int] = defaultdict(int)
    for row in source_rows:
        _validate_packet_row(row)
        _validate_submitted_row(row, {row["review_id"]: row})
        actions[row["reviewer_decision"]] += 1
    if dict(actions) != {"confirm_overturned": 12, "select_ufc_datalab": 2}:
        raise ReviewerDecisionImportError(
            "outcome source does not contain the approved 12/2 action split"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "m3_outcome_decisions.csv"
    _write_once_or_same(output_path, _csv_content(list(source_rows)))
    _write_once_or_same(
        output_dir / "m3_v6_outcome_authorization.json",
        json.dumps(
            {
                "packet_version": PACKET_VERSION,
                "authorized_outcome_actions": dict(sorted(actions.items())),
                "outcome_source_filename": outcome_source_csv.name,
                "review_ids": [row["review_id"] for row in source_rows],
                "source_evidence_sha256": {
                    row["review_id"]: row["source_evidence_sha256"] for row in source_rows
                },
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
    )
    return output_path


def validate_m3_v6_reviewer_package(packet_dir: Path) -> V6ReviewerPackageReport:
    """Validate the complete v6 packet without importing or writing a ledger."""

    registry = _packet_registry(packet_dir)
    retired = _retired_review_ids(packet_dir)
    if retired.intersection(registry):
        raise ReviewerDecisionImportError("retired correction review ID appears in v6 packet")
    expected_counts = {
        "identity.consolidated_alias_identity": 1,
        "taxonomy.division_exact_normalization": 1,
        "taxonomy.finish_method_exact_mapping": 5,
        "taxonomy.missing_stance_policy": 1,
        "bout_format.special_format": 9,
        "bout_format.cross_source_four_round_confirmation": 1,
        "bout_format.unresolved_cross_source_match": 2,
        "outcome.no_contest_vs_winner": 12,
        "outcome.winner_disagreement": 2,
    }
    actual_counts: defaultdict[str, int] = defaultdict(int)
    completed = 0
    blank = 0
    valid_completed = 0
    for row in registry.values():
        actual_counts[row["category"]] += 1
        if not row["reviewer_decision"].strip():
            blank += 1
            continue
        completed += 1
        _validate_submitted_row(row, registry)
        valid_completed += 1
    if dict(actual_counts) != expected_counts:
        raise ReviewerDecisionImportError(
            f"unexpected v6 reviewer-package composition: {dict(sorted(actual_counts.items()))}"
        )
    return V6ReviewerPackageReport(
        identity_count=actual_counts["identity.consolidated_alias_identity"],
        taxonomy_mapping_count=(
            actual_counts["taxonomy.division_exact_normalization"]
            + actual_counts["taxonomy.finish_method_exact_mapping"]
        ),
        null_policy_count=actual_counts["taxonomy.missing_stance_policy"],
        special_format_count=actual_counts["bout_format.special_format"],
        ultimate_four_round_count=actual_counts["bout_format.cross_source_four_round_confirmation"],
        unresolved_bout_count=actual_counts["bout_format.unresolved_cross_source_match"],
        outcome_count=(
            actual_counts["outcome.no_contest_vs_winner"]
            + actual_counts["outcome.winner_disagreement"]
        ),
        completed_count=completed,
        blank_count=blank,
        valid_completed_count=valid_completed,
    )


def migrate_m3_legacy_authorities(
    *,
    legacy_identity_csv: Path,
    legacy_taxonomy_csv: Path,
    legacy_packet_dir: Path,
    v6_packet_dir: Path,
    output_dir: Path,
) -> LegacyAuthorityMigrationReport:
    """Migrate only validated approved legacy rows into an immutable authority ledger."""

    legacy_registry = _packet_registry(legacy_packet_dir)
    v6_registry = _packet_registry(v6_packet_dir)
    retired = _retired_review_ids(legacy_packet_dir) | _retired_review_ids(v6_packet_dir)
    accepted: list[dict[str, str]] = []
    retired_or_superseded: list[str] = []
    rejected: list[dict[str, str]] = []
    for path, expected_category in (
        (legacy_identity_csv, "identity."),
        (legacy_taxonomy_csv, "taxonomy."),
    ):
        for row in _read_decision_csv(path):
            review_id = row["review_id"]
            if not row["category"].startswith(expected_category):
                rejected.append({"review_id": review_id, "reason": "unexpected_category"})
                continue
            if (
                review_id in retired
                or review_id in v6_registry
                or row["reviewer_decision"] != "approve"
            ):
                retired_or_superseded.append(review_id)
                continue
            try:
                _validate_submitted_row(row, legacy_registry)
            except ReviewerDecisionImportError as error:
                rejected.append({"review_id": review_id, "reason": str(error)})
                continue
            accepted.append(
                {
                    "record_type": "m3_supplemental_legacy_authority",
                    "authority_kind": "identity"
                    if row["category"].startswith("identity.")
                    else "taxonomy",
                    "legacy_review_id": review_id,
                    "category": row["category"],
                    "source_values": row["source_values"],
                    "proposed_canonical_value_or_action": row["proposed_canonical_value_or_action"],
                    "representative_evidence": row["representative_evidence"],
                    "source_evidence_sha256": row["source_evidence_sha256"],
                    "reviewer": row["reviewer"],
                    "decision_timestamp": row["decision_timestamp"],
                    "reviewer_notes": row["reviewer_notes"],
                }
            )
    accepted.sort(key=lambda row: row["legacy_review_id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "m3_supplemental_legacy_authorities.jsonl"
    report_path = output_dir / "m3_legacy_authority_migration_report.json"
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in accepted)
    _write_once_or_same(ledger_path, payload)
    accepted_identity_count = sum(row["authority_kind"] == "identity" for row in accepted)
    accepted_taxonomy_count = sum(row["authority_kind"] == "taxonomy" for row in accepted)
    report_payload = {
        "accepted_identity_count": accepted_identity_count,
        "accepted_taxonomy_count": accepted_taxonomy_count,
        "retired_or_superseded_review_ids": sorted(retired_or_superseded),
        "rejected": sorted(rejected, key=lambda row: row["review_id"]),
        "legacy_identity_csv": str(legacy_identity_csv),
        "legacy_taxonomy_csv": str(legacy_taxonomy_csv),
        "v6_packet_dir": str(v6_packet_dir),
    }
    _write_once_or_same(report_path, json.dumps(report_payload, sort_keys=True, indent=2) + "\n")
    return LegacyAuthorityMigrationReport(
        accepted_identity_count=accepted_identity_count,
        accepted_taxonomy_count=accepted_taxonomy_count,
        retired_or_superseded_count=len(retired_or_superseded),
        rejected_count=len(rejected),
        ledger_path=ledger_path,
        report_path=report_path,
    )


def generate_m3_correction_packet(
    *,
    ultimate_csv: Path,
    datalab_csv: Path,
    output_dir: Path,
    retire_manifest_path: Path,
) -> CorrectionPacketReport:
    """Create replacement-only, evidence-bound proposals for reviewer deferrals."""

    retired = (
        "M3-ID-45CDDFCF91DA",
        "M3-ID-333577CCC1AF",
        "M3-TAX-257DFBD9A034",
        "M3-TAX-398D1F4ABE63",
        "M3-TAX-FD0AB57445C9",
        "M3-TAX-935D1986C187",
        "M3-TAX-793554275A41",
        "M3-TAX-5ED353D0D548",
        "M3-TAX-4C9107B3AF63",
        "M3-TAX-D686698596B7",
        "M3-TAX-8C3A077E1E51",
        "M3-TAX-52281807F1B7",
    )
    identity = _roldan_replacement_item()
    taxonomy = _taxonomy_replacement_items()
    bout_items = _bout_format_items(ultimate_csv=ultimate_csv, datalab_csv=datalab_csv)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_once_or_same(
        retire_manifest_path,
        json.dumps(
            {
                "packet_version": PACKET_VERSION,
                "retired_review_ids": retired,
                "replacement_identity_review_id": identity.review_id,
                "replacement_taxonomy_review_ids": [item.review_id for item in taxonomy],
                "replacement_bout_review_ids": [item.review_id for item in bout_items],
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
    )
    _write_once_or_same(
        output_dir / "m3_correction_reviewer_packet.md",
        _correction_markdown(identity, taxonomy, bout_items, retired),
    )
    _write_csv_once_or_same(output_dir / "m3_identity_correction_decisions.csv", (identity,))
    _write_csv_once_or_same(output_dir / "m3_taxonomy_correction_decisions.csv", taxonomy)
    _write_csv_once_or_same(output_dir / "m3_bout_format_decisions.csv", bout_items)
    _write_once_or_same(
        output_dir / "m3_anomaly_detector_audit.md",
        _round_semantics_audit_markdown(datalab_csv),
    )
    _write_once_or_same(
        output_dir / "m3_ultimate_four_round_audit.md",
        _ultimate_four_round_audit_markdown(ultimate_csv, datalab_csv),
    )
    return CorrectionPacketReport(
        identity.review_id,
        len(taxonomy),
        len(bout_items),
        sum(item.category == "bout_format.unresolved_cross_source_match" for item in bout_items),
        output_dir,
    )


def _consolidate_queue(
    queues: tuple[tuple[str, tuple[dict[str, str], ...]], ...],
    *,
    kind: Literal["identity", "taxonomy"],
) -> tuple[ReviewerPacketItem, ...]:
    grouped: defaultdict[tuple[str, str], list[tuple[str, dict[str, str]]]] = defaultdict(list)
    for source, rows in queues:
        for row in rows:
            category = _category(kind, row["evidence"])
            raw_key = (
                _identity_key(row["raw_value"])
                if kind == "identity"
                else _text_key(row["raw_value"])
            )
            grouped[(category, raw_key)].append((source, row))
    items: list[ReviewerPacketItem] = []
    prefix = "ID" if kind == "identity" else "TAX"
    for (category, raw_key), members in sorted(grouped.items()):
        source_values = tuple(sorted(f"{source}: {row['raw_value']}" for source, row in members))
        affected_rows = sum(int(row["affected_count"]) for _, row in members)
        proposed = _proposed_action(kind, category, members)
        evidence = _evidence(members)
        review_id = _review_id(prefix, category, raw_key, source_values)
        items.append(
            ReviewerPacketItem(
                review_id=review_id,
                category=category,
                source_values=source_values,
                proposed_canonical_value_or_action=proposed,
                affected_row_count=affected_rows,
                affected_bout_count=affected_rows,
                representative_evidence=evidence,
                confidence="review_required",
                recommended_decision="defer unless source-backed evidence supports the action",
            )
        )
    return tuple(items)


def _outcome_items(path: Path) -> tuple[ReviewerPacketItem, ...]:
    items: list[ReviewerPacketItem] = []
    for payload in _read_jsonl(path):
        left = _mapping(payload.get("left_source"))
        right = _mapping(payload.get("right_source"))
        outcome = next(
            item for item in _sequence(payload.get("comparisons")) if item.get("field") == "outcome"
        )
        category = _outcome_category(outcome, left, right)
        source_values = (
            _bout_source_value(left),
            _bout_source_value(right),
        )
        evidence = (
            "Outcome: "
            f"Ultimate={outcome.get('left_value')!s} ({outcome.get('left_normalized')!s}); "
            f"UFC-DataLab={outcome.get('right_value')!s} ({outcome.get('right_normalized')!s}). "
            f"Method: Ultimate={left.get('method')!s}; UFC-DataLab={right.get('method')!s}."
        )
        review_id = _review_id(
            "OUT",
            category,
            str(left.get("source_record_key")),
            (str(right.get("source_record_key")),),
        )
        items.append(
            ReviewerPacketItem(
                review_id=review_id,
                category=category,
                source_values=source_values,
                proposed_canonical_value_or_action=(
                    "select verified outcome or defer; retain both source observations"
                ),
                affected_row_count=2,
                affected_bout_count=1,
                representative_evidence=evidence,
                confidence="review_required",
                recommended_decision="defer pending authoritative result evidence",
            )
        )
    return tuple(sorted(items, key=lambda item: item.review_id))


def _roldan_replacement_item() -> ReviewerPacketItem:
    source_values = (
        "ultimate: Roldan Sangcha-an",
        "ufc-datalab: Roldan Sangcha'an",
    )
    retired = "M3-ID-45CDDFCF91DA, M3-ID-333577CCC1AF"
    review_id = _review_id(
        "ID",
        "identity.consolidated_alias_identity",
        "roldan-sangcha-an",
        source_values,
    )
    return ReviewerPacketItem(
        review_id=review_id,
        category="identity.consolidated_alias_identity",
        source_values=source_values,
        proposed_canonical_value_or_action=(
            "create one canonical fighter: Roldan Sangcha-an; preserve aliases "
            "Roldan Sangcha-an and Roldan Sangcha'an"
        ),
        affected_row_count=4,
        affected_bout_count=4,
        representative_evidence=(
            f"Replacement for retired IDs {retired}. "
            "Both source aliases identify the same reviewed "
            "fighter; no additional identity merge is proposed."
        ),
        confidence="review_required",
        recommended_decision="approve_corrected_mapping or defer",
    )


def _taxonomy_replacement_items() -> tuple[ReviewerPacketItem, ...]:
    definitions = (
        (
            "taxonomy.division_exact_normalization",
            "ufc-datalab: Road to UFC 3 Women's Strawweight Tournament Title  Bout",
            "Road to UFC 3 Women's Strawweight Tournament Title Bout",
            1,
            "M3-TAX-257DFBD9A034",
            "approve_corrected_mapping or defer",
        ),
        (
            "taxonomy.finish_method_exact_mapping",
            "ultimate: CNC",
            "Could Not Continue",
            6,
            "M3-TAX-5ED353D0D548",
            "approve_corrected_mapping or defer",
        ),
        (
            "taxonomy.finish_method_exact_mapping",
            "ultimate: M-DEC",
            "Decision - Majority",
            104,
            "M3-TAX-4C9107B3AF63",
            "approve_corrected_mapping or defer",
        ),
        (
            "taxonomy.finish_method_exact_mapping",
            "ultimate: S-DEC",
            "Decision - Split",
            1398,
            "M3-TAX-D686698596B7",
            "approve_corrected_mapping or defer",
        ),
        (
            "taxonomy.finish_method_exact_mapping",
            "ultimate: SUB",
            "Submission",
            2520,
            "M3-TAX-8C3A077E1E51",
            "approve_corrected_mapping or defer",
        ),
        (
            "taxonomy.finish_method_exact_mapping",
            "ultimate: U-DEC",
            "Decision - Unanimous",
            5362,
            "M3-TAX-52281807F1B7",
            "approve_corrected_mapping or defer",
        ),
        (
            "taxonomy.missing_stance_policy",
            "ultimate: <missing> || ufc-datalab: <missing>",
            "preserve missing stance as null; never infer Orthodox, Southpaw, or Switch; "
            "model-ready use only via null handling or missing indicator",
            8743,
            "M3-TAX-793554275A41",
            "preserve_null or defer",
        ),
    )
    items: list[ReviewerPacketItem] = []
    for category, source_value, proposal, count, retired_id, recommendation in definitions:
        values = tuple(source_value.split(" || "))
        review_id = _review_id("TAX", category, proposal, values)
        items.append(
            ReviewerPacketItem(
                review_id=review_id,
                category=category,
                source_values=values,
                proposed_canonical_value_or_action=proposal,
                affected_row_count=count,
                affected_bout_count=count,
                representative_evidence=(
                    f"Replacement for retired ID {retired_id}; exact reviewer correction."
                ),
                confidence="review_required",
                recommended_decision=recommendation,
            )
        )
    return tuple(items)


def _bout_format_items(*, ultimate_csv: Path, datalab_csv: Path) -> tuple[ReviewerPacketItem, ...]:
    datalab_rows = _read_datalab_round_rows(datalab_csv)
    items = [
        *_datalab_special_format_items(datalab_rows),
        *_ultimate_four_round_items(ultimate_csv, datalab_rows),
    ]
    return tuple(sorted(items, key=lambda item: item.review_id))


@dataclass(frozen=True, slots=True)
class _DataLabRoundRow:
    row_number: int
    event_date: str
    event_name: str
    red_name: str
    blue_name: str
    time_format: str
    scheduled_rounds: int | None
    finish_round: int | None


def _read_datalab_round_rows(path: Path) -> tuple[_DataLabRoundRow, ...]:
    rows: list[_DataLabRoundRow] = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row_number, row in enumerate(csv.DictReader(stream, delimiter=";"), start=2):
            rows.append(
                _DataLabRoundRow(
                    row_number=row_number,
                    event_date=row["event_date"],
                    event_name=row["event_name"],
                    red_name=row["red_fighter_name"],
                    blue_name=row["blue_fighter_name"],
                    time_format=row["time_format"].strip(),
                    scheduled_rounds=_parse_time_format_rounds(row["time_format"]),
                    finish_round=_leading_integer(row["round"]),
                )
            )
    return tuple(rows)


def profile_ufc_datalab_round_semantics(path: Path) -> RoundSemanticsProfile:
    """Profile raw bout-format semantics without changing any source record.

    A violation is deliberately narrow: a numeric finish round greater than
    the numeric scheduled-round maximum encoded in ``time_format``.  Overtime
    segments extend that maximum; ``No Time Limit`` remains non-numeric.
    """

    rows = _read_datalab_round_rows(path)
    violations = tuple(row for row in rows if _is_impossible_finish_round(row))
    special = tuple(row for row in rows if _is_special_format(row.time_format))
    return RoundSemanticsProfile(
        row_count=len(rows),
        unique_bout_count=len(_unique_datalab_bouts(list(rows))),
        violation_row_count=len(violations),
        violation_unique_bout_count=len(_unique_datalab_bouts(list(violations))),
        special_format_row_count=len(special),
        special_format_unique_bout_count=len(_unique_datalab_bouts(list(special))),
    )


def _datalab_special_format_items(
    rows: tuple[_DataLabRoundRow, ...],
) -> tuple[ReviewerPacketItem, ...]:
    groups: defaultdict[str, list[_DataLabRoundRow]] = defaultdict(list)
    for row in rows:
        if _is_special_format(row.time_format):
            groups[row.time_format].append(row)
    items: list[ReviewerPacketItem] = []
    for time_format, group in sorted(groups.items()):
        parsed = {row.scheduled_rounds for row in group}
        if len(parsed) != 1 or None in parsed:
            raise ValueError(f"inconsistent special-format parser result: {time_format}")
        scheduled_rounds = next(iter(parsed))
        assert scheduled_rounds is not None
        unique_bouts = _unique_datalab_bouts(group)
        examples = "; ".join(
            f"row-{row.row_number} {row.red_name} vs {row.blue_name} ({row.event_date})"
            for row in group[:3]
        )
        source_values = (f"ufc-datalab: time_format={time_format}",)
        review_id = _review_id("BOUT", "bout_format.special_format", time_format, source_values)
        items.append(
            ReviewerPacketItem(
                review_id=review_id,
                category="bout_format.special_format",
                source_values=source_values,
                proposed_canonical_value_or_action=(
                    f"preserve explicit special format; scheduled rounds={scheduled_rounds}"
                ),
                affected_row_count=len(group),
                affected_bout_count=len(unique_bouts),
                representative_evidence=(
                    f"raw_rows={len(group)}; unique_bouts={len(unique_bouts)}; {examples}. "
                    "All finish rounds are within parsed schedule. Retires "
                    "M3-TAX-398D1F4ABE63/M3-TAX-FD0AB57445C9 as aggregate detector defects."
                ),
                confidence="review_required",
                recommended_decision="approve_corrected_mapping or defer",
            )
        )
    return tuple(items)


def _ultimate_four_round_items(
    path: Path, datalab_rows: tuple[_DataLabRoundRow, ...]
) -> tuple[ReviewerPacketItem, ...]:
    index: defaultdict[tuple[str, tuple[str, str]], list[_DataLabRoundRow]] = defaultdict(list)
    for datalab_row in datalab_rows:
        index[
            _bout_key(
                _iso_date(datalab_row.event_date), datalab_row.red_name, datalab_row.blue_name
            )
        ].append(datalab_row)
    confirmed: list[tuple[int, dict[str, str], _DataLabRoundRow]] = []
    unresolved: list[tuple[int, dict[str, str]]] = []
    items: list[ReviewerPacketItem] = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row_number, ultimate_row in enumerate(csv.DictReader(stream), start=2):
            if ultimate_row["no_of_rounds"].strip() not in {"4", "4.0"}:
                continue
            matches = index[
                _bout_key(
                    ultimate_row["date"], ultimate_row["R_fighter"], ultimate_row["B_fighter"]
                )
            ]
            special = [
                candidate
                for candidate in matches
                if candidate.time_format == "3 Rnd + OT (5-5-5-5)"
                and candidate.scheduled_rounds == 4
            ]
            if len(special) == 1:
                confirmed.append((row_number, ultimate_row, special[0]))
            else:
                unresolved.append((row_number, ultimate_row))
    if confirmed:
        examples = "; ".join(
            f"ultimate row-{row_number} {row['R_fighter']} vs {row['B_fighter']} -> "
            f"DataLab row-{match.row_number} {match.time_format}"
            for row_number, row, match in confirmed[:3]
        )
        source_values = ("ultimate: no_of_rounds=4", "ufc-datalab: 3 Rnd + OT (5-5-5-5)")
        review_id = _review_id(
            "BOUT",
            "bout_format.cross_source_four_round_confirmation",
            "ultimate-four",
            source_values,
        )
        items.append(
            ReviewerPacketItem(
                review_id=review_id,
                category="bout_format.cross_source_four_round_confirmation",
                source_values=source_values,
                proposed_canonical_value_or_action=(
                    "preserve scheduled rounds=4 as an explicit 3-round-plus-overtime format"
                ),
                affected_row_count=len(confirmed),
                affected_bout_count=len(confirmed),
                representative_evidence=(
                    f"{len(confirmed)} Ultimate rows have one matching "
                    "DataLab special-format bout; "
                    f"{examples}. "
                    "Retires M3-TAX-935D1986C187 without treating the format as invalid."
                ),
                confidence="review_required",
                recommended_decision="approve_corrected_mapping or defer",
            )
        )
    for row_number, ultimate_row in unresolved:
        source_values = (
            f"ultimate: ufc-master.csv:row-{row_number}",
            f"fighters={ultimate_row['R_fighter']} vs {ultimate_row['B_fighter']}",
        )
        review_id = _review_id(
            "BOUT", "bout_format.unresolved_cross_source_match", str(row_number), source_values
        )
        items.append(
            ReviewerPacketItem(
                review_id=review_id,
                category="bout_format.unresolved_cross_source_match",
                source_values=source_values,
                proposed_canonical_value_or_action=(
                    "retain only if an explicit reviewed cross-source identity/bout match is "
                    "supplied; "
                    "otherwise exclude affected record"
                ),
                affected_row_count=1,
                affected_bout_count=1,
                representative_evidence=(
                    f"date={ultimate_row['date']}; raw scheduled rounds="
                    f"{ultimate_row['no_of_rounds']}; "
                    f"finish_round={ultimate_row.get('finish_round', '')}; "
                    "no exact normalized cross-source pair."
                ),
                confidence="review_required",
                recommended_decision="exclude_affected_record or defer",
            )
        )
    return tuple(items)


def _leading_integer(value: str) -> int | None:
    digits = "".join(character for character in value.strip() if character.isdecimal())
    return int(digits) if digits else None


def _parse_time_format_rounds(value: str) -> int | None:
    normalized = value.strip()
    if normalized.casefold() == "no time limit":
        return None
    if "Rnd" not in normalized:
        return None
    first = _leading_integer(normalized.split("Rnd", maxsplit=1)[0])
    if first is None:
        return None
    if "+ 2OT" in normalized:
        return first + 2
    if "+ OT" in normalized:
        return first + 1
    return first


def _is_special_format(value: str) -> bool:
    return "Rnd +" in value and "OT" in value


def _is_impossible_finish_round(row: _DataLabRoundRow) -> bool:
    return (
        row.scheduled_rounds is not None
        and row.finish_round is not None
        and row.finish_round > row.scheduled_rounds
    )


def _iso_date(value: str) -> str:
    day, month, year = value.split("/", maxsplit=2)
    return f"{year}-{month}-{day}"


def _bout_key(date_value: str, first: str, second: str) -> tuple[str, tuple[str, str]]:
    normalized = sorted((_identity_key(first), _identity_key(second)))
    return date_value, (normalized[0], normalized[1])


def _unique_datalab_bouts(rows: list[_DataLabRoundRow]) -> set[tuple[str, tuple[str, str]]]:
    return {_bout_key(_iso_date(row.event_date), row.red_name, row.blue_name) for row in rows}


def _round_semantics_audit_markdown(path: Path) -> str:
    rows = _read_datalab_round_rows(path)
    profile = profile_ufc_datalab_round_semantics(path)
    combinations: defaultdict[tuple[str, int | None, int | None], int] = defaultdict(int)
    for row in rows:
        combinations[(row.time_format, row.scheduled_rounds, row.finish_round)] += 1
    samples = _round_audit_samples(rows)
    row_counts_by_bout: defaultdict[tuple[str, tuple[str, str]], int] = defaultdict(int)
    for row in rows:
        row_counts_by_bout[_bout_key(_iso_date(row.event_date), row.red_name, row.blue_name)] += 1
    repeated_bout_count = sum(count > 1 for count in row_counts_by_bout.values())
    lines = [
        "# UFC-DataLab round-semantics detector audit",
        "",
        "The raw file has one aggregate bout row per record, not per-round or fighter-side rows. "
        f"Rows: {profile.row_count}; unique unordered date/fighter bouts: "
        f"{profile.unique_bout_count}; finish-round violations: "
        f"{profile.violation_row_count} rows / {profile.violation_unique_bout_count} bouts. "
        f"Explicit overtime formats: {profile.special_format_row_count} rows / "
        f"{profile.special_format_unique_bout_count} bouts.",
        "",
        "| Raw column | Parsed type | Example raw values | Intended meaning | "
        "Parser / null handling | Format assumption |",
        "| --- | --- | --- | --- | --- | --- |",
        "| `time_format` | `int / null` | `3 Rnd (5-5-5)`; `3 Rnd + OT (5-5-5-5)`; "
        "`No Time Limit` | scheduled bout format / maximum rounds | parse leading `N Rnd`; "
        "add one or two for OT; `No Time Limit` -> null | formatted bout structure, "
        "not elapsed time |",
        "| `round` | `int / null` | `1`; `2`; `3`; `5` | round in which bout ended | "
        "leading integer; blank -> null | "
        "round ordinal, not a per-round-stat record |",
        "| `event_date` | raw `dd/mm/yyyy` / derived ISO date | `13/04/2024` | "
        "event date for dedupe key | "
        "converted only for comparison; raw retained | calendar date, not a duration |",
        "| `red_fighter_name`, `blue_fighter_name` | normalized string pair for dedupe only | "
        "`ALEX PEREIRA`; `JAMAHAL HILL` | unordered fighter pair for bout key | "
        "Unicode/text identity key; "
        "raw names retained | neither column is a fighter-side round-stat row |",
        "",
        "The detector rule is `finish_round > parsed_scheduled_rounds` only when both values are "
        "numeric. There is no raw `scheduled_rounds` column: the parsed value is derived solely "
        "from `time_format`. There are no flagged rows, so the requested flagged-row profile by "
        "event date and per-bout row count is empty. Source dedupe finds "
        f"{repeated_bout_count} repeated unordered bout key(s); those are retained as raw rows but "
        "cannot create duplicate review decisions.",
        "",
        "## Top raw-format combinations",
        "",
        "| Raw `time_format` | Parsed scheduled rounds | Finish round | Rows | Detector result |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for (time_format, scheduled, finish), count in sorted(
        combinations.items(), key=lambda item: (-item[1], item[0])
    )[:20]:
        result = (
            "flag"
            if _is_impossible_finish_round(
                _DataLabRoundRow(0, "", "", "", "", time_format, scheduled, finish)
            )
            else "valid"
        )
        lines.append(f"| {time_format} | {scheduled or ''} | {finish or ''} | {count} | {result} |")
    lines.extend(
        [
            "",
            "## Representative cases",
            "",
            "| Class | Source row | Fighters | Event / date | Raw format | Parsed scheduled | "
            "Finish round | Expected detector result |",
            "| --- | ---: | --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for label, row in samples:
        expected = "flag" if _is_impossible_finish_round(row) else "not flagged"
        lines.append(
            f"| {label} | {row.row_number} | {row.red_name} vs {row.blue_name} | "
            f"{row.event_name} / {row.event_date} | {row.time_format} | "
            f"{row.scheduled_rounds or ''} | {row.finish_round or ''} | {expected} |"
        )
    return "\n".join(lines) + "\n"


def _ultimate_four_round_audit_markdown(ultimate_csv: Path, datalab_csv: Path) -> str:
    """List every Ultimate raw-four-round record and its deterministic evidence."""

    datalab_rows = _read_datalab_round_rows(datalab_csv)
    index: defaultdict[tuple[str, tuple[str, str]], list[_DataLabRoundRow]] = defaultdict(list)
    for datalab_row in datalab_rows:
        index[
            _bout_key(
                _iso_date(datalab_row.event_date), datalab_row.red_name, datalab_row.blue_name
            )
        ].append(datalab_row)
    lines = [
        "# Ultimate four-round record audit",
        "",
        "Ultimate has no event-name column. Its raw `no_of_rounds=4` is assessed per source row "
        "against an exact normalized date-and-unordered-fighter DataLab match; no fuzzy fighter "
        "link is used. `3 Rnd + OT (5-5-5-5)` is an accurately representable four-round special "
        "format, not a parser error.",
        "",
        "| Ultimate row | Bout / date | Weight class / location | Raw rounds | Raw finish round | "
        "DataLab evidence | Finding / recommended action |",
        "| ---: | --- | --- | ---: | --- | --- | --- |",
    ]
    with ultimate_csv.open(encoding="utf-8-sig", newline="") as stream:
        for row_number, ultimate_row in enumerate(csv.DictReader(stream), start=2):
            if ultimate_row["no_of_rounds"].strip() not in {"4", "4.0"}:
                continue
            matches = index[
                _bout_key(
                    ultimate_row["date"], ultimate_row["R_fighter"], ultimate_row["B_fighter"]
                )
            ]
            special = [
                candidate
                for candidate in matches
                if candidate.time_format == "3 Rnd + OT (5-5-5-5)"
                and candidate.scheduled_rounds == 4
            ]
            bout = (
                f"{ultimate_row['R_fighter']} vs {ultimate_row['B_fighter']} / "
                f"{ultimate_row['date']}"
            )
            metadata = (
                f"{ultimate_row.get('weight_class', '')} / {ultimate_row.get('location', '')}"
            )
            if len(special) == 1:
                candidate = special[0]
                evidence = (
                    f"DataLab row-{candidate.row_number}: {candidate.event_name}; "
                    f"{candidate.time_format}; finish round={candidate.finish_round}"
                )
                finding = "legitimate special format; preserve as explicit four-round format"
            else:
                evidence = "no exact normalized date-and-fighter DataLab match"
                finding = "unresolved cross-source identity/bout match; exclude or defer"
            lines.append(
                f"| {row_number} | {bout} | {metadata} | {ultimate_row['no_of_rounds']} | "
                f"{ultimate_row.get('finish_round', '')} | {evidence} | {finding} |"
            )
    return "\n".join(lines) + "\n"


def _round_audit_samples(
    rows: tuple[_DataLabRoundRow, ...],
) -> tuple[tuple[str, _DataLabRoundRow], ...]:
    groups = (
        (
            "three-round decision",
            lambda row: row.time_format == "3 Rnd (5-5-5)" and row.finish_round == 3,
        ),
        (
            "three-round first-round finish",
            lambda row: row.time_format == "3 Rnd (5-5-5)" and row.finish_round == 1,
        ),
        (
            "three-round second-round finish",
            lambda row: row.time_format == "3 Rnd (5-5-5)" and row.finish_round == 2,
        ),
        ("five-round bout", lambda row: row.time_format == "5 Rnd (5-5-5-5-5)"),
        ("historical special format", lambda row: _is_special_format(row.time_format)),
    )
    selected: list[tuple[str, _DataLabRoundRow]] = []
    for label, predicate in groups:
        selected.extend((label, row) for row in [item for item in rows if predicate(item)][:6])
    # The first four groups cover 24; keep six special-format examples for 30 total.
    return tuple(selected[:30])


def _correction_markdown(
    identity: ReviewerPacketItem,
    taxonomy: tuple[ReviewerPacketItem, ...],
    bouts: tuple[ReviewerPacketItem, ...],
    retired: tuple[str, ...],
) -> str:
    header = (
        "# M3 corrected reviewer packet\n\n"
        "This packet replaces only the listed deferred proposals. "
        "The retired IDs cannot be imported. Review each replacement independently; "
        "no raw or canonical data is modified by this packet.\n\n"
        f"Retired review IDs: {', '.join(retired)}.\n"
    )
    return (
        header
        + _markdown_section("Replacement identity decision", (identity,))
        + _markdown_section("Replacement taxonomy decisions", taxonomy)
        + _markdown_section("Bout-level format decisions", bouts)
    )


def _read_markdown_queue(path: Path) -> tuple[dict[str, str], ...]:
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| review-"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 7:
            raise ValueError(f"invalid reviewer queue row in {path}: {line}")
        rows.append(
            dict(
                zip(
                    (
                        "source_review_id",
                        "raw_value",
                        "proposed_value",
                        "affected_count",
                        "confidence",
                        "evidence",
                        "recommended_action",
                    ),
                    cells,
                    strict=True,
                )
            )
        )
    if not rows:
        raise ValueError(f"reviewer queue has no rows: {path}")
    return tuple(rows)


def _category(kind: str, evidence: str) -> str:
    if kind == "identity" and "Bruno Silva" in evidence:
        return "identity.homonym_preservation"
    if kind == "identity":
        return "identity.alias_candidate"
    return f"taxonomy.{_text_key(evidence).replace(' ', '_')}"


def _proposed_action(kind: str, category: str, members: list[tuple[str, dict[str, str]]]) -> str:
    if category == "identity.homonym_preservation":
        return "preserve separate Flyweight and Middleweight Bruno Silva identities; do not merge"
    proposals = [row["proposed_value"] for _, row in members if row["proposed_value"]]
    if not proposals:
        return "defer; no canonical value proposed"
    # Prefer an explicit known-variant display over a folded comparison key.
    preferred = next(
        (
            row["proposed_value"]
            for _, row in members
            if "known punctuation" in row["evidence"] and row["proposed_value"]
        ),
        proposals[0],
    )
    if kind == "identity":
        return (
            f"review source-backed alias/display mapping to: {preferred}; "
            "do not merge identities automatically"
        )
    return f"review exact taxonomy mapping to: {preferred}"


def _evidence(members: list[tuple[str, dict[str, str]]]) -> str:
    examples = "; ".join(
        f"{source} {row['source_review_id']}: {row['evidence']}" for source, row in members[:3]
    )
    return examples


def _packet_markdown(
    identity: tuple[ReviewerPacketItem, ...],
    taxonomy: tuple[ReviewerPacketItem, ...],
    outcomes: tuple[ReviewerPacketItem, ...],
) -> str:
    header = (
        "# M3 reviewer packet\n\n"
        "This packet is review-only. No entry applies an alias, taxonomy mapping, outcome, "
        "or canonical record automatically. Import records an append-only reviewed decision; "
        "separate canonical validation remains required.\n\n"
        "Bruno Silva is explicitly preserved as separate Flyweight and Middleweight identities. "
        "Do not approve a fuzzy identity merge without source-backed bout, weight-class, "
        "physical-profile, or equivalent corroborating evidence.\n"
    )
    return (
        header
        + _markdown_section("Identity decisions", identity)
        + _markdown_section("Taxonomy decisions", taxonomy)
        + _markdown_section("Residual material outcome conflicts", outcomes)
    )


def _markdown_section(title: str, items: tuple[ReviewerPacketItem, ...]) -> str:
    lines = [
        f"\n## {title}\n",
        "| Review ID | Category | Source values | Proposed action | Rows / bouts | Evidence | "
        "Confidence | Recommended decision | Reviewer decision | Reviewer notes |",
        "| --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- |",
    ]
    for item in items:
        lines.append(
            "| "
            + " | ".join(
                (
                    item.review_id,
                    item.category,
                    _markdown_cell("; ".join(item.source_values)),
                    _markdown_cell(item.proposed_canonical_value_or_action),
                    f"{item.affected_row_count} / {item.affected_bout_count}",
                    _markdown_cell(item.representative_evidence),
                    item.confidence,
                    _markdown_cell(item.recommended_decision),
                    "",
                    "",
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _write_csv_once_or_same(path: Path, items: tuple[ReviewerPacketItem, ...]) -> None:
    rows = [item.csv_row() for item in items]
    content = _csv_content(rows)
    _write_once_or_same(path, content)


def _csv_content(rows: list[dict[str, str]]) -> str:
    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=_DECISION_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def _write_once_or_same(path: Path, content: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise RuntimeError(f"reviewer artifact already exists with different content: {path}")
    if not path.exists():
        path.write_text(content, encoding="utf-8", newline="\n")


def _packet_registry(packet_dir: Path) -> dict[str, dict[str, str]]:
    registry: dict[str, dict[str, str]] = {}
    files = tuple(sorted(packet_dir.glob("*decisions.csv")))
    if not files:
        raise ReviewerDecisionImportError(f"no decision CSV files found: {packet_dir}")
    for path in files:
        for row in _read_decision_csv(path):
            _validate_packet_row(row)
            if row["review_id"] in registry:
                raise ReviewerDecisionImportError(f"duplicate packet review ID: {row['review_id']}")
            registry[row["review_id"]] = row
    return registry


def _retired_review_ids(packet_dir: Path) -> frozenset[str]:
    path = packet_dir / "m3_retired_review_ids.json"
    if not path.exists():
        return frozenset()
    payload = _mapping(json.loads(path.read_text(encoding="utf-8")))
    values = payload.get("retired_review_ids")
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ReviewerDecisionImportError(f"invalid retired-review manifest: {path}")
    return frozenset(values)


def _read_decision_csv(path: Path) -> tuple[dict[str, str], ...]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _DECISION_COLUMNS:
            raise ReviewerDecisionImportError(f"invalid decision CSV header: {path}")
        return tuple({key: (value or "") for key, value in row.items()} for row in reader)


def _validate_submitted_row(row: dict[str, str], registry: dict[str, dict[str, str]]) -> None:
    review_id = row["review_id"]
    expected = registry.get(review_id)
    if expected is None:
        raise ReviewerDecisionImportError(f"unknown review ID: {review_id}")
    immutable = (
        "category",
        "source_values",
        "proposed_canonical_value_or_action",
        "affected_row_count",
        "affected_bout_count",
        "representative_evidence",
        "confidence",
        "recommended_decision",
        "source_evidence_sha256",
    )
    if any(row[key] != expected[key] for key in immutable):
        raise ReviewerDecisionImportError(f"stale source evidence for review ID: {review_id}")
    _validate_packet_row(expected)
    decision = row["reviewer_decision"].strip()
    allowed = _OUTCOME_DECISIONS if row["category"].startswith("outcome.") else _STANDARD_DECISIONS
    if decision not in allowed:
        raise ReviewerDecisionImportError(f"invalid reviewer decision for review ID: {review_id}")
    if not row["reviewer"].strip():
        raise ReviewerDecisionImportError(f"missing reviewer for review ID: {review_id}")
    if not row["reviewer_notes"].strip():
        raise ReviewerDecisionImportError(f"missing rationale for review ID: {review_id}")
    try:
        timestamp = datetime.fromisoformat(row["decision_timestamp"])
    except ValueError as error:
        raise ReviewerDecisionImportError(
            f"invalid timestamp for review ID: {review_id}"
        ) from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ReviewerDecisionImportError(
            f"timestamp must include timezone for review ID: {review_id}"
        )


def _validate_packet_row(row: dict[str, str]) -> None:
    """Verify an issued row's evidence hash from its immutable payload."""

    try:
        item = ReviewerPacketItem(
            review_id=row["review_id"],
            category=row["category"],
            source_values=tuple(row["source_values"].split(" || ")),
            proposed_canonical_value_or_action=row["proposed_canonical_value_or_action"],
            affected_row_count=int(row["affected_row_count"]),
            affected_bout_count=int(row["affected_bout_count"]),
            representative_evidence=row["representative_evidence"],
            confidence=row["confidence"],
            recommended_decision=row["recommended_decision"],
        )
    except (KeyError, ValueError) as error:
        raise ReviewerDecisionImportError(
            f"invalid issued reviewer packet row: {row.get('review_id', '<unknown>')}"
        ) from error
    if row["source_evidence_sha256"] != item.source_evidence_sha256:
        raise ReviewerDecisionImportError(
            f"stale source evidence for review ID: {row['review_id']}"
        )


def _read_ledger(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    records: dict[str, dict[str, str]] = {}
    for payload in _read_jsonl(path):
        review_id = str(payload.get("review_id", ""))
        if not review_id or review_id in records:
            raise ReviewerDecisionImportError(f"invalid imported-decision ledger: {path}")
        records[review_id] = {key: str(value) for key, value in payload.items()}
    return records


def _ledger_record(row: dict[str, str]) -> dict[str, str]:
    return {
        "record_type": "m3_review_decision_recorded_pending_canonical_validation",
        "packet_version": PACKET_VERSION,
        **{key: row[key] for key in _DECISION_COLUMNS},
    }


def _decision_identity(record: dict[str, str]) -> tuple[str, ...]:
    return tuple(record.get(key, "") for key in _DECISION_COLUMNS)


def _read_jsonl(path: Path) -> tuple[dict[str, object], ...]:
    return tuple(
        _mapping(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _sequence(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("expected JSON object list")
    return value


def _identity_key(value: str) -> str:
    return normalize_fighter_alias(value).normalized_value


def _text_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _review_id(prefix: str, category: str, key: str, source_values: tuple[str, ...]) -> str:
    digest = _sha256_json({"category": category, "key": key, "source_values": source_values})[
        :12
    ].upper()
    return f"M3-{prefix}-{digest}"


def _outcome_category(
    outcome: dict[str, object], left: dict[str, object], right: dict[str, object]
) -> str:
    values = {str(outcome.get("left_normalized")), str(outcome.get("right_normalized"))}
    methods = {str(left.get("method", "")).casefold(), str(right.get("method", "")).casefold()}
    if any(value.startswith("uninterpreted:") for value in values):
        return "outcome.source_parsing"
    if "no_contest" in values:
        return "outcome.no_contest_vs_winner"
    if "draw" in values:
        return "outcome.draw_vs_winner"
    if "overturned" in methods:
        return "outcome.overturned_result"
    return "outcome.winner_disagreement"


def _bout_source_value(source: dict[str, object]) -> str:
    return (
        f"{source.get('source')}: {source.get('source_record_key')} | "
        f"{source.get('fight_date')} | {source.get('red_name')} vs {source.get('blue_name')} | "
        f"outcome={source.get('outcome')} | method={source.get('method')}"
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
