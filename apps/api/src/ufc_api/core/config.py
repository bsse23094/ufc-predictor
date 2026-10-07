"""Strict, environment-based API configuration.

The foundation deliberately validates production-only safety requirements early.
Database, Redis, and model connectivity checks are added with their owning domains.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a local ignored `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    app_env: Literal["local", "test", "staging", "production"] = "local"
    release_sha: str = "development"
    image_digest: str | None = None
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    request_id_header: str = "X-Request-ID"

    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    api_workers: int = Field(default=1, ge=1, le=32)
    database_url: SecretStr | None = None
    redis_url: SecretStr | None = None
    cors_allowed_origins: str = ""
    max_request_bytes: int = Field(default=1_048_576, ge=1_024, le=10_485_760)
    max_page_size: int = Field(default=100, ge=1, le=100)

    # Cache
    cache_default_ttl_seconds: int = Field(default=300, ge=0, le=86400)
    cache_catalog_ttl_seconds: int = Field(default=300, ge=0, le=86400)
    cache_prediction_ttl_seconds: int = Field(default=60, ge=0, le=86400)

    # Auth / rate limiting
    api_key_header: str = "X-API-Key"
    admin_api_keys: str = ""  # comma-separated admin keys
    analyst_api_keys: str = ""  # comma-separated analyst keys
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10000)

    oidc_issuer_url: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    model_artifact_trusted_prefixes: str = ""
    champion_bundle_path: str = (
        "data/processed/m4-final-champion/m3-74eeb9b7f49b5adca45e461a/m4_final_champion_bundle.json"
    )
    sportsdataio_mma_api_key: SecretStr | None = None
    audit_ip_hash_key: SecretStr | None = None

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        if "*" in origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must be an explicit allow-list")
        return ",".join(origins)

    @model_validator(mode="after")
    def enforce_production_safety(self) -> Settings:
        if self.app_env != "production":
            return self

        required = {
            "DATABASE_URL": self.database_url,
            "REDIS_URL": self.redis_url,
            "CORS_ALLOWED_ORIGINS": self.cors_allowed_origins,
            "OIDC_ISSUER_URL": self.oidc_issuer_url,
            "OIDC_AUDIENCE": self.oidc_audience,
            "OIDC_JWKS_URL": self.oidc_jwks_url,
            "MODEL_ARTIFACT_TRUSTED_PREFIXES": self.model_artifact_trusted_prefixes,
            "AUDIT_IP_HASH_KEY": self.audit_ip_hash_key,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"production configuration is missing: {', '.join(missing)}")
        return self

    @property
    def cors_origins(self) -> tuple[str, ...]:
        """Return an explicit, normalized origin tuple suitable for middleware."""

        return tuple(origin for origin in self.cors_allowed_origins.split(",") if origin)


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings object for the process lifetime."""

    return Settings()
