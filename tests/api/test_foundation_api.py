from __future__ import annotations

from fastapi.testclient import TestClient

from ufc_api.core.config import Settings
from ufc_api.main import create_app


def test_health_is_dependency_free_and_versioned() -> None:
    client = TestClient(create_app(Settings()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Request-ID"]


def test_readiness_does_not_claim_future_services_are_available() -> None:
    client = TestClient(create_app(Settings()))

    response = client.get("/readiness")

    assert response.status_code == 200
    assert response.json()["capabilities"]["database"] == "not_checked_until_milestone_7"
