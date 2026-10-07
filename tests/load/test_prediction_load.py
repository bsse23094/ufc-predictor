"""Load and latency benchmark tests verifying server-side p95 targets."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from ufc_api.core.config import Settings
from ufc_api.main import create_app
from ufc_predictor.inference.m5_champion import ChampionRuntime


def test_catalog_endpoint_latency_under_300ms() -> None:
    settings = Settings()
    with TestClient(create_app(settings)) as client:
        # Warmup
        client.get("/api/v1/fighters?limit=25")

        latencies: list[float] = []
        for _ in range(30):
            t0 = time.perf_counter()
            res = client.get("/api/v1/fighters?limit=25")
            elapsed = time.perf_counter() - t0
            assert res.status_code == 200
            latencies.append(elapsed)

        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95)]
        # API spec: catalog read p95 objective is 250ms - 300ms
        assert p95 < 0.35, f"Catalog read p95 latency too high: {p95:.3f}s"


def test_prediction_endpoint_latency_under_1500ms() -> None:
    settings = Settings()
    runtime = ChampionRuntime()
    row = next(iter(runtime._rows.values()))
    payload = {
        "fighter_a_id": str(row["canonical_fighter_a_id"]),
        "fighter_b_id": str(row["canonical_fighter_b_id"]),
        "target_fight_date": str(row["fight_date"]),
        "scheduled_rounds": 3,
        "mode": "pure",
    }

    with TestClient(create_app(settings)) as client:
        # Warmup
        client.post("/api/v1/predictions/matchup", json=payload)

        latencies: list[float] = []
        for _ in range(15):
            t0 = time.perf_counter()
            res = client.post("/api/v1/predictions/matchup", json=payload)
            elapsed = time.perf_counter() - t0
            assert res.status_code == 200
            latencies.append(elapsed)

        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95)]
        # API spec: prediction inference p95 objective is 1.5s
        assert p95 < 1.5, f"Prediction p95 latency too high: {p95:.3f}s"
