"""Tests for M8 prediction service features: caching, idempotency, persistence, and queries."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ufc_api.core.config import Settings
from ufc_api.main import create_app
from ufc_predictor.inference.m5_champion import ChampionRuntime


def test_matchup_prediction_caching_and_idempotency() -> None:
    settings = Settings()
    runtime = ChampionRuntime()
    row = next(iter(runtime._rows.values()))
    with TestClient(create_app(settings)) as client:
        payload = {
            "fighter_a_id": str(row["canonical_fighter_a_id"]),
            "fighter_b_id": str(row["canonical_fighter_b_id"]),
            "target_fight_date": str(row["fight_date"]),
            "scheduled_rounds": 3,
            "mode": "pure",
            "persist": False,
        }

        # 1. Initial request -> Cache MISS
        res1 = client.post(
            "/api/v1/predictions/matchup",
            json=payload,
            headers={"Idempotency-Key": "test-key-12345"},
        )
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["fighter_a_id"] == payload["fighter_a_id"]
        assert "fighter_a_win_probability" in data1
        assert data1["method_probabilities"] is None
        assert data1["round_distribution"] is None
        assert data1["prediction_id"] is not None
        pred_id = data1["prediction_id"]

        # 2. Duplicate request with same Idempotency-Key -> Hit idempotent cache
        res2 = client.post(
            "/api/v1/predictions/matchup",
            json=payload,
            headers={"Idempotency-Key": "test-key-12345"},
        )
        assert res2.status_code == 200
        assert res2.headers.get("X-Cache") == "HIT-IDEMPOTENT"
        assert res2.json()["prediction_id"] == pred_id

        conflicting_payload = {**payload, "scheduled_rounds": 5}
        conflict = client.post(
            "/api/v1/predictions/matchup",
            json=conflicting_payload,
            headers={"Idempotency-Key": "test-key-12345"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_key_conflict"

        # 3. Request without idempotency key -> Hit standard cache
        res3 = client.post(
            "/api/v1/predictions/matchup",
            json=payload,
        )
        assert res3.status_code == 200
        assert res3.headers.get("X-Cache") == "HIT"

        # 4. An uncached response is not a durable snapshot.
        res4 = client.get(f"/api/v1/predictions/{pred_id}")
        assert res4.status_code == 404

        payload["persist"] = True
        assert client.post("/api/v1/predictions/matchup", json=payload).status_code == 501

        payload["persist"] = False
        payload["mode"] = "market"
        assert client.post("/api/v1/predictions/matchup", json=payload).status_code == 422


def test_prediction_not_found_returns_404() -> None:
    settings = Settings()
    with TestClient(create_app(settings)) as client:
        res = client.get("/api/v1/predictions/00000000-0000-0000-0000-000000000000")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "prediction_not_found"


def test_fight_predictions_list_endpoint() -> None:
    settings = Settings()
    with TestClient(create_app(settings)) as client:
        res = client.get("/api/v1/predictions/fights/fake-fight-id")
        assert res.status_code == 200
        data = res.json()
        assert "items" in data
        assert isinstance(data["items"], list)
