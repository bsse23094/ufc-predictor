"""Data governance and freshness routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ufc_api.data.models import DataQualityIssue, DataSource, IngestionRunRecord
from ufc_api.data.schemas import DataFreshnessResponse, SourceFreshness
from ufc_api.db.session import get_optional_db_session

router = APIRouter(prefix="/api/v1/data", tags=["data-governance"])

ACCEPTED_M3_GENERATION_ID = "m3-74eeb9b7f49b5adca45e461a"
PREDICTION_CUTOFF_DATE = "2023-11-11"


@router.get(
    "/freshness",
    response_model=DataFreshnessResponse,
    summary="Data source freshness and governance summary",
)
async def get_data_freshness(
    session: Annotated[AsyncSession | None, Depends(get_optional_db_session)] = None,
    source: Annotated[str | None, Query(description="Filter by source stable key")] = None,
) -> DataFreshnessResponse:
    """Return per-source last observation, retrieval, publication, and quality issues."""
    if session is None:
        from ufc_api.data.parquet_catalog import ParquetCatalog

        return ParquetCatalog.get_data_freshness(source=source)

    stmt = select(DataSource).order_by(DataSource.stable_key.asc())
    if source:
        stmt = stmt.where(DataSource.stable_key == source.strip())

    result = await session.scalars(stmt)
    sources = list(result.all())

    items: list[SourceFreshness] = []
    for src in sources:
        run_stmt = (
            select(IngestionRunRecord)
            .where(IngestionRunRecord.source_id == src.source_id)
            .order_by(IngestionRunRecord.requested_at.desc())
            .limit(1)
        )
        latest_run = await session.scalar(run_stmt)

        issue_stmt = (
            select(func.count())
            .select_from(DataQualityIssue)
            .where(
                DataQualityIssue.source_id == src.source_id,
                DataQualityIssue.status == "open",
            )
        )
        open_issues = (await session.scalar(issue_stmt)) or 0

        status = "healthy"
        if open_issues > 0:
            status = "degraded"
        if latest_run and latest_run.status == "failed":
            status = "failed"

        items.append(
            SourceFreshness(
                source_id=str(src.source_id),
                stable_key=src.stable_key,
                display_name=src.display_name,
                source_type=src.source_type,
                audit_state=src.audit_state,
                dataset_license=src.dataset_license,
                last_observation_timestamp=latest_run.requested_at if latest_run else None,
                last_retrieval_timestamp=latest_run.requested_at if latest_run else None,
                last_published_timestamp=(
                    latest_run.published_at or latest_run.completed_at
                    if latest_run and latest_run.status == "published"
                    else None
                ),
                published_records_count=(
                    latest_run.accepted_count
                    if latest_run and latest_run.status == "published"
                    else 0
                ),
                quarantined_records_count=latest_run.quarantined_count if latest_run else 0,
                open_quality_issues_count=open_issues,
                expected_cadence="manual_audited_ingestion",
                status=status,
            )
        )

    return DataFreshnessResponse(
        sources=items,
        accepted_dataset_generation_id=ACCEPTED_M3_GENERATION_ID,
        prediction_cutoff_date=PREDICTION_CUTOFF_DATE,
        summary_timestamp=datetime.now(UTC),
        limitations=[
            (
                "Only approved, locally acquired datasets are ingested; "
                "automated UFCStats scraping is disabled."
            ),
            "Pre-fight features enforce strict cutoff dates before target bout.",
        ],
    )
