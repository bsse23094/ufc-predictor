"""Publication gates for typed canonical mapping results."""

from __future__ import annotations

from dataclasses import dataclass

from ufc_predictor.canonical.models import CanonicalMappingIssue, CanonicalMappingResult


@dataclass(frozen=True, slots=True)
class CanonicalMappingBlocked(ValueError):
    """A mapped slice cannot enter the relational catalog until reviewed gaps close."""

    issues: tuple[CanonicalMappingIssue, ...]

    def __str__(self) -> str:
        return "canonical mapping has quarantined records"


def require_publishable_mapping(mapping: CanonicalMappingResult) -> None:
    """Enforce complete row accounting before any canonical publication boundary."""

    if mapping.input_count != len(mapping.accepted) + len(mapping.quarantined_record_keys):
        raise ValueError("canonical mapping row accounting is not balanced")
    if mapping.quarantined_record_keys:
        raise CanonicalMappingBlocked(mapping.issues)
    if not mapping.accepted:
        raise ValueError("canonical publication requires accepted mapped records")
