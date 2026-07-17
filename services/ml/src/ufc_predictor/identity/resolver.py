"""Explicit reviewed identity-transition requests.

This module carries only immutable, canonical-ID requests.  It does not find
matches, mutate aliases, or decide whether a proposed merge or split is safe;
the API-owned repository validates retained review evidence and applies the
durable transition transactionally.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReviewedFighterMerge:
    """A human-reviewed request to merge one active fighter into another."""

    decision_id: UUID
    canonical_fighter_id: UUID
    merged_fighter_id: UUID

    def __post_init__(self) -> None:
        if self.canonical_fighter_id == self.merged_fighter_id:
            raise ValueError("a fighter cannot be merged into itself")


@dataclass(frozen=True, slots=True)
class ReviewedFighterSplit:
    """A human-reviewed request to restore a specifically merged fighter."""

    decision_id: UUID
    canonical_fighter_id: UUID
    restored_fighter_id: UUID

    def __post_init__(self) -> None:
        if self.canonical_fighter_id == self.restored_fighter_id:
            raise ValueError("a fighter cannot be split from itself")
