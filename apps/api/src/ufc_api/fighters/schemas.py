"""Schemas for canonical fighter catalog read views."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FighterSummary(BaseModel):
    """Compact summary of a canonical fighter."""

    fighter_id: str
    display_name: str
    identity_status: str
    active_alias_count: int = 0
    created_at: datetime


class FighterAliasSummary(BaseModel):
    """A reviewed source alias associated with a canonical fighter."""

    alias_id: str
    alias_value: str
    normalized_value: str
    alias_type: str
    source_id: str
    is_current: bool
    resolution_status: str


class FighterCareerStats(BaseModel):
    """Aggregate career and pre-fight performance indicators."""

    wins: int = 0
    losses: int = 0
    draws: int = 0
    ko_wins: int = 0
    sub_wins: int = 0
    dec_wins: int = 0
    avg_fight_time_mins: float | None = None
    sig_strike_landed_per_min: float | None = None
    sig_strike_acc: float | None = None
    sig_strike_absorbed_per_min: float | None = None
    sig_strike_def: float | None = None
    td_avg_per_15m: float | None = None
    td_acc: float | None = None
    td_def: float | None = None
    sub_avg_per_15m: float | None = None


class FighterDetail(BaseModel):
    """Detailed canonical fighter record with reviewed aliases and analytical metrics."""

    fighter_id: str
    display_name: str
    identity_status: str
    merged_into_fighter_id: str | None = None
    retired_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    aliases: list[FighterAliasSummary] = Field(default_factory=list)
    first_name: str | None = None
    last_name: str | None = None
    nickname: str | None = None
    stance: str | None = None
    height_cm: float | None = None
    reach_cm: float | None = None
    weight_class: str | None = None
    division: str | None = None
    stats: FighterCareerStats | None = None


class FighterPage(BaseModel):
    """Keyset-paginated collection of canonical fighters."""

    items: list[FighterSummary]
    next_cursor: str | None = None
    has_more: bool = False
