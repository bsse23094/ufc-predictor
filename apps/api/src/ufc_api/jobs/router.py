"""Job tracking schemas and router for async prediction/simulation work.

Jobs provide anonymous scoped retrieval via unguessable IDs. Admin jobs require
authorization. This satisfies the M8 requirement for async work tracking.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel

from ufc_api.core.errors import DomainError

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


# ---------------------------------------------------------------------------
# In-memory job store (PostgreSQL-backed store comes with M13 hardening)
# ---------------------------------------------------------------------------

_jobs: dict[str, dict[str, Any]] = {}


class JobResponse(BaseModel):
    """Public job status response per API specification."""

    job_id: str
    type: str
    state: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: float | None = None
    result_url: str | None = None
    error: str | None = None
    expires_at: datetime | None = None


class JobPage(BaseModel):
    items: list[JobResponse]
    next_cursor: str | None = None
    has_more: bool = False


def create_job(job_type: str, metadata: dict[str, Any] | None = None) -> str:
    """Register a new job and return its ID."""
    job_id = str(uuid4())
    now = datetime.now(UTC)
    _jobs[job_id] = {
        "job_id": job_id,
        "type": job_type,
        "state": "queued",
        "created_at": now,
        "started_at": None,
        "completed_at": None,
        "progress": 0.0,
        "result_url": None,
        "error": None,
        "expires_at": None,
        "metadata": metadata or {},
    }
    return job_id


def update_job(job_id: str, **kwargs: Any) -> None:
    """Update fields on an existing job."""
    if job_id in _jobs:
        _jobs[job_id].update(kwargs)


def get_job(job_id: str) -> dict[str, Any] | None:
    """Retrieve a job by ID."""
    return _jobs.get(job_id)


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="Check job status",
    responses={404: {"description": "Job not found"}, 410: {"description": "Job expired"}},
)
async def get_job_status(job_id: str) -> JobResponse:
    """Return the current status of an async job by its scoped ID."""
    job = get_job(job_id)
    if job is None:
        raise DomainError(
            code="job_not_found",
            message=f"Job {job_id} was not found.",
            status_code=404,
        )

    if job.get("expires_at") and datetime.now(UTC) > job["expires_at"]:
        raise DomainError(
            code="job_expired",
            message=f"Job {job_id} has expired.",
            status_code=410,
        )

    return JobResponse(
        job_id=job["job_id"],
        type=job["type"],
        state=job["state"],
        created_at=job["created_at"],
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
        progress=job.get("progress"),
        result_url=job.get("result_url"),
        error=job.get("error"),
        expires_at=job.get("expires_at"),
    )
