"""Review-only dual-source reconciliation and strictly-prior history proposals.

This module deliberately compares observations rather than producing a merged
bout.  Normalized values are comparison evidence only: the two source values
remain intact in every reconciliation record and artifact.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

import polars as pl

from ufc_predictor.identity.normalize import normalize_fighter_alias


class CandidateReconciliationClass(StrEnum):
    """A non-mutating disposition for one candidate reconciliation."""

    EQUIVALENT = "equivalent_after_deterministic_normalization"
    SOFT_METADATA = "soft_metadata_disagreement"
    MISSING_ON_ONE_SOURCE = "missing_on_one_source"
    POST_FIGHT_DETAIL = "post_fight_detail_disagreement"
    MATERIAL_OUTCOME = "material_outcome_conflict"
    MATERIAL_IDENTITY = "material_identity_conflict"
    AMBIGUOUS = "ambiguous_bout_match"


@dataclass(frozen=True, slots=True)
class CandidateBout:
    source: str
    source_record_key: str
    fight_date: date
    red_name: str
    blue_name: str
    outcome: str | None
    method: str | None
    finish_round: int | None
    finish_time: str | None
    scheduled_rounds: int | None
    division: str | None
    event_name: str | None
    location: str | None


@dataclass(frozen=True, slots=True)
class FieldComparison:
    field: str
    left_value: object | None
    right_value: object | None
    left_normalized: object | None
    right_normalized: object | None
    rule_id: str | None
    status: str


@dataclass(frozen=True, slots=True)
class CandidateReconciliation:
    classification: CandidateReconciliationClass
    left: CandidateBout | None
    right: CandidateBout | None
    comparisons: tuple[FieldComparison, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateReconciliationReport:
    # Legacy aggregate counts are retained for callers and historical reports.
    exact: int
    normalized_exact: int
    corner_swapped: int
    probable: int
    ambiguous: int
    conflict: int
    ultimate_only: int
    datalab_only: int
    deterministically_equivalent: int
    soft_metadata_conflict: int
    missing_value_only: int
    post_fight_only_conflict: int
    post_fight_detail_conflict: int
    material_identity_conflict: int
    material_outcome_conflict: int
    ambiguous_match: int
    human_review_queue_size: int
    original_conflict_count: int
    disagreeing_fields: dict[str, int]
    disagreeing_field_combinations: dict[str, int]
    source_value_variations: dict[str, int]


_FIELD_ORDER = (
    "fighter_identity",
    "corner_orientation",
    "outcome",
    "event_date",
    "event_name",
    "weight_class",
    "scheduled_rounds",
    "finish_method",
    "finish_round",
    "finish_time",
    "location",
)
_SOFT_METADATA_FIELDS = frozenset(
    {"event_date", "event_name", "weight_class", "scheduled_rounds", "location"}
)
_POST_FIGHT_FIELDS = frozenset({"finish_method", "finish_round", "finish_time"})


def reconcile_ultimate_and_datalab_candidates(
    *, ultimate_csv: Path, datalab_parquet: Path
) -> CandidateReconciliationReport:
    """Profile source observations without applying identity/taxonomy decisions."""

    records = reconcile_ultimate_and_datalab_candidate_records(
        ultimate_csv=ultimate_csv, datalab_parquet=datalab_parquet
    )
    return _report(records)


def reconcile_ultimate_and_datalab_candidate_records(
    *, ultimate_csv: Path, datalab_parquet: Path
) -> tuple[CandidateReconciliation, ...]:
    """Return stable, complete evidence records for the two local sources."""

    ultimate = tuple(_ultimate_bouts(ultimate_csv))
    datalab = tuple(_datalab_bouts(datalab_parquet))
    index: defaultdict[tuple[date, tuple[str, str]], list[CandidateBout]] = defaultdict(list)
    for bout in datalab:
        index[_candidate_key(bout)].append(bout)
    used_right: set[str] = set()
    records: list[CandidateReconciliation] = []
    for left in ultimate:
        candidates = index.get(_candidate_key(left), [])
        if not candidates:
            records.append(_missing_record(left, None))
            continue
        if len(candidates) > 1:
            used_right.update(item.source_record_key for item in candidates)
            records.append(
                CandidateReconciliation(
                    CandidateReconciliationClass.AMBIGUOUS,
                    left,
                    None,
                    (),
                    tuple(sorted(item.source_record_key for item in candidates)),
                )
            )
            continue
        right = candidates[0]
        used_right.add(right.source_record_key)
        records.append(_compare_bouts(left, right))
    records.extend(
        _missing_record(None, right)
        for right in datalab
        if right.source_record_key not in used_right
    )
    return tuple(records)


def write_reconciliation_artifacts(
    *, ultimate_csv: Path, datalab_parquet: Path, output_dir: Path
) -> CandidateReconciliationReport:
    """Write deterministic audit artifacts; never write to either source path.

    ``summary.json`` profiles every field and combination.  The two JSONL
    files retain parallel source values, normalized comparison evidence, and
    rule identifiers for all non-equivalent candidates.
    """

    records = reconcile_ultimate_and_datalab_candidate_records(
        ultimate_csv=ultimate_csv, datalab_parquet=datalab_parquet
    )
    report = _report(records)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json_once_or_same(output_dir / "reconciliation_summary.json", _summary_payload(report))
    non_review = tuple(
        record
        for record in records
        if record.classification
        in {
            CandidateReconciliationClass.EQUIVALENT,
            CandidateReconciliationClass.SOFT_METADATA,
            CandidateReconciliationClass.MISSING_ON_ONE_SOURCE,
            CandidateReconciliationClass.POST_FIGHT_DETAIL,
        }
    )
    review = tuple(
        record
        for record in records
        if record.classification
        in {
            CandidateReconciliationClass.MATERIAL_IDENTITY,
            CandidateReconciliationClass.MATERIAL_OUTCOME,
            CandidateReconciliationClass.AMBIGUOUS,
        }
    )
    _write_jsonl_once_or_same(output_dir / "deterministic_or_soft_conflicts.jsonl", non_review)
    _write_jsonl_once_or_same(output_dir / "residual_material_conflicts.jsonl", review)
    return report


def generate_candidate_prior_history_features(
    *, datalab_parquet: Path, output_path: Path
) -> tuple[int, int]:
    """Publish candidate-keyed historical features using dates strictly before T.

    The output is review-only because candidate names are not durable identity
    decisions. Current-fight statistics are added to history only after all
    targets on the same event date have been materialized.
    """

    _DETAILS_BY_RECORD.clear()
    bouts = tuple(sorted(_datalab_bouts(datalab_parquet), key=lambda bout: bout.fight_date))
    by_date: defaultdict[date, list[CandidateBout]] = defaultdict(list)
    for bout in bouts:
        by_date[bout.fight_date].append(bout)
    history: defaultdict[str, list[tuple[str, dict[str, float]]]] = defaultdict(list)
    rows: list[dict[str, object]] = []
    for fight_date in sorted(by_date):
        same_date = by_date[fight_date]
        for bout in same_date:
            red_key, blue_key = _name_key(bout.red_name), _name_key(bout.blue_name)
            red = _history_features(history[red_key])
            blue = _history_features(history[blue_key])
            row: dict[str, object] = {
                "source_record_key": bout.source_record_key,
                "fight_date": fight_date,
                "red_candidate_name": bout.red_name,
                "blue_candidate_name": bout.blue_name,
                "identity_status": "candidate_unreviewed",
                "temporal_policy": "event_date_strictly_before_target",
            }
            for name, value in red.items():
                row[f"red_{name}"] = value
                row[f"blue_{name}"] = blue[name]
                row[f"difference_{name}"] = value - blue[name]
            rows.append(row)
        for bout in same_date:
            details = _datalab_details(bout)
            history[_name_key(bout.red_name)].append(
                (_red_result(bout.outcome), _statistics(details, "red"))
            )
            history[_name_key(bout.blue_name)].append(
                (_blue_result(bout.outcome), _statistics(details, "blue"))
            )
    frame = pl.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        existing = pl.read_parquet(output_path)
        if existing.schema != frame.schema or existing.height != frame.height:
            raise RuntimeError(
                "candidate historical feature output conflicts with existing immutable path"
            )
    else:
        frame.write_parquet(output_path, compression="zstd")
    return frame.height, frame.width


def _report(records: tuple[CandidateReconciliation, ...]) -> CandidateReconciliationReport:
    classes = Counter(record.classification for record in records)
    fields = Counter(
        comparison.field
        for record in records
        for comparison in record.comparisons
        if comparison.status in {"disagree", "missing_left", "missing_right"}
    )
    source_variations = Counter(
        comparison.field
        for record in records
        for comparison in record.comparisons
        if comparison.status
        in {"equivalent_normalized", "disagree", "missing_left", "missing_right"}
    )
    combinations = Counter(
        "+".join(
            comparison.field
            for comparison in record.comparisons
            if comparison.status in {"disagree", "missing_left", "missing_right"}
        )
        for record in records
        if record.comparisons
        and any(
            comparison.status in {"disagree", "missing_left", "missing_right"}
            for comparison in record.comparisons
        )
    )
    missing_value_only = sum(
        record.classification is CandidateReconciliationClass.SOFT_METADATA
        and bool(record.comparisons)
        and all(
            item.status in {"equal", "equivalent_normalized", "missing_left", "missing_right"}
            for item in record.comparisons
        )
        and any(item.status in {"missing_left", "missing_right"} for item in record.comparisons)
        for record in records
    )
    equivalent = classes[CandidateReconciliationClass.EQUIVALENT]
    # Retain the previous aggregate contract: it covered only outcome, method,
    # and scheduled rounds, so it remains comparable to the recorded 4,664.
    legacy_pairs = tuple(record for record in records if record.left and record.right)
    original_conflict_count = sum(_legacy_conflict(record) for record in legacy_pairs)
    normalized_exact = sum(
        not _legacy_conflict(record)
        and record.left is not None
        and record.right is not None
        and not _legacy_exact_names(record.left, record.right)
        for record in legacy_pairs
    )
    exact = sum(not _legacy_conflict(record) for record in legacy_pairs) - normalized_exact
    material = (
        classes[CandidateReconciliationClass.MATERIAL_IDENTITY]
        + classes[CandidateReconciliationClass.MATERIAL_OUTCOME]
        + classes[CandidateReconciliationClass.AMBIGUOUS]
    )
    post_fight_only = sum(
        record.classification is CandidateReconciliationClass.POST_FIGHT_DETAIL
        and {
            item.field
            for item in record.comparisons
            if item.status in {"disagree", "missing_left", "missing_right"}
        }
        <= _POST_FIGHT_FIELDS
        for record in records
    )
    return CandidateReconciliationReport(
        exact=exact,
        normalized_exact=normalized_exact,
        corner_swapped=0,
        probable=0,
        ambiguous=classes[CandidateReconciliationClass.AMBIGUOUS],
        conflict=original_conflict_count,
        ultimate_only=sum(record.left is not None and record.right is None for record in records),
        datalab_only=sum(record.left is None and record.right is not None for record in records),
        deterministically_equivalent=equivalent,
        soft_metadata_conflict=classes[CandidateReconciliationClass.SOFT_METADATA],
        missing_value_only=missing_value_only,
        post_fight_only_conflict=post_fight_only,
        post_fight_detail_conflict=classes[CandidateReconciliationClass.POST_FIGHT_DETAIL],
        material_identity_conflict=classes[CandidateReconciliationClass.MATERIAL_IDENTITY],
        material_outcome_conflict=classes[CandidateReconciliationClass.MATERIAL_OUTCOME],
        ambiguous_match=classes[CandidateReconciliationClass.AMBIGUOUS],
        human_review_queue_size=material,
        original_conflict_count=original_conflict_count,
        disagreeing_fields={field: fields[field] for field in _FIELD_ORDER},
        disagreeing_field_combinations=dict(sorted(combinations.items())),
        source_value_variations={field: source_variations[field] for field in _FIELD_ORDER},
    )


def _compare_bouts(left: CandidateBout, right: CandidateBout) -> CandidateReconciliation:
    comparisons = tuple(_comparison(field, left, right) for field in _FIELD_ORDER)
    differences = tuple(
        item for item in comparisons if item.status in {"disagree", "missing_left", "missing_right"}
    )
    identity_difference = any(item.field == "fighter_identity" for item in differences)
    outcome_difference = any(
        item.field == "outcome" and item.status == "disagree" for item in differences
    )
    substantive = {item.field for item in differences}
    if identity_difference:
        classification = CandidateReconciliationClass.MATERIAL_IDENTITY
    elif outcome_difference:
        classification = CandidateReconciliationClass.MATERIAL_OUTCOME
    elif not differences:
        classification = CandidateReconciliationClass.EQUIVALENT
    elif substantive <= _POST_FIGHT_FIELDS | {"corner_orientation"}:
        classification = CandidateReconciliationClass.POST_FIGHT_DETAIL
    elif substantive <= _SOFT_METADATA_FIELDS | {"corner_orientation"}:
        classification = CandidateReconciliationClass.SOFT_METADATA
    elif substantive <= _SOFT_METADATA_FIELDS | _POST_FIGHT_FIELDS | {"corner_orientation"}:
        # Outcome and identity are known; post-fight disagreement remains non-blocking.
        classification = CandidateReconciliationClass.POST_FIGHT_DETAIL
    else:  # Defensive: every compared field is classified above.
        classification = CandidateReconciliationClass.MATERIAL_IDENTITY
    return CandidateReconciliation(
        classification,
        left,
        right,
        comparisons,
        ("candidate_match:exact_normalized_unordered_fighter_pair_and_event_date",),
    )


def _missing_record(
    left: CandidateBout | None, right: CandidateBout | None
) -> CandidateReconciliation:
    assert (left is None) != (right is None)
    return CandidateReconciliation(
        CandidateReconciliationClass.MISSING_ON_ONE_SOURCE,
        left,
        right,
        (),
        ("candidate_key_absent_from_other_source",),
    )


def _comparison(field: str, left: CandidateBout, right: CandidateBout) -> FieldComparison:
    left_value, right_value = _field_values(field, left, right)
    left_normalized, left_rule = _normalised_field(field, left, left_value)
    right_normalized, right_rule = _normalised_field(field, right, right_value)
    if left_value is None and right_value is None:
        status = "equal"
    elif left_value is None:
        status = "missing_left"
    elif right_value is None:
        status = "missing_right"
    elif left_normalized == right_normalized:
        status = "equal" if left_value == right_value else "equivalent_normalized"
    else:
        status = "disagree"
    rule_id = left_rule or right_rule
    return FieldComparison(
        field, left_value, right_value, left_normalized, right_normalized, rule_id, status
    )


def _field_values(
    field: str, left: CandidateBout, right: CandidateBout
) -> tuple[object | None, object | None]:
    if field == "fighter_identity":
        return (left.red_name, left.blue_name), (right.red_name, right.blue_name)
    if field == "corner_orientation":
        return (left.red_name, left.blue_name), (right.red_name, right.blue_name)
    field_name = {
        "event_date": "fight_date",
        "weight_class": "division",
        "finish_method": "method",
    }.get(field, field)
    return getattr(left, field_name), getattr(right, field_name)


def _normalised_field(
    field: str, bout: CandidateBout, value: object | None
) -> tuple[object | None, str | None]:
    if value is None:
        return None, None
    if field == "fighter_identity":
        return tuple(
            sorted((_name_key(bout.red_name), _name_key(bout.blue_name)))
        ), "REC-001.fighter_key"
    if field == "corner_orientation":
        return tuple(
            sorted((_name_key(bout.red_name), _name_key(bout.blue_name)))
        ), "REC-009.corner_orientation"
    if field == "outcome":
        return _winner_fighter(bout), "REC-002.outcome_orientation"
    if field == "event_date":
        return value.isoformat() if isinstance(value, date) else str(value), "REC-003.iso_date"
    if field == "weight_class":
        return _normalise_weight_class(str(value)), "REC-004.weight_class_alias"
    if field == "scheduled_rounds" or field == "finish_round":
        return int(str(value)), "REC-005.integer"
    if field == "finish_method":
        return _normalise_method(str(value)), "REC-006.finish_method_format"
    if field == "finish_time":
        return _normalise_clock(str(value)), "REC-007.finish_time"
    if field in {"event_name", "location"}:
        return _normalise_text(str(value)), "REC-008.text_format"
    raise ValueError(f"unknown reconciliation field: {field}")


def _candidate_key(bout: CandidateBout) -> tuple[date, tuple[str, str]]:
    first, second = sorted((_name_key(bout.red_name), _name_key(bout.blue_name)))
    return bout.fight_date, (first, second)


def _name_key(value: str) -> str:
    return normalize_fighter_alias(value).normalized_value


def _winner_fighter(bout: CandidateBout) -> str | None:
    if bout.outcome is None:
        return None
    outcome = _normalise_text(bout.outcome).replace(" ", "_")
    if outcome in {"red", "r", "red_win", "red_won", "w"}:
        return _name_key(bout.red_name)
    if outcome in {"blue", "b", "blue_win", "blue_won", "l"}:
        return _name_key(bout.blue_name)
    if outcome in {"draw", "majority_draw", "split_draw"}:
        return "draw"
    if outcome in {"nc", "no_contest", "no contest"}:
        return "no_contest"
    # An unknown source label is never silently interpreted as a result.
    return f"uninterpreted:{outcome}"


def _normalise_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^\w]+", " ", without_marks.casefold()).split())


def _normalise_weight_class(value: str) -> str:
    normalised = _normalise_text(value)
    # "Bout" is a presentation suffix in the two audited source schemas, not
    # a division decision.  No catchweight or sex/division taxonomy is inferred.
    return re.sub(r"\bbout$", "", normalised).strip()


def _normalise_method(value: str) -> str:
    # This deliberately does not collapse KO and KO/TKO, or decision subtypes.
    return _normalise_text(value).replace(" ", "_")


def _normalise_clock(value: str) -> int | str:
    match = re.fullmatch(r"\s*(\d+)\s*:\s*(\d{1,2})\s*", value)
    if match is None:
        return _normalise_text(value)
    minutes, seconds = int(match.group(1)), int(match.group(2))
    return minutes * 60 + seconds if seconds < 60 else _normalise_text(value)


def _ultimate_bouts(path: Path) -> Iterable[CandidateBout]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for index, row in enumerate(csv.DictReader(stream), start=2):
            fight_date = date.fromisoformat(row["date"].strip())
            yield CandidateBout(
                source="ultimate",
                source_record_key=f"ufc-master.csv:row-{index}",
                fight_date=fight_date,
                red_name=row["R_fighter"].strip(),
                blue_name=row["B_fighter"].strip(),
                outcome=row["Winner"].strip() or None,
                method=row["finish"].strip() or None,
                finish_round=_optional_int(row.get("finish_round", "")),
                finish_time=row.get("finish_round_time", "").strip() or None,
                scheduled_rounds=_optional_int(row["no_of_rounds"]),
                division=row["weight_class"].strip() or None,
                event_name=None,
                location=row["location"].strip() or None,
            )


def _datalab_bouts(path: Path) -> Iterable[CandidateBout]:
    for row in pl.read_parquet(path).iter_rows(named=True):
        source_record_key = str(row["source_record_key"])
        details = json.loads(str(row["detailed_statistics"]))
        _DETAILS_BY_RECORD[source_record_key] = details
        yield CandidateBout(
            source="ufc-datalab",
            source_record_key=source_record_key,
            fight_date=row["fight_date"],
            red_name=str(row["red_fighter_source_name"]),
            blue_name=str(row["blue_fighter_source_name"]),
            outcome=_optional_string(row.get("outcome_source_value")),
            method=_optional_string(row.get("method_source_value")),
            finish_round=row.get("finish_round"),
            finish_time=_optional_string(details.get("time")),
            scheduled_rounds=row.get("scheduled_rounds"),
            division=_optional_string(row.get("division_source_value")),
            event_name=_optional_string(row.get("event_name")),
            location=_optional_string(row.get("location")),
        )


def _optional_int(value: object) -> int | None:
    normalized = str(value).strip() if value is not None else ""
    if normalized.isdecimal():
        return int(normalized)
    try:
        parsed = float(normalized)
    except ValueError:
        return None
    return int(parsed) if parsed.is_integer() and parsed > 0 else None


def _optional_string(value: object | None) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None


def _summary_payload(report: CandidateReconciliationReport) -> dict[str, object]:
    payload = asdict(report)
    payload["classification_policy_version"] = "m3-reconciliation-v5"
    return payload


def _legacy_conflict(record: CandidateReconciliation) -> bool:
    assert record.left is not None and record.right is not None
    pairs = (
        (_legacy_winner_side(record.left.outcome), _legacy_winner_side(record.right.outcome)),
        (_legacy_text(record.left.method), _legacy_text(record.right.method)),
        (record.left.scheduled_rounds, record.right.scheduled_rounds),
    )
    return any(
        first is not None and second is not None and first != second for first, second in pairs
    )


def _legacy_winner_side(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.casefold()
    if normalized in {"red", "red_win"}:
        return "red"
    if normalized in {"blue", "blue_win"}:
        return "blue"
    if normalized in {"draw", "nc", "no_contest", "no contest"}:
        return normalized
    return None


def _legacy_text(value: str | None) -> str | None:
    return (
        "".join(character for character in value.casefold() if character.isalnum())
        if value
        else None
    )


def _legacy_exact_names(left: CandidateBout, right: CandidateBout) -> bool:
    return (left.red_name.casefold(), left.blue_name.casefold()) == (
        right.red_name.casefold(),
        right.blue_name.casefold(),
    )


def _record_payload(record: CandidateReconciliation) -> dict[str, object]:
    return {
        "classification": record.classification.value,
        "left_source": asdict(record.left) if record.left else None,
        "right_source": asdict(record.right) if record.right else None,
        "comparisons": [asdict(item) for item in record.comparisons],
        "evidence": list(record.evidence),
        "ruleset_version": "m3-reconciliation-v5",
    }


def _write_json_once_or_same(path: Path, payload: dict[str, object]) -> None:
    content = json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n"
    _write_text_once_or_same(path, content)


def _write_jsonl_once_or_same(path: Path, records: tuple[CandidateReconciliation, ...]) -> None:
    content = "".join(
        json.dumps(_record_payload(record), sort_keys=True, default=str) + "\n"
        for record in records
    )
    _write_text_once_or_same(path, content)


def _write_text_once_or_same(path: Path, content: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise RuntimeError(f"immutable reconciliation artifact has conflicting content: {path}")
    if not path.exists():
        path.write_text(content, encoding="utf-8", newline="\n")


def _datalab_details(bout: CandidateBout) -> dict[str, str]:
    return _DETAILS_BY_RECORD[bout.source_record_key]


_DETAILS_BY_RECORD: dict[str, dict[str, str]] = {}


def _statistics(details: dict[str, str], corner: str) -> dict[str, float]:
    return {
        "knockdowns": _number(details.get(f"{corner}_fighter_KD", "0")),
        "significant_strikes": _number(details.get(f"{corner}_fighter_sig_str", "0")),
        "takedowns": _number(details.get(f"{corner}_fighter_TD", "0")),
        "submission_attempts": _number(details.get(f"{corner}_fighter_sub_att", "0")),
        "control_seconds": _clock_seconds(details.get(f"{corner}_fighter_ctrl", "0:00")),
    }


def _number(value: str) -> float:
    first = value.split(" of ", maxsplit=1)[0].strip()
    try:
        return float(first)
    except ValueError:
        return 0.0


def _clock_seconds(value: str) -> float:
    try:
        minutes, seconds = value.split(":", maxsplit=1)
        return float(int(minutes) * 60 + int(seconds))
    except ValueError:
        return 0.0


def _red_result(outcome: str | None) -> str:
    return {"red_win": "win", "blue_win": "loss", "draw": "draw"}.get(outcome or "", "nc")


def _blue_result(outcome: str | None) -> str:
    return {"red_win": "loss", "blue_win": "win", "draw": "draw"}.get(outcome or "", "nc")


def _history_features(history: list[tuple[str, dict[str, float]]]) -> dict[str, float]:
    result = {
        "prior_ufc_bouts": float(len(history)),
        "prior_wins": float(sum(outcome == "win" for outcome, _ in history)),
        "prior_losses": float(sum(outcome == "loss" for outcome, _ in history)),
        "prior_draws": float(sum(outcome == "draw" for outcome, _ in history)),
        "prior_no_contests": float(sum(outcome == "nc" for outcome, _ in history)),
    }
    for metric in (
        "knockdowns",
        "significant_strikes",
        "takedowns",
        "submission_attempts",
        "control_seconds",
    ):
        values = [statistics[metric] for _, statistics in history]
        result[f"career_{metric}"] = sum(values) / len(values) if values else 0.0
        recent = values[-3:]
        result[f"rolling_3_{metric}"] = sum(recent) / len(recent) if recent else 0.0
    return result
