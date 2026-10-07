"""Tests for expanded API endpoints (events, predictions, simulations, similarity)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ufc_api.core.config import Settings
from ufc_api.data import parquet_catalog
from ufc_api.main import create_app
from ufc_predictor.inference.m5_champion import ChampionRuntime


@pytest.fixture
def future_card(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    card = tmp_path / "upcoming.csv"
    future_date = (date.today() + timedelta(days=7)).isoformat()
    card.write_text(
        "R_fighter,B_fighter,date,location,weight_class,no_of_rounds,title_bout\n"
        f"Renato Moicano,Chris Duncan,{future_date},Test Arena,Lightweight,3,false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(parquet_catalog, "UPCOMING_CSV", card)


def test_upcoming_events_endpoint(future_card: None) -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.get("/api/v1/events/upcoming")
        assert response.status_code == 200
        data = response.json()
        assert "event_id" in data
        assert "event_name" in data
        assert "bouts" in data
        assert len(data["bouts"]) > 0
        first_bout = data["bouts"][0]
        assert "fighter_a" in first_bout
        assert "fighter_b" in first_bout
        assert "weight_class" in first_bout


def test_events_list_and_detail_endpoint(future_card: None) -> None:
    with TestClient(create_app(Settings())) as client:
        list_res = client.get("/api/v1/events")
        assert list_res.status_code == 200
        items = list_res.json()["items"]
        assert len(items) > 0
        event_id = items[0]["event_id"]

        detail_res = client.get(f"/api/v1/events/{event_id}")
        assert detail_res.status_code == 200
        assert detail_res.json()["event_id"] == event_id


def test_expired_card_is_not_presented_as_upcoming() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.get("/api/v1/events/upcoming")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "upcoming_event_unavailable"
        assert client.get("/api/v1/events").json()["items"] == []


def test_fighters_catalog_parquet_fallback() -> None:
    # Ensure fighters list and search works even when database session is None
    settings = Settings()
    settings.database_url = None
    with TestClient(create_app(settings)) as client:
        res = client.get("/api/v1/fighters?limit=5")
        assert res.status_code == 200
        body = res.json()
        assert len(body["items"]) == 5
        fighter_id = body["items"][0]["fighter_id"]

        # Detail lookup
        detail_res = client.get(f"/api/v1/fighters/{fighter_id}")
        assert detail_res.status_code == 200
        assert detail_res.json()["fighter_id"] == fighter_id

        # Search
        search_res = client.get("/api/v1/fighters?query=Moicano")
        assert search_res.status_code == 200
        assert any("Moicano" in f["display_name"] for f in search_res.json()["items"])


def test_matchup_prediction_endpoint() -> None:
    runtime = ChampionRuntime()
    row = next(iter(runtime._rows.values()))
    payload = {
        "fighter_a_id": str(row["canonical_fighter_a_id"]),
        "fighter_b_id": str(row["canonical_fighter_b_id"]),
        "target_fight_date": str(row["fight_date"]),
        "scheduled_rounds": 3,
        "mode": "pure",
    }
    with TestClient(create_app(Settings())) as client:
        res = client.post("/api/v1/predictions/matchup", json=payload)
        assert res.status_code == 200
        body = res.json()
        assert body["mode"] == "pure"
        assert body["method_probabilities"] is None
        assert body["round_distribution"] is None
        assert body["fighter_a_win_probability"] + body["fighter_b_win_probability"] == 1.0


def test_simulations_counterfactual_endpoint() -> None:
    runtime = ChampionRuntime()
    row = next(iter(runtime._rows.values()))
    payload = {
        "fighter_a_id": str(row["canonical_fighter_a_id"]),
        "fighter_b_id": str(row["canonical_fighter_b_id"]),
        "target_fight_date": str(row["fight_date"]),
        "adjustments": {
            "reach_advantage_cms": 5.0,
            "age_difference_years": -3.0,
        },
    }
    with TestClient(create_app(Settings())) as client:
        res = client.post("/api/v1/simulations/counterfactual", json=payload)
        assert res.status_code == 200
        body = res.json()
        assert "counterfactual_probability_a" in body
        assert "probability_delta_a" in body
        assert body["synthetic_label"] == "SYNTHETIC_COUNTERFACTUAL_ESTIMATE"


def test_simulations_monte_carlo_endpoint() -> None:
    runtime = ChampionRuntime()
    row = next(iter(runtime._rows.values()))
    payload = {
        "fighter_a_id": str(row["canonical_fighter_a_id"]),
        "fighter_b_id": str(row["canonical_fighter_b_id"]),
        "target_fight_date": str(row["fight_date"]),
        "iterations": 1000,
        "seed": 42,
        "scheduled_rounds": 3,
    }
    with TestClient(create_app(Settings())) as client:
        res = client.post("/api/v1/simulations/monte-carlo", json=payload)
        assert res.status_code == 200
        body = res.json()
        assert body["iterations"] == 1000
        assert "method_distribution" in body
        assert "round_distribution" in body
        assert "duration_quantiles" in body


def test_similarity_matchups_endpoint() -> None:
    runtime = ChampionRuntime()
    row = next(iter(runtime._rows.values()))
    with TestClient(create_app(Settings())) as client:
        res = client.get(
            f"/api/v1/similarity/matchups?fighter_a_id={row['canonical_fighter_a_id']}&fighter_b_id={row['canonical_fighter_b_id']}&target_fight_date={row['fight_date']}&limit=3"
        )
        assert res.status_code == 200
        items = res.json()
        assert isinstance(items, list)
        if items:
            assert "similarity_score" in items[0]
            assert "fighter_a_name" in items[0]


def test_explanations_endpoint() -> None:
    runtime = ChampionRuntime()
    row = next(iter(runtime._rows.values()))
    with TestClient(create_app(Settings())) as client:
        res = client.get(
            f"/api/v1/explanations?fighter_a_id={row['canonical_fighter_a_id']}&fighter_b_id={row['canonical_fighter_b_id']}&target_fight_date={row['fight_date']}"
        )
        assert res.status_code == 200
        body = res.json()
        assert "top_factors" in body
        assert len(body["top_factors"]) > 0
        assert "disclaimer" in body
