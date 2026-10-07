"""Schemas for canonical fight catalog read views."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class ParticipantSummary(BaseModel):
    """A participant slot in a canonical bout."""

    participant_id: str
    fighter_id: str
    display_name: str
    canonical_slot: int
    source_corner: str | None = None


class ResultSummary(BaseModel):
    """Verified canonical outcome for a completed bout."""

    result_id: str
    outcome_type: str
    canonical_method_code: str | None = None
    source_outcome_label: str | None = None
    source_method_label: str | None = None
    winner_participant_id: str | None = None
    winner_fighter_id: str | None = None


class FightSummary(BaseModel):
    """Compact summary of a canonical fight."""

    fight_id: str
    fight_date: date | None = None
    division_code: str | None = None
    status: str
    scheduled_rounds: int
    participants: list[ParticipantSummary] = Field(default_factory=list)
    result: ResultSummary | None = None


class FightDetail(BaseModel):
    """Detailed canonical fight record with participants, result, and source references."""

    fight_id: str
    fight_date: date | None = None
    division_code: str | None = None
    status: str
    publication_state: str
    event_context_status: str
    scheduled_rounds: int
    round_length_seconds: int | None = None
    location: str | None = None
    country: str | None = None
    participants: list[ParticipantSummary] = Field(default_factory=list)
    result: ResultSummary | None = None
    source_count: int = 0
    created_at: datetime
    updated_at: datetime


class FighterHistoryPage(BaseModel):
    """Keyset-paginated bout history for a canonical fighter."""

    fighter_id: str
    items: list[FightSummary]
    next_cursor: str | None = None
    has_more: bool = False


class FightPage(BaseModel):
    """Keyset-paginated collection of canonical fights."""

    items: list[FightSummary]
    next_cursor: str | None = None
    has_more: bool = False
