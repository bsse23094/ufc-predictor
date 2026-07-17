from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from ufc_api.core.config import Settings


def test_wildcard_cors_is_rejected() -> None:
    with pytest.raises(ValidationError, match="explicit allow-list"):
        Settings(cors_allowed_origins="*")


def test_production_requires_security_critical_configuration() -> None:
    with pytest.raises(ValidationError, match="production configuration is missing"):
        Settings(app_env="production")


def test_secret_repr_is_redacted() -> None:
    settings = Settings(
        database_url=SecretStr("postgresql+asyncpg://user:secret@localhost:5432/db")
    )

    assert "secret" not in repr(settings)
