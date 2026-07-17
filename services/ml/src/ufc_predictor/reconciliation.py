"""Traceable pairwise source reconciliation; source rows are never overwritten."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID


class ReconciliationClass(StrEnum):
    EXACT = "exact"
    NORMALIZED_EXACT = "normalized_exact"
    CORNER_SWAPPED = "corner_swapped"
    PROBABLE = "probable"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class SourceBout:
    source: str
    source_record_key: str
    event_date: date
    red_fighter_id: UUID
    blue_fighter_id: UUID
    winner: str | None
    method: str | None
    finish_round: int | None
    finish_time: str | None
    scheduled_rounds: int | None
    division: str | None
    event_name: str | None
    location: str | None


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    left_record_key: str
    right_record_key: str | None
    classification: ReconciliationClass
    conflicts: tuple[str, ...]


def reconcile_bouts(
    left: tuple[SourceBout, ...], right: tuple[SourceBout, ...]
) -> tuple[ReconciliationResult, ...]:
    """Match only candidates sharing date and canonical fighter pair; retain both rows."""

    results: list[ReconciliationResult] = []
    used: set[str] = set()
    for candidate in left:
        matches = [
            other
            for other in right
            if other.event_date == candidate.event_date
            and {other.red_fighter_id, other.blue_fighter_id}
            == {candidate.red_fighter_id, candidate.blue_fighter_id}
        ]
        if not matches:
            results.append(
                ReconciliationResult(
                    candidate.source_record_key, None, ReconciliationClass.UNMATCHED, ()
                )
            )
        elif len(matches) > 1:
            results.append(
                ReconciliationResult(
                    candidate.source_record_key, None, ReconciliationClass.AMBIGUOUS, ()
                )
            )
        else:
            other = matches[0]
            used.add(other.source_record_key)
            conflicts = _conflicts(candidate, other)
            if conflicts:
                classification = ReconciliationClass.CONFLICT
            elif (candidate.red_fighter_id, candidate.blue_fighter_id) == (
                other.red_fighter_id,
                other.blue_fighter_id,
            ):
                if _metadata_equal(candidate, other):
                    classification = ReconciliationClass.EXACT
                elif _metadata_normalized_equal(candidate, other):
                    classification = ReconciliationClass.NORMALIZED_EXACT
                else:
                    classification = ReconciliationClass.PROBABLE
            else:
                classification = (
                    ReconciliationClass.CORNER_SWAPPED
                    if _metadata_normalized_equal(candidate, other)
                    else ReconciliationClass.PROBABLE
                )
            results.append(
                ReconciliationResult(
                    candidate.source_record_key, other.source_record_key, classification, conflicts
                )
            )
    results.extend(
        ReconciliationResult("", item.source_record_key, ReconciliationClass.UNMATCHED, ())
        for item in right
        if item.source_record_key not in used
    )
    return tuple(results)


def _metadata_equal(left: SourceBout, right: SourceBout) -> bool:
    return (left.event_name, left.division, left.location) == (
        right.event_name,
        right.division,
        right.location,
    )


def _metadata_normalized_equal(left: SourceBout, right: SourceBout) -> bool:
    return tuple(_normalise_metadata(value) for value in _metadata_values(left)) == tuple(
        _normalise_metadata(value) for value in _metadata_values(right)
    )


def _metadata_values(bout: SourceBout) -> tuple[str | None, str | None, str | None]:
    return bout.event_name, bout.division, bout.location


def _normalise_metadata(value: str | None) -> str | None:
    if value is None:
        return None
    return "".join(character for character in value.casefold() if character.isalnum())


def _conflicts(left: SourceBout, right: SourceBout) -> tuple[str, ...]:
    comparisons = (
        ("winner", _winner_id(left), _winner_id(right)),
        ("method", left.method, right.method),
        ("finish_round", left.finish_round, right.finish_round),
        ("finish_time", left.finish_time, right.finish_time),
        ("scheduled_rounds", left.scheduled_rounds, right.scheduled_rounds),
        ("division", _normalise_metadata(left.division), _normalise_metadata(right.division)),
        (
            "event_name",
            _normalise_metadata(left.event_name),
            _normalise_metadata(right.event_name),
        ),
        ("location", _normalise_metadata(left.location), _normalise_metadata(right.location)),
    )
    return tuple(
        name for name, first, second in comparisons if first and second and first != second
    )


def _winner_id(bout: SourceBout) -> UUID | None:
    """Compare source-side results in canonical participant space."""

    if bout.winner is None:
        return None
    winner = bout.winner.casefold()
    if winner in {"red", "r"}:
        return bout.red_fighter_id
    if winner in {"blue", "b"}:
        return bout.blue_fighter_id
    return None
