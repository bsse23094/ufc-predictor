"""Events API router for upcoming fight cards and historical events."""

from __future__ import annotations

from datetime import date
from typing import cast
from uuid import NAMESPACE_DNS, uuid5

from fastapi import APIRouter, Request

from ufc_api.core.errors import DomainError, ErrorDetail
from ufc_api.data.parquet_catalog import ParquetCatalog
from ufc_api.events.live_provider import get_provider_event, get_provider_events
from ufc_api.events.schemas import (
    EventPage,
    EventSummary,
    UpcomingBoutSummary,
    UpcomingFighterInfo,
)
from ufc_predictor.inference.m5_champion import ChampionRuntime

router = APIRouter(prefix="/api/v1/events", tags=["events"])


def _runtime(request: Request) -> ChampionRuntime | None:
    return cast(ChampionRuntime | None, getattr(request.app.state, "champion_runtime", None))


@router.get("/upcoming", response_model=EventSummary, summary="Get the upcoming featured UFC event")
async def get_upcoming_event(request: Request) -> EventSummary:
    """Return the authentic upcoming event card with analytical win probabilities."""
    try:
        configured_key = request.app.state.settings.sportsdataio_mma_api_key
        provider_event = await get_provider_event(
            configured_key.get_secret_value() if configured_key else None
        )
    except Exception as exc:
        raise DomainError(
            code="schedule_provider_unavailable",
            message="Live schedule provider is unavailable.",
            status_code=503,
        ) from exc
    if provider_event is not None:
        return provider_event
    raw_bouts = ParquetCatalog.get_upcoming_bouts()
    if not raw_bouts:
        raise DomainError(
            code="upcoming_event_unavailable",
            message="No verified future event card is available.",
            status_code=404,
        )

    runtime = _runtime(request)
    first = raw_bouts[0]
    event_date = date.fromisoformat(first["fight_date"])
    event_id = str(uuid5(NAMESPACE_DNS, f"event:{event_date}:{first['location']}"))

    bouts: list[UpcomingBoutSummary] = []
    for b in raw_bouts:
        fa = b["fighter_a"]
        fb = b["fighter_b"]
        fa_info = UpcomingFighterInfo(
            fighter_id=fa["fighter_id"],
            display_name=fa["display_name"],
            odds=float(fa["odds"]) if fa.get("odds") is not None else None,
            reach_cms=float(fa["reach_cms"]) if fa.get("reach_cms") is not None else None,
            height_cms=float(fa["height_cms"]) if fa.get("height_cms") is not None else None,
            weight_lbs=float(fa["weight_lbs"]) if fa.get("weight_lbs") is not None else None,
            stance=fa.get("stance"),
            age=int(fa["age"]) if fa.get("age") is not None else None,
            wins=int(fa["wins"]) if fa.get("wins") is not None else None,
            losses=int(fa["losses"]) if fa.get("losses") is not None else None,
        )
        fb_info = UpcomingFighterInfo(
            fighter_id=fb["fighter_id"],
            display_name=fb["display_name"],
            odds=float(fb["odds"]) if fb.get("odds") is not None else None,
            reach_cms=float(fb["reach_cms"]) if fb.get("reach_cms") is not None else None,
            height_cms=float(fb["height_cms"]) if fb.get("height_cms") is not None else None,
            weight_lbs=float(fb["weight_lbs"]) if fb.get("weight_lbs") is not None else None,
            stance=fb.get("stance"),
            age=int(fb["age"]) if fb.get("age") is not None else None,
            wins=int(fb["wins"]) if fb.get("wins") is not None else None,
            losses=int(fb["losses"]) if fb.get("losses") is not None else None,
        )

        pred_winner = None
        prob_a = None
        prob_b = None
        tier = "default"

        if runtime is not None:
            try:
                pred = runtime.predict(fa["fighter_id"], fb["fighter_id"], event_date)
                prob_a = round(pred.probability_a, 4)
                prob_b = round(pred.probability_b, 4)
                pred_winner = pred.predicted_winner_id
                tier = (
                    "high"
                    if bool(pred.confidence["high_confidence"]["covered"])
                    else "medium"
                    if bool(pred.confidence["medium_confidence"]["covered"])
                    else "default"
                )
            except Exception:
                # The winner model has no accepted materialization for this bout.
                # Odds are not a substitute for a model prediction.
                pass

        bouts.append(
            UpcomingBoutSummary(
                bout_id=b["bout_id"],
                weight_class=b["weight_class"],
                scheduled_rounds=b["scheduled_rounds"],
                is_title_bout=b["is_title_bout"],
                card_placement=b["card_placement"],
                fighter_a=fa_info,
                fighter_b=fb_info,
                predicted_winner_id=pred_winner,
                probability_a=prob_a,
                probability_b=prob_b,
                confidence_tier=tier,
            )
        )

    return EventSummary(
        event_id=event_id,
        event_name=first["event_name"],
        event_date=event_date,
        location=first["location"],
        status="scheduled",
        bout_count=len(bouts),
        bouts=bouts,
    )


@router.get("", response_model=EventPage, summary="List scheduled and historical events")
async def list_events(request: Request) -> EventPage:
    """Return upcoming events and notable event cards."""
    configured_key = request.app.state.settings.sportsdataio_mma_api_key
    if configured_key:
        try:
            events = await get_provider_events(configured_key.get_secret_value())
        except Exception as exc:
            raise DomainError(
                code="schedule_provider_unavailable",
                message="Live schedule provider is unavailable.",
                status_code=503,
            ) from exc
        return EventPage(items=events, next_cursor=None, has_more=False)
    try:
        upcoming = await get_upcoming_event(request)
    except DomainError as exc:
        if exc.code == "upcoming_event_unavailable":
            return EventPage(items=[], next_cursor=None, has_more=False)
        raise
    return EventPage(
        items=[upcoming],
        next_cursor=None,
        has_more=False,
    )


@router.get("/{event_id}", response_model=EventSummary, summary="Get event details by ID")
async def get_event(event_id: str, request: Request) -> EventSummary:
    """Return specific event details."""
    configured_key = request.app.state.settings.sportsdataio_mma_api_key
    if configured_key:
        try:
            events = await get_provider_events(configured_key.get_secret_value())
        except Exception as exc:
            raise DomainError(
                code="schedule_provider_unavailable",
                message="Live schedule provider is unavailable.",
                status_code=503,
            ) from exc
        for event in events:
            if event.event_id == event_id:
                return event
    upcoming = await get_upcoming_event(request)
    if upcoming.event_id == event_id or event_id == "upcoming":
        return upcoming

    raise DomainError(
        code="event_not_found",
        message=f"Event {event_id} was not found.",
        status_code=404,
        details=[ErrorDetail(field="event_id", reason="unknown event ID")],
    )
