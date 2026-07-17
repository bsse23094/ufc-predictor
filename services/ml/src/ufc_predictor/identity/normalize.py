"""Candidate-only fighter-name normalization with retained source evidence.

This module intentionally cannot resolve, merge, or publish fighter identities.
It produces repeatable comparison keys while retaining the exact observed alias
and raw-object checksum required for later human-reviewed resolution.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

_WHITESPACE = re.compile(r"\s+")
_FIGHTER_NAME_FIELDS = ("fighter_one_source_name", "fighter_two_source_name")


@dataclass(frozen=True, slots=True)
class NormalizedAlias:
    """An observed alias and its comparison-only normalized form."""

    original_value: str
    normalized_value: str


@dataclass(frozen=True, slots=True)
class FighterAliasCandidate:
    """A source-backed candidate that has no canonical fighter assignment."""

    source_identifier: str
    source_record_key: str
    source_raw_sha256: str
    source_field: str
    alias: NormalizedAlias


def normalize_fighter_alias(value: str) -> NormalizedAlias:
    """Create a conservative lookup key without changing the observed alias.

    Unicode compatibility decomposition, accent removal, case folding, punctuation
    folding, and whitespace collapse only support candidate generation. Equal keys
    are never proof that two observations represent the same fighter.
    """

    if not isinstance(value, str):
        raise TypeError("fighter alias must be a string")
    if not value.strip():
        raise ValueError("fighter alias must not be blank")

    decomposed = unicodedata.normalize("NFKD", value)
    accent_free = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    punctuation_folded = "".join(
        character if character.isalnum() else "" if character in ("'", "`", "\u2019") else " "
        for character in accent_free.casefold()
    )
    normalized = _WHITESPACE.sub(" ", punctuation_folded).strip()
    if not normalized:
        raise ValueError("fighter alias has no comparable characters")
    return NormalizedAlias(original_value=value, normalized_value=normalized)


def candidate_fighter_aliases(
    *, source_identifier: str, rows: Iterable[Mapping[str, object]]
) -> tuple[FighterAliasCandidate, ...]:
    """Create source-backed candidate aliases from M2's restricted interim rows."""

    if not source_identifier.strip():
        raise ValueError("source_identifier must not be blank")

    candidates: list[FighterAliasCandidate] = []
    for row in rows:
        source_record_key = _required_text(row, "source_record_key")
        source_raw_sha256 = _required_sha256(row, "source_raw_sha256")
        for source_field in _FIGHTER_NAME_FIELDS:
            candidates.append(
                FighterAliasCandidate(
                    source_identifier=source_identifier,
                    source_record_key=source_record_key,
                    source_raw_sha256=source_raw_sha256,
                    source_field=source_field,
                    alias=normalize_fighter_alias(_required_text(row, source_field)),
                )
            )
    return tuple(candidates)


def group_candidate_aliases(
    candidates: Iterable[FighterAliasCandidate],
) -> dict[str, tuple[FighterAliasCandidate, ...]]:
    """Group equal comparison keys without treating a group as a resolved identity."""

    grouped: defaultdict[str, list[FighterAliasCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.alias.normalized_value].append(candidate)
    return {key: tuple(grouped[key]) for key in sorted(grouped)}


def _required_text(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"interim row has no nonblank {field}")
    return value


def _required_sha256(row: Mapping[str, object], field: str) -> str:
    value = _required_text(row, field)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"interim row has invalid {field}")
    return value
