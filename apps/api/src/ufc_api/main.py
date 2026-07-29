"""FastAPI application factory for the UFC Predictor modular monolith."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ufc_api import __version__
from ufc_api.core.config import Settings, get_settings
from ufc_api.core.errors import DomainError, domain_error_handler, unexpected_error_response
from ufc_api.core.logging import configure_logging
from ufc_api.core.middleware import RequestContextMiddleware
from ufc_api.predictions.champion import router as champion_prediction_router
from ufc_predictor.inference.m5_champion import ChampionRuntime


class HealthResponse(BaseModel):
    """Process-only liveness response."""

    status: str
    version: str
    release_sha: str


class ReadinessResponse(BaseModel):
    """Foundation readiness response that does not claim unimplemented dependencies are live."""

    status: str
    environment: str
    capabilities: dict[str, str]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the API application without importing domain-specific services."""

    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level, resolved_settings.log_format)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.champion_runtime = ChampionRuntime(
            bundle_path=Path(resolved_settings.champion_bundle_path)
        )
        yield

    app = FastAPI(
        title="UFC Predictor API",
        version=__version__,
        description=(
            "Reproducible pre-fight UFC analytics. Outputs are uncertain estimates, "
            "not betting advice."
        ),
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.include_router(champion_prediction_router)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(Exception, unexpected_error_response)
    app.add_middleware(
        RequestContextMiddleware, request_id_header=resolved_settings.request_id_header
    )
    if resolved_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=[resolved_settings.request_id_header, "Content-Type", "Idempotency-Key"],
        )

    @app.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok", version=__version__, release_sha=resolved_settings.release_sha
        )

    @app.get("/readiness", response_model=ReadinessResponse, tags=["operations"])
    async def readiness(_: Request) -> ReadinessResponse:
        return ReadinessResponse(
            status="ready",
            environment=resolved_settings.app_env,
            capabilities={
                "database": "not_checked_until_milestone_7",
                "redis": "not_checked_until_milestone_7",
                "model_runtime": "ready_m5_champion_bundle",
            },
        )

    return app
