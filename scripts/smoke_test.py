"""Exercise the supported local API without assuming a current event card."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ufc_api.main import create_app
from ufc_predictor.inference.m5_champion import ChampionRuntime


def main() -> int:
    runtime = ChampionRuntime()
    row = next(iter(runtime._rows.values()))
    payload = {
        "fighter_a_id": str(row["canonical_fighter_a_id"]),
        "fighter_b_id": str(row["canonical_fighter_b_id"]),
        "target_fight_date": str(row["fight_date"]),
        "mode": "pure",
    }

    with TestClient(create_app()) as client:
        health = client.get("/health")
        assert health.status_code == 200 and health.json()["status"] == "ok"

        readiness = client.get("/readiness")
        assert readiness.status_code == 200
        assert readiness.json()["capabilities"]["model_runtime"] == "ready"

        model = client.get("/api/v1/models")
        assert model.status_code == 200 and model.json()

        fighters = client.get("/api/v1/fighters?limit=5")
        assert fighters.status_code == 200 and fighters.json()["items"]

        events = client.get("/api/v1/events")
        assert events.status_code == 200 and isinstance(events.json()["items"], list)

        prediction = client.post("/api/v1/predictions/matchup", json=payload)
        assert prediction.status_code == 200, prediction.text
        result = prediction.json()
        assert (
            abs(result["fighter_a_win_probability"] + result["fighter_b_win_probability"] - 1)
            < 1e-12
        )
        assert result["method_probabilities"] is None
        assert result["round_distribution"] is None

        assert (
            client.post(
                "/api/v1/predictions/matchup", json={**payload, "mode": "market"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/predictions/matchup", json={**payload, "persist": True}
            ).status_code
            == 501
        )

    print("Supported local API smoke check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
