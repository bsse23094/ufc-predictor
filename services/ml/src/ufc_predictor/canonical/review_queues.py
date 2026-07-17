"""Taxonomy review queues; proposed values are suggestions, never defaults."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TaxonomyReviewQueueItem:
    source: str
    raw_value: str
    proposed_value: str | None
    affected_count: int
    examples: tuple[str, ...]
    confidence: str
    reason: str
    review_status: str = "pending"


def build_taxonomy_review_queue(
    *, source: str, rows: Iterable[Mapping[str, object]]
) -> tuple[TaxonomyReviewQueueItem, ...]:
    """Identify all requested taxonomy edge cases from retained source values."""

    buckets: dict[str, list[str]] = {}
    for row in rows:
        for field, reason in (
            ("country", "country whitespace"),
            ("stance", "stance whitespace or missing"),
            ("weight_class", "division naming, Catch Weight, or women's division"),
            ("title_bout", "title-bout semantics"),
            ("no_of_rounds", "four-round or scheduled-round review"),
            ("finish_round", "finish round exceeds scheduled rounds"),
            ("height", "implausible measurement"),
            ("reach", "implausible measurement"),
            ("finish", "unknown finish method"),
            ("event", "event-name consistency"),
            ("location", "location consistency"),
        ):
            value = row.get(field)
            text = value if isinstance(value, str) else "" if value is None else str(value)
            if _requires_review(field, text, row):
                buckets.setdefault(reason, []).append(text)
    items: list[TaxonomyReviewQueueItem] = []
    for reason, values in sorted(buckets.items()):
        for value, count in sorted(Counter(values).items()):
            items.append(
                TaxonomyReviewQueueItem(
                    source=source,
                    raw_value=value,
                    proposed_value=value.strip() or None,
                    affected_count=count,
                    examples=tuple(values[:3]),
                    confidence="review_required",
                    reason=reason,
                )
            )
    return tuple(items)


def _requires_review(field: str, value: str, row: Mapping[str, object]) -> bool:
    if field in {"country", "stance"}:
        return not value or value != value.strip()
    if field == "weight_class":
        folded = value.casefold()
        return "catch" in folded or "women" in folded or value != value.strip()
    if field == "no_of_rounds":
        return value.strip() == "4"
    if field == "finish_round":
        rounds = row.get("no_of_rounds")
        return (
            value.isdecimal()
            and isinstance(rounds, str)
            and rounds.isdecimal()
            and int(value) > int(rounds)
        )
    if field in {"height", "reach"}:
        return value.isdecimal() and not 120 <= int(value) <= 260
    if field == "finish":
        return bool(value) and value.casefold() not in {
            "ko/tko",
            "submission",
            "decision",
            "draw",
            "nc",
        }
    return bool(value) and value != value.strip()
