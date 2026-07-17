"""Celery application and queue routing; task bodies live in owning domains."""

from __future__ import annotations

from celery import Celery

from ufc_api.core.config import get_settings

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
