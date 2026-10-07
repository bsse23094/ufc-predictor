"""The licensed schedule adapter keeps provider identity separate from model identity."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx
from pytest import MonkeyPatch

from ufc_api.events import live_provider


def test_live_schedule_requires_key() -> None:
    assert asyncio.run(live_provider.get_provider_event(None)) is None


def test_live_schedule_maps_only_known_canonical_fighters(monkeypatch: MonkeyPatch) -> None:
    future = (date.today() + timedelta(days=14)).isoformat()
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        assert request.headers["Ocp-Apim-Subscription-Key"] == "test-key"
        if "/Schedule/" in str(request.url):
            return httpx.Response(
                200,
                json=[
                    {
                        "EventId": 91,
                        "Name": "UFC Test",
                        "Day": future,
                        "Status": "Scheduled",
                    }
                ],
            )
        return httpx.Response(
            200,
            json={
                "EventId": 91,
                "Name": "UFC Test",
                "Day": future,
                "Fights": [
                    {
                        "FightId": 7,
                        "WeightClass": "Lightweight",
                        "Rounds": 3,
                        "Fighters": [
                            {"FirstName": "Known", "LastName": "Fighter"},
                            {"FirstName": "New", "LastName": "Fighter"},
                        ],
                    }
                ],
            },
        )

    client_class = httpx.AsyncClient
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        live_provider.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(transport=transport, **kwargs),
    )
    monkeypatch.setattr(
        live_provider,
        "_name_to_fighter_id_map",
        lambda: {"known fighter": "canonical-123"},
    )
    event = asyncio.run(live_provider.get_provider_event("test-key"))
    assert event is not None
    assert event.source_audit_state == "licensed_provider"
    assert event.bouts[0].fighter_a.fighter_id == "canonical-123"
    assert event.bouts[0].fighter_b.fighter_id == ""
    assert len(requests) == 3


def test_live_schedule_lists_future_cards_in_date_order(monkeypatch: MonkeyPatch) -> None:
    soon = (date.today() + timedelta(days=7)).isoformat()
    later = (date.today() + timedelta(days=21)).isoformat()
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "/Schedule/" in str(request.url):
            # Only one season returns fixtures; the adapter still requests both.
            if str(date.today().year + 1) in str(request.url):
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[
                    {"EventId": 2, "Name": "Later", "Day": later, "Status": "Scheduled"},
                    {"EventId": 1, "Name": "Soon", "Day": soon, "Status": "Scheduled"},
                ],
            )
        event_id = int(str(request.url).rsplit("/", 1)[-1])
        return httpx.Response(
            200,
            json={
                "EventId": event_id,
                "Name": "Soon" if event_id == 1 else "Later",
                "Day": soon if event_id == 1 else later,
                "Fights": [],
            },
        )

    client_class = httpx.AsyncClient
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        live_provider.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(transport=transport, **kwargs),
    )
    monkeypatch.setattr(live_provider, "_name_to_fighter_id_map", lambda: {})
    events = asyncio.run(live_provider.get_provider_events("many-key", max_events=2))
    assert [event.event_name for event in events] == ["Soon", "Later"]
    assert len(calls) == 4
    cached = asyncio.run(live_provider.get_provider_events("many-key", max_events=2))
    assert cached == events
    assert len(calls) == 4
