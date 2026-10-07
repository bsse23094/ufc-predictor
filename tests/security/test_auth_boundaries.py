"""Security and role-based authorization boundary tests.

Verifies strict rejection of unauthenticated/unauthorized access to admin endpoints,
analyst vs admin role boundaries, and input injection resistance.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ufc_api.core.config import Settings
from ufc_api.main import create_app


def test_admin_endpoints_reject_unauthenticated_requests() -> None:
    settings = Settings(admin_api_keys="secret-admin-key", analyst_api_keys="secret-analyst-key")
    with TestClient(create_app(settings)) as client:
        # Without X-API-Key header -> role is 'public', rejected with 403 forbidden
        res1 = client.post(
            "/api/v1/admin/ingestion-runs",
            json={"source_id": "00000000-0000-0000-0000-000000000001", "mode": "incremental"},
        )
        assert res1.status_code == 403
        assert res1.json()["error"]["code"] == "forbidden"

        res2 = client.get("/api/v1/admin/data-quality-issues")
        assert res2.status_code == 403

        res3 = client.post(
            "/api/v1/admin/models/test-model/promote",
            json={"target_alias": "champion", "approval_note": "Production test"},
        )
        assert res3.status_code == 403


def test_admin_endpoints_reject_invalid_api_key() -> None:
    settings = Settings(admin_api_keys="secret-admin-key", analyst_api_keys="secret-analyst-key")
    with TestClient(create_app(settings)) as client:
        res = client.get(
            "/api/v1/admin/data-quality-issues",
            headers={"X-API-Key": "completely-invalid-key"},
        )
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "forbidden"


def test_analyst_key_rejected_on_admin_only_endpoints() -> None:
    settings = Settings(admin_api_keys="secret-admin-key", analyst_api_keys="secret-analyst-key")
    with TestClient(create_app(settings)) as client:
        # Analyst key is rejected on admin-only route
        res = client.post(
            "/api/v1/admin/ingestion-runs",
            json={"source_id": "00000000-0000-0000-0000-000000000001", "mode": "incremental"},
            headers={"X-API-Key": "secret-analyst-key"},
        )
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "forbidden"


def test_admin_key_allows_administrative_mutations() -> None:
    settings = Settings(admin_api_keys="secret-admin-key", analyst_api_keys="secret-analyst-key")
    with TestClient(create_app(settings)) as client:
        res = client.get(
            "/api/v1/admin/data-quality-issues",
            headers={"X-API-Key": "secret-admin-key"},
        )
        assert res.status_code == 200
        assert "items" in res.json()


def test_sql_injection_patterns_handled_safely_in_search() -> None:
    settings = Settings()
    with TestClient(create_app(settings)) as client:
        # Search query with classic SQL injection strings
        injections = [
            "' OR '1'='1",
            "'; DROP TABLE fighters; --",
            '" UNION SELECT * FROM users --',
            "1' UNION ALL SELECT NULL, NULL, NULL--",
        ]
        for payload in injections:
            res = client.get(f"/api/v1/fighters?query={payload}")
            # Must return 200 with sanitized search, never 500
            assert res.status_code == 200
            assert "items" in res.json()
