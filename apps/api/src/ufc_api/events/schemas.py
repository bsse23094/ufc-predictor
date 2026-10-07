"""Pydantic schemas for events and upcoming cards."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class UpcomingFighterInfo(BaseModel):
    fighter_id: str
    display_name: str
    odds: float | None = None
    reach_cms: float | None = None
    height_cms: float | None = None
    weight_lbs: float | None = None
    stance: str | None = None
    age: int | None = None
    wins: int | None = None
    losses: int | None = None


class UpcomingBoutSummary(BaseModel):
    bout_id: str
    weight_class: str
    scheduled_rounds: int
    is_title_bout: bool = False
    card_placement: str = "main_card"
    fighter_a: UpcomingFighterInfo
    fighter_b: UpcomingFighterInfo
    predicted_winner_id: str | None = None
    probability_a: float | None = None
    probability_b: float | None = None
    confidence_tier: str | None = None


class EventSummary(BaseModel):
    event_id: str
    event_name: str
    event_date: date
    location: str
    status: str
    source_audit_state: str = "unverified"
    bout_count: int
    bouts: list[UpcomingBoutSummary] = Field(default_factory=list)


class EventPage(BaseModel):
    items: list[EventSummary]
    next_cursor: str | None = None
    has_more: bool = False
