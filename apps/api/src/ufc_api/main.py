"""FastAPI application factory for the UFC Predictor modular monolith."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ufc_api import __version__
from ufc_api.admin.router import router as admin_router
from ufc_api.core.config import Settings, get_settings
from ufc_api.core.errors import DomainError, domain_error_handler, unexpected_error_response
from ufc_api.core.logging import configure_logging
from ufc_api.core.middleware import RequestContextMiddleware
from ufc_api.data.router import router as data_router
from ufc_api.db.session import build_session_factory
from ufc_api.events.router import router as events_router
from ufc_api.explanations.router import router as explanations_router
from ufc_api.fighters.router import router as fighters_router
from ufc_api.fights.router import router as fights_router
from ufc_api.jobs.router import router as jobs_router
from ufc_api.models.router import router as models_router
from ufc_api.predictions.champion import router as champion_prediction_router
from ufc_api.similarity.router import router as similarity_router
from ufc_api.simulations.router import router as simulations_router
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
        bundle_path = Path(resolved_settings.champion_bundle_path)
        if not bundle_path.is_file():
            for parent in Path(__file__).resolve().parents:
                candidate = parent / bundle_path
                if candidate.is_file():
                    bundle_path = candidate
                    break
        application.state.champion_runtime = ChampionRuntime(bundle_path=bundle_path)
        if resolved_settings.database_url is not None:
            application.state.session_factory = build_session_factory(resolved_settings)
        else:
            application.state.session_factory = None

        # Redis connection (optional; degrades gracefully)
        application.state.redis = None
        if resolved_settings.redis_url is not None:
            try:
                import redis.asyncio as aioredis

                application.state.redis = aioredis.from_url(  # type: ignore[no-untyped-call]
                    resolved_settings.redis_url.get_secret_value(),
                    decode_responses=True,
                )
            except Exception:
                pass
        yield
        # Cleanup
        if application.state.redis is not None:
            with suppress(Exception):
                await application.state.redis.aclose()

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
    app.include_router(data_router)
    app.include_router(events_router)
    app.include_router(fighters_router)
    app.include_router(fights_router)
    app.include_router(models_router)
    app.include_router(champion_prediction_router)
    app.include_router(simulations_router)
    app.include_router(similarity_router)
    app.include_router(explanations_router)
    app.include_router(admin_router)
    app.include_router(jobs_router)

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
    @app.get(
        "/readyz",
        response_model=ReadinessResponse,
        tags=["operations"],
        include_in_schema=False,
    )
    async def readiness(request: Request) -> ReadinessResponse:
        capabilities: dict[str, str] = {}

        # Database check
        db_factory = getattr(request.app.state, "session_factory", None)
        if db_factory is not None:
            try:
                from sqlalchemy import text

                async with db_factory() as session:
                    await session.execute(text("SELECT 1"))
                capabilities["database"] = "ready"
            except Exception:
                capabilities["database"] = "degraded"
        else:
            capabilities["database"] = "not_configured"

        # Redis check
        redis_client = getattr(request.app.state, "redis", None)
        if redis_client is not None:
            try:
                await redis_client.ping()
                capabilities["redis"] = "ready"
            except Exception:
                capabilities["redis"] = "degraded"
        else:
            capabilities["redis"] = "not_configured"

        # Model runtime check
        runtime = getattr(request.app.state, "champion_runtime", None)
        if runtime is not None and hasattr(runtime, "bundle"):
            capabilities["model_runtime"] = "ready"
        else:
            capabilities["model_runtime"] = "not_loaded"

        all_ready = all(v in ("ready", "not_configured") for v in capabilities.values())
        status = "ready" if all_ready else "degraded"

        return ReadinessResponse(
            status=status,
            environment=resolved_settings.app_env,
            capabilities=capabilities,
        )

    return app


app = create_app()
