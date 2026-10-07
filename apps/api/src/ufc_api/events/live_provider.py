"""Opt-in SportsDataIO schedule adapter. Provider names never become canonical IDs."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from time import monotonic
from typing import Any

import httpx

from ufc_api.data.parquet_catalog import _name_to_fighter_id_map
from ufc_api.events.schemas import EventSummary, UpcomingBoutSummary, UpcomingFighterInfo

BASE = "https://api.sportsdata.io/v3/mma/scores/json"
_CACHE: dict[tuple[str, int], tuple[float, list[EventSummary]]] = {}


async def get_provider_event(key: str | None) -> EventSummary | None:
    events = await get_provider_events(key, max_events=1)
    return events[0] if events else None


async def get_provider_events(key: str | None, *, max_events: int = 5) -> list[EventSummary]:
    key = (key or "").strip()
    if not key:
        return []
    cache_key = (sha256(key.encode()).hexdigest(), max_events)
    cached = _CACHE.get(cache_key)
    if cached and monotonic() - cached[0] < 3600:
        return cached[1]
    headers = {"Ocp-Apim-Subscription-Key": key}
    async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
        years = (date.today().year, date.today().year + 1)
        schedules: list[dict[str, Any]] = []
        for year in years:
            response = await client.get(f"{BASE}/Schedule/UFC/{year}")
            response.raise_for_status()
            schedules.extend(response.json())
        future = sorted(
            (
                event
                for event in schedules
                if event.get("Day")
                and date.fromisoformat(event["Day"][:10]) >= date.today()
                and event.get("Status") not in {"Canceled", "Final"}
            ),
            key=lambda event: event["Day"],
        )
        details = []
        for scheduled in future[:max_events]:
            response = await client.get(f"{BASE}/Event/{scheduled['EventId']}")
            response.raise_for_status()
            details.append(response.json())
    events = [_parse_event(detail) for detail in details]
    _CACHE[cache_key] = (monotonic(), events)
    return events


def _parse_event(detail: dict[str, Any]) -> EventSummary:
    canonical = _name_to_fighter_id_map()
    bouts: list[UpcomingBoutSummary] = []
    for fight in detail.get("Fights") or []:
        participants = fight.get("Fighters") or []
        if len(participants) != 2 or fight.get("Status") == "Canceled":
            continue
        fighters = []
        for participant in participants:
            name = " ".join(
                filter(None, (participant.get("FirstName"), participant.get("LastName")))
            ).strip()
            fighters.append(
                UpcomingFighterInfo(
                    fighter_id=canonical.get(name.lower(), ""),
                    display_name=name or "Fighter TBA",
                    wins=participant.get("PreFightWins"),
                    losses=participant.get("PreFightLosses"),
                )
            )
        bouts.append(
            UpcomingBoutSummary(
                bout_id=f"sportsdataio:{fight['FightId']}",
                weight_class=fight.get("WeightClass") or "Division TBA",
                scheduled_rounds=fight.get("Rounds") or 3,
                is_title_bout=False,
                card_placement=fight.get("CardSegment") or "Card TBA",
                fighter_a=fighters[0],
                fighter_b=fighters[1],
            )
        )
    return EventSummary(
        event_id=f"sportsdataio:{detail['EventId']}",
        event_name=detail.get("Name") or "UFC event",
        event_date=date.fromisoformat(detail["Day"][:10]),
        location="Location not supplied by provider",
        status="scheduled",
        source_audit_state="licensed_provider",
        bout_count=len(bouts),
        bouts=bouts,
    )
