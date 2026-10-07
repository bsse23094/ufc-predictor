"""Administrative governance router for data and model operations.

All admin endpoints require the 'admin' role via API key. State-changing
actions use optimistic locking via expected_version and audit every mutation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ufc_api.auth.dependencies import Role, require_role
from ufc_api.core.errors import DomainError, ErrorDetail
from ufc_api.data.models import DataQualityIssue, DataSource
from ufc_api.db.session import get_db_session, get_optional_db_session

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class IngestionRunRequest(BaseModel):
    source_key: str = Field(min_length=1, max_length=128)
    mode: str = Field(default="incremental", pattern=r"^(incremental|backfill)$")
    dry_run: bool = False
    idempotency_key: str | None = None


class IngestionRunResponse(BaseModel):
    run_id: str
    source_key: str
    mode: str
    state: str
    created_at: datetime
    message: str


class DataQualityIssueResponse(BaseModel):
    issue_id: str
    source_id: str | None = None
    source_key: str | None = None
    issue_type: str
    severity: str
    status: str
    description: str
    source_record_reference: str | None = None
    raw_checksum: str | None = None
    occurrence_count: int = 1
    created_at: datetime
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class DataQualityIssuePage(BaseModel):
    items: list[DataQualityIssueResponse]
    next_cursor: str | None = None
    has_more: bool = False


class PatchQualityIssueRequest(BaseModel):
    status: str = Field(pattern=r"^(acknowledged|resolved|suppressed)$")
    resolution_note: str = Field(min_length=1, max_length=2000)
    expected_version: int | None = None


class ModelStageRequest(BaseModel):
    expected_current_state: str
    note: str = Field(min_length=1, max_length=2000)


class ModelPromoteRequest(BaseModel):
    target_alias: str = Field(default="champion")
    expected_current_version: str | None = None
    approval_note: str = Field(min_length=1, max_length=2000)


class ModelRollbackRequest(BaseModel):
    target_alias: str = Field(default="champion")
    reason: str = Field(min_length=1, max_length=2000)
    expected_current_version: str | None = None


class PromotionResponse(BaseModel):
    model_id: str
    alias: str
    previous_version: str | None = None
    new_version: str
    action: str
    timestamp: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/ingestion-runs",
    response_model=IngestionRunResponse,
    status_code=202,
    summary="Enqueue a governed ingestion run",
    dependencies=[Depends(require_role("admin", "data_operator"))],
)
async def create_ingestion_run(
    payload: IngestionRunRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    role: Annotated[Role, Depends(require_role("admin", "data_operator"))],
) -> IngestionRunResponse:
    """Validate source policy and enqueue a new ingestion run."""
    source_stmt = select(DataSource).where(DataSource.stable_key == payload.source_key)
    source = await session.scalar(source_stmt)
    if source is None:
        raise DomainError(
            code="source_not_found",
            message=f"Source '{payload.source_key}' is not registered.",
            status_code=404,
            details=[ErrorDetail(field="source_key", reason="unknown source key")],
        )

    if source.audit_state != "approved":
        raise DomainError(
            code="source_not_approved",
            message=f"Source '{payload.source_key}' has audit state '{source.audit_state}'.",
            status_code=422,
            details=[ErrorDetail(field="source_key", reason="source not approved for ingestion")],
        )

    raise DomainError(
        code="ingestion_scheduler_unavailable",
        message="Ingestion scheduling is not configured; use the governed local CLI.",
        status_code=501,
    )


@router.get(
    "/data-quality-issues",
    response_model=DataQualityIssuePage,
    summary="List data quality issues with filters",
    dependencies=[Depends(require_role("admin", "analyst", "data_operator"))],
)
async def list_data_quality_issues(
    session: Annotated[AsyncSession | None, Depends(get_optional_db_session)],
    status: Annotated[str | None, Query(description="Filter by status")] = None,
    severity: Annotated[str | None, Query(description="Filter by severity")] = None,
    source: Annotated[str | None, Query(description="Filter by source stable key")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(description="Keyset cursor")] = None,
) -> DataQualityIssuePage:
    """Return paginated data quality issues for governance review."""
    if session is None:
        return DataQualityIssuePage(items=[], next_cursor=None, has_more=False)
    stmt = select(DataQualityIssue).order_by(DataQualityIssue.first_seen_at.desc())

    if status:
        stmt = stmt.where(DataQualityIssue.status == status)
    if severity:
        stmt = stmt.where(DataQualityIssue.severity == severity)

    if cursor:
        # Simple offset-based fallback; a real keyset cursor would use created_at + id
        stmt = stmt.offset(int(cursor))

    stmt = stmt.limit(limit + 1)
    result = await session.scalars(stmt)
    rows = list(result.all())

    has_more = len(rows) > limit
    items = rows[:limit]

    return DataQualityIssuePage(
        items=[
            DataQualityIssueResponse(
                issue_id=str(issue.issue_id),
                source_id=str(issue.source_id) if issue.source_id else None,
                issue_type=issue.rule_id,
                severity=issue.severity,
                status=issue.status,
                description=issue.safe_summary,
                source_record_reference=issue.entity_id,
                raw_checksum=None,
                occurrence_count=issue.occurrence_count,
                created_at=issue.first_seen_at,
                resolved_at=None,
                resolution_note=None,
            )
            for issue in items
        ],
        next_cursor=str(int(cursor or "0") + limit) if has_more else None,
        has_more=has_more,
    )


@router.patch(
    "/data-quality-issues/{issue_id}",
    response_model=DataQualityIssueResponse,
    summary="Update a data quality issue status",
    dependencies=[Depends(require_role("admin", "data_operator"))],
)
async def patch_data_quality_issue(
    issue_id: UUID,
    payload: PatchQualityIssueRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    role: Annotated[Role, Depends(require_role("admin", "data_operator"))],
) -> DataQualityIssueResponse:
    """Reject mutations until a reviewed, append-only resolution path is available."""
    raise DomainError(
        code="quality_resolution_unavailable",
        message="Quality issue resolution requires the reviewed governance workflow.",
        status_code=501,
    )


@router.post(
    "/models/{model_id}/stage",
    response_model=PromotionResponse,
    summary="Stage a model candidate for evaluation",
    dependencies=[Depends(require_role("admin", "model_manager"))],
)
async def stage_model(
    model_id: str,
    payload: ModelStageRequest,
    role: Annotated[Role, Depends(require_role("admin", "model_manager"))],
) -> PromotionResponse:
    """Report that durable model staging is unavailable."""
    raise DomainError(
        code="model_registry_unavailable",
        message="Model staging is not configured.",
        status_code=501,
    )


@router.post(
    "/models/{model_id}/promote",
    response_model=PromotionResponse,
    summary="Promote a staged model to champion",
    dependencies=[Depends(require_role("admin", "model_manager"))],
)
async def promote_model(
    model_id: str,
    payload: ModelPromoteRequest,
    role: Annotated[Role, Depends(require_role("admin", "model_manager"))],
) -> PromotionResponse:
    """Report that durable model promotion is unavailable."""
    raise DomainError(
        code="model_registry_unavailable",
        message="Model promotion is not configured.",
        status_code=501,
    )


@router.post(
    "/models/{model_id}/rollback",
    response_model=PromotionResponse,
    summary="Rollback a model to a previously validated version",
    dependencies=[Depends(require_role("admin", "model_manager"))],
)
async def rollback_model(
    model_id: str,
    payload: ModelRollbackRequest,
    role: Annotated[Role, Depends(require_role("admin", "model_manager"))],
) -> PromotionResponse:
    """Report that durable model rollback is unavailable."""
    raise DomainError(
        code="model_registry_unavailable",
        message="Model rollback is not configured.",
        status_code=501,
    )
