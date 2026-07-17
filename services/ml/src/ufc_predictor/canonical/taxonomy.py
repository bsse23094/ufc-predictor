"""Versioned, reviewer-approved mappings for observed source labels.

No source label is interpreted by default.  The taxonomy retains each original
label and admits a canonical code only through an explicit mapping scoped to a
source schema and attributed to a reviewer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SourceFighterField(StrEnum):
    """The source participant field named by an approved outcome mapping."""

    RED = "R_fighter"
    BLUE = "B_fighter"


class CanonicalOutcomeType(StrEnum):
    """Outcome categories that do not infer a winner from an unreviewed label."""

    DECISIVE = "decisive"
    DRAW = "draw"
    NO_CONTEST = "no_contest"


@dataclass(frozen=True, slots=True)
class TaxonomyScope:
    """The exact source/schema scope in which a label was reviewed."""

    source_identifier: str
    source_schema_version: str

    def __post_init__(self) -> None:
        if not self.source_identifier.strip() or not self.source_schema_version.strip():
            raise ValueError("taxonomy scope requires source identifier and schema version")


@dataclass(frozen=True, slots=True)
class ObservedLabel:
    """A retained raw label observed in one source record."""

    scope: TaxonomyScope
    record_key: str
    raw_sha256: str
    field_name: str
    original_value: str

    def __post_init__(self) -> None:
        if (
            not self.record_key.strip()
            or not self.field_name.strip()
            or not self.original_value.strip()
        ):
            raise ValueError("observed label requires record, field, and original value")
        if len(self.raw_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.raw_sha256
        ):
            raise ValueError("observed label requires a lowercase raw SHA-256")


@dataclass(frozen=True, slots=True)
class OutcomeTaxonomyEntry:
    """An explicit source outcome label mapping approved for one source schema."""

    scope: TaxonomyScope
    source_label: str
    outcome_type: CanonicalOutcomeType
    winner_source_field: SourceFighterField | None
    mapping_version: str
    approved_by: str
    approved_at: datetime
    rationale: str

    def __post_init__(self) -> None:
        _validate_mapping_audit(
            source_label=self.source_label,
            mapping_version=self.mapping_version,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rationale=self.rationale,
        )
        if (self.outcome_type is CanonicalOutcomeType.DECISIVE) != (
            self.winner_source_field is not None
        ):
            raise ValueError("only decisive outcomes may name a winning source participant")


@dataclass(frozen=True, slots=True)
class MethodTaxonomyEntry:
    """An explicit observed finish/method label mapping."""

    scope: TaxonomyScope
    source_label: str
    canonical_method_code: str
    mapping_version: str
    approved_by: str
    approved_at: datetime
    rationale: str

    def __post_init__(self) -> None:
        _validate_mapping_audit(
            source_label=self.source_label,
            mapping_version=self.mapping_version,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rationale=self.rationale,
        )
        if not self.canonical_method_code.strip():
            raise ValueError("canonical_method_code is required")


@dataclass(frozen=True, slots=True)
class DivisionTaxonomyEntry:
    """An explicit observed weight-class label mapping."""

    scope: TaxonomyScope
    source_label: str
    canonical_division_code: str
    mapping_version: str
    approved_by: str
    approved_at: datetime
    rationale: str

    def __post_init__(self) -> None:
        _validate_mapping_audit(
            source_label=self.source_label,
            mapping_version=self.mapping_version,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            rationale=self.rationale,
        )
        if not self.canonical_division_code.strip():
            raise ValueError("canonical_division_code is required")


class ObservedLabelTaxonomy:
    """Immutable mapping registry with no fallback or guessed interpretation."""

    def __init__(
        self,
        *,
        taxonomy_version: str,
        outcomes: tuple[OutcomeTaxonomyEntry, ...] = (),
        methods: tuple[MethodTaxonomyEntry, ...] = (),
        divisions: tuple[DivisionTaxonomyEntry, ...] = (),
    ) -> None:
        if not taxonomy_version.strip():
            raise ValueError("taxonomy_version is required")
        self.taxonomy_version = taxonomy_version
        self._outcomes = _index_entries(outcomes)
        self._methods = _index_entries(methods)
        self._divisions = _index_entries(divisions)

    def outcome_for(self, scope: TaxonomyScope, source_label: str) -> OutcomeTaxonomyEntry | None:
        """Return an exact approved outcome mapping, or require review."""

        return self._outcomes.get(_entry_key(scope, source_label))

    def method_for(self, scope: TaxonomyScope, source_label: str) -> MethodTaxonomyEntry | None:
        """Return an exact approved method mapping, or require review."""

        return self._methods.get(_entry_key(scope, source_label))

    def division_for(self, scope: TaxonomyScope, source_label: str) -> DivisionTaxonomyEntry | None:
        """Return an exact approved division mapping, or require review."""

        return self._divisions.get(_entry_key(scope, source_label))


def _validate_mapping_audit(
    *,
    source_label: str,
    mapping_version: str,
    approved_by: str,
    approved_at: datetime,
    rationale: str,
) -> None:
    if not source_label.strip() or not mapping_version.strip():
        raise ValueError("source label and mapping version are required")
    if not approved_by.strip() or not rationale.strip():
        raise ValueError("taxonomy mappings require reviewer and rationale")
    if approved_at.tzinfo is None or approved_at.utcoffset() is None:
        raise ValueError("taxonomy approval time must be timezone-aware")


def _index_entries[Entry: OutcomeTaxonomyEntry | MethodTaxonomyEntry | DivisionTaxonomyEntry](
    entries: tuple[Entry, ...],
) -> dict[tuple[str, str, str], Entry]:
    indexed: dict[tuple[str, str, str], Entry] = {}
    for entry in entries:
        key = _entry_key(entry.scope, entry.source_label)
        existing = indexed.setdefault(key, entry)
        if existing != entry:
            raise ValueError("conflicting taxonomy entries share a source/schema/label key")
    return indexed


def _entry_key(scope: TaxonomyScope, source_label: str) -> tuple[str, str, str]:
    normalized = source_label.strip().casefold()
    if not normalized:
        raise ValueError("source label must not be blank")
    return (scope.source_identifier, scope.source_schema_version, normalized)
