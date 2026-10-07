"""Celery application, queue routing, and background inference tasks."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from celery import Celery

from ufc_api.core.config import get_settings
from ufc_api.data.parquet_catalog import resolve_canonical_fighter_id
from ufc_api.jobs.router import update_job
from ufc_predictor.inference.m5_champion import ChampionRuntime
from ufc_predictor.simulation.engine import SimulationEngine

logger = logging.getLogger(__name__)

settings = get_settings()
celery_app = Celery(
    "ufc_predictor",
    broker=settings.redis_url.get_secret_value() if settings.redis_url else None,
)
celery_app.conf.update(
    task_default_queue="maintenance",
    task_routes={
        "ufc_api.ingestion.*": {"queue": "ingestion-low"},
        "ufc_api.data.*": {"queue": "data"},
        "ufc_api.training.*": {"queue": "training"},
        "ufc_api.inference.*": {"queue": "inference"},
        "ufc_api.simulations.*": {"queue": "simulation"},
    },
    task_acks_late=True,
    task_track_started=True,
)


@celery_app.task(name="ufc_api.inference.compute_async_prediction", bind=True)  # type: ignore[misc]
def compute_async_prediction(
    self: Any,
    job_id: str,
    fighter_a_id: str,
    fighter_b_id: str,
    target_fight_date: str,
    scheduled_rounds: int = 3,
    mode: str = "pure",
) -> dict[str, Any]:
    """Background prediction task updating job tracker upon completion."""
    update_job(job_id, state="running", started_at=datetime.now(UTC), progress=0.25)
    try:
        if mode != "pure":
            raise ValueError("Only the pure winner model is available")
        runtime = ChampionRuntime(bundle_path=Path(settings.champion_bundle_path))
        scored = runtime.predict(
            resolve_canonical_fighter_id(fighter_a_id),
            resolve_canonical_fighter_id(fighter_b_id),
            date.fromisoformat(target_fight_date),
        )
        result = {
            "fighter_a_id": scored.fighter_a_id,
            "fighter_b_id": scored.fighter_b_id,
            "target_fight_date": target_fight_date,
            "fighter_a_win_probability": scored.probability_a,
            "fighter_b_win_probability": scored.probability_b,
            "model_bundle_hash": runtime.bundle_hash,
        }
        update_job(
            job_id,
            state="succeeded",
            completed_at=datetime.now(UTC),
            progress=1.0,
            result_url=f"/api/v1/jobs/{job_id}/result",
        )
        return result
    except Exception as exc:
        logger.exception("Async prediction task failed for job %s", job_id)
        update_job(
            job_id,
            state="failed",
            completed_at=datetime.now(UTC),
            error=str(exc),
        )
        raise


@celery_app.task(name="ufc_api.simulations.compute_async_simulation", bind=True)  # type: ignore[misc]
def compute_async_simulation(
    self: Any,
    job_id: str,
    simulation_payload: dict[str, Any],
) -> dict[str, Any]:
    """Background Monte Carlo simulation task."""
    update_job(job_id, state="running", started_at=datetime.now(UTC), progress=0.1)
    try:
        runtime = ChampionRuntime(bundle_path=Path(settings.champion_bundle_path))
        engine = SimulationEngine(runtime)
        simulated = engine.run_monte_carlo(
            resolve_canonical_fighter_id(str(simulation_payload["fighter_a_id"])),
            resolve_canonical_fighter_id(str(simulation_payload["fighter_b_id"])),
            date.fromisoformat(str(simulation_payload["target_fight_date"])),
            iterations=int(simulation_payload.get("iterations", 10000)),
            seed=int(simulation_payload.get("seed", 42)),
            scheduled_rounds=int(simulation_payload.get("scheduled_rounds", 3)),
        )
        result = {
            "iterations_completed": simulated.iterations,
            "fighter_a_win_probability": simulated.simulated_win_rate_a,
            "fighter_b_win_probability": simulated.simulated_win_rate_b,
            "method_distribution": simulated.method_distribution,
            "round_distribution": simulated.round_distribution,
        }
        update_job(
            job_id,
            state="succeeded",
            completed_at=datetime.now(UTC),
            progress=1.0,
            result_url=f"/api/v1/jobs/{job_id}/result",
        )
        return result
    except Exception as exc:
        logger.exception("Async simulation task failed for job %s", job_id)
        update_job(
            job_id,
            state="failed",
            completed_at=datetime.now(UTC),
            error=str(exc),
        )
        raise


@celery_app.task(name="ufc_api.inference.snapshot_card_predictions")  # type: ignore[misc]
def snapshot_card_predictions(event_id: str) -> dict[str, Any]:
    """Scheduled task to freeze and store prediction snapshots for an entire card."""
    logger.info("Snapshotting predictions for upcoming card event %s", event_id)
    raise RuntimeError("Scheduled card snapshot execution is not configured")
