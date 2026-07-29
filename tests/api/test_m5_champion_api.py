"""M5 prediction endpoint schema and safe status-code coverage."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ufc_api.core.config import Settings
from ufc_api.main import create_app
from ufc_predictor.inference.m5_champion import ChampionRuntime


def test_fight_prediction_endpoint_returns_provenance_and_symmetric_probabilities() -> None:
    runtime = ChampionRuntime()
    row = next(iter(runtime._rows.values()))
    payload = {
        "fighter_a_id": str(row["canonical_fighter_a_id"]),
        "fighter_b_id": str(row["canonical_fighter_b_id"]),
        "target_fight_date": str(row["fight_date"]),
    }
    with TestClient(create_app(Settings())) as client:
        response = client.post("/api/v1/predictions/fight", json=payload)
        swapped = client.post(
            "/api/v1/predictions/fight",
            json={
                **payload,
                "fighter_a_id": payload["fighter_b_id"],
                "fighter_b_id": payload["fighter_a_id"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["fighter_a_win_probability"] + body["fighter_b_win_probability"] == 1.0
    assert body["bundle_hash"] == runtime.bundle_hash
    assert body["operating_points"]["default_full_coverage"]["covered"] is True
    assert swapped.status_code == 200
    assert body["fighter_a_win_probability"] == swapped.json()["fighter_b_win_probability"]


def test_fight_prediction_rejects_identical_or_unavailable_fighters() -> None:
    runtime = ChampionRuntime()
    row = next(iter(runtime._rows.values()))
    fighter = str(row["canonical_fighter_a_id"])
    target = str(row["fight_date"])
    with TestClient(create_app(Settings())) as client:
        identical = client.post(
            "/api/v1/predictions/fight",
            json={
                "fighter_a_id": fighter,
                "fighter_b_id": fighter,
                "target_fight_date": target,
            },
        )
        unavailable = client.post(
            "/api/v1/predictions/fight",
            json={
                "fighter_a_id": fighter,
                "fighter_b_id": "not-a-fighter",
                "target_fight_date": target,
            },
        )

    assert identical.status_code == 422
    assert unavailable.status_code == 422
    assert unavailable.json()["error"]["code"] == "prediction_materialization_unavailable"


def test_fight_prediction_rejects_invalid_dates() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.post(
            "/api/v1/predictions/fight",
            json={
                "fighter_a_id": "fighter-a",
                "fighter_b_id": "fighter-b",
                "target_fight_date": "not-a-date",
            },
        )

    assert response.status_code == 422
