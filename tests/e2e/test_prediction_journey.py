"""End-to-end user journey test for discovery, prediction, explanation, and simulation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ufc_api.core.config import Settings
from ufc_api.main import create_app
from ufc_predictor.inference.m5_champion import ChampionRuntime


def test_complete_prediction_analytical_journey() -> None:
    settings = Settings()
    runtime = ChampionRuntime()
    row = next(iter(runtime._rows.values()))
    fighter_a_id = str(row["canonical_fighter_a_id"])
    fighter_b_id = str(row["canonical_fighter_b_id"])
    target_date = str(row["fight_date"])

    with TestClient(create_app(settings)) as client:
        # Step 1: The expired local card is not presented as upcoming.
        res_events = client.get("/api/v1/events")
        assert res_events.status_code == 200
        event_data = res_events.json()
        assert event_data["items"] == []

        # Step 2: Search fighters in roster
        res_fighters = client.get("/api/v1/fighters?limit=10")
        assert res_fighters.status_code == 200
        fighters = res_fighters.json()["items"]
        assert len(fighters) > 0

        # Step 3: Run matchup prediction
        pred_payload = {
            "fighter_a_id": fighter_a_id,
            "fighter_b_id": fighter_b_id,
            "target_fight_date": target_date,
            "scheduled_rounds": 3,
            "mode": "pure",
            "persist": False,
        }
        res_pred = client.post(
            "/api/v1/predictions/matchup",
            json=pred_payload,
            headers={"Idempotency-Key": "e2e-journey-key-1"},
        )
        assert res_pred.status_code == 200
        pred_data = res_pred.json()
        pred_id = pred_data["prediction_id"]
        assert pred_id is not None
        sum_prob = pred_data["fighter_a_win_probability"] + pred_data["fighter_b_win_probability"]
        assert sum_prob == 1.0

        # Step 4: Explain the prediction
        exp_url = (
            f"/api/v1/explanations?fighter_a_id={fighter_a_id}"
            f"&fighter_b_id={fighter_b_id}&target_fight_date={target_date}"
        )
        res_exp = client.get(exp_url)
        assert res_exp.status_code == 200
        exp_data = res_exp.json()
        assert "top_factors" in exp_data
        assert len(exp_data["top_factors"]) > 0

        # Step 5: Run counterfactual what-if simulation
        cf_payload = {
            "fighter_a_id": fighter_a_id,
            "fighter_b_id": fighter_b_id,
            "target_fight_date": target_date,
            "adjustments": {"reach_advantage_cms": 5.0, "takedown_defense_pct": 0.15},
        }
        res_cf = client.post("/api/v1/simulations/counterfactual", json=cf_payload)
        assert res_cf.status_code == 200
        cf_data = res_cf.json()
        assert "counterfactual_probability_a" in cf_data
        assert "probability_delta_a" in cf_data

        # Step 6: Run Monte Carlo stochastic simulation
        mc_payload = {
            "fighter_a_id": fighter_a_id,
            "fighter_b_id": fighter_b_id,
            "target_fight_date": target_date,
            "iterations": 1000,
            "scheduled_rounds": 3,
            "seed": 42,
        }
        res_mc = client.post("/api/v1/simulations/monte-carlo", json=mc_payload)
        assert res_mc.status_code == 200
        mc_data = res_mc.json()
        assert mc_data["iterations"] == 1000
        assert "method_distribution" in mc_data
        assert "round_distribution" in mc_data

        # Step 7: No durable snapshot exists for an uncached response.
        res_audit = client.get(f"/api/v1/predictions/{pred_id}")
        assert res_audit.status_code == 404
