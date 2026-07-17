"""Review-only dual-source reconciliation and strictly-prior history proposals."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from ufc_predictor.identity.normalize import normalize_fighter_alias


@dataclass(frozen=True, slots=True)
class CandidateBout:
    source: str
    source_record_key: str
    fight_date: date
    red_name: str
    blue_name: str
    outcome: str | None
    method: str | None
    scheduled_rounds: int | None
    division: str | None
    location: str | None


@dataclass(frozen=True, slots=True)
class CandidateReconciliationReport:
    exact: int
    normalized_exact: int
    corner_swapped: int
    probable: int
    ambiguous: int
    conflict: int
    ultimate_only: int
    datalab_only: int


def reconcile_ultimate_and_datalab_candidates(
    *, ultimate_csv: Path, datalab_parquet: Path
) -> CandidateReconciliationReport:
    """Reconcile exact normalized-name candidates without assigning identities.

    The candidate key is deliberately not a canonical fighter ID. Any match
    emitted here remains evidence for a reviewer and must not apply aliases.
    """

    ultimate = tuple(_ultimate_bouts(ultimate_csv))
    datalab = tuple(_datalab_bouts(datalab_parquet))
    index: defaultdict[tuple[date, tuple[str, str]], list[CandidateBout]] = defaultdict(list)
    for bout in datalab:
        index[_candidate_key(bout)].append(bout)
    counts: defaultdict[str, int] = defaultdict(int)
    touched_right: set[str] = set()
    for left in ultimate:
        candidates = index.get(_candidate_key(left), [])
        if not candidates:
            counts["ultimate_only"] += 1
            continue
        if len(candidates) > 1:
            counts["ambiguous"] += 1
            touched_right.update(candidate.source_record_key for candidate in candidates)
            continue
        right = candidates[0]
        touched_right.add(right.source_record_key)
        conflicts = _conflicts(left, right)
        if conflicts:
            counts["conflict"] += 1
        elif _same_orientation(left, right):
            counts["exact" if _exact_names(left, right) else "normalized_exact"] += 1
        elif _swapped_orientation(left, right):
            counts["corner_swapped"] += 1
        else:
            counts["probable"] += 1
    counts["datalab_only"] = sum(bout.source_record_key not in touched_right for bout in datalab)
    return CandidateReconciliationReport(
        **{name: counts[name] for name in CandidateReconciliationReport.__annotations__}
    )


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
                outcome=row["Winner"].strip().casefold() or None,
                method=row["finish"].strip() or None,
                scheduled_rounds=_optional_int(row["no_of_rounds"]),
                division=row["weight_class"].strip() or None,
                location=row["location"].strip() or None,
            )


def _datalab_bouts(path: Path) -> Iterable[CandidateBout]:
    for row in pl.read_parquet(path).iter_rows(named=True):
        source_record_key = str(row["source_record_key"])
        _DETAILS_BY_RECORD[source_record_key] = json.loads(str(row["detailed_statistics"]))
        yield CandidateBout(
            source="ufc-datalab",
            source_record_key=source_record_key,
            fight_date=row["fight_date"],
            red_name=str(row["red_fighter_source_name"]),
            blue_name=str(row["blue_fighter_source_name"]),
            outcome=str(row["outcome_source_value"]) or None,
            method=str(row["method_source_value"]) or None,
            scheduled_rounds=row["scheduled_rounds"],
            division=str(row["division_source_value"]) or None,
            location=str(row["location"]) or None,
        )


def _candidate_key(bout: CandidateBout) -> tuple[date, tuple[str, str]]:
    first, second = sorted((_name_key(bout.red_name), _name_key(bout.blue_name)))
    return bout.fight_date, (first, second)


def _name_key(value: str) -> str:
    return normalize_fighter_alias(value).normalized_value


def _exact_names(left: CandidateBout, right: CandidateBout) -> bool:
    return (left.red_name.casefold(), left.blue_name.casefold()) == (
        right.red_name.casefold(),
        right.blue_name.casefold(),
    )


def _same_orientation(left: CandidateBout, right: CandidateBout) -> bool:
    return (_name_key(left.red_name), _name_key(left.blue_name)) == (
        _name_key(right.red_name),
        _name_key(right.blue_name),
    )


def _swapped_orientation(left: CandidateBout, right: CandidateBout) -> bool:
    return (_name_key(left.red_name), _name_key(left.blue_name)) == (
        _name_key(right.blue_name),
        _name_key(right.red_name),
    )


def _conflicts(left: CandidateBout, right: CandidateBout) -> tuple[str, ...]:
    return tuple(
        name
        for name, first, second in (
            ("outcome", _winner_side(left.outcome), _winner_side(right.outcome)),
            ("method", _normalise(left.method), _normalise(right.method)),
            ("scheduled_rounds", left.scheduled_rounds, right.scheduled_rounds),
        )
        if first is not None and second is not None and first != second
    )


def _winner_side(value: str | None) -> str | None:
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


def _normalise(value: str | None) -> str | None:
    return (
        "".join(character for character in value.casefold() if character.isalnum())
        if value
        else None
    )


def _optional_int(value: str) -> int | None:
    return int(value) if value.isdecimal() else None


def _datalab_details(bout: CandidateBout) -> dict[str, str]:
    # The source record remains in its source-shaped Parquet row; this helper is
    # overridden by the cached lookup populated in _statistics for each output.
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
