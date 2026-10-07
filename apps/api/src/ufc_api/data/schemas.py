"""Public schemas for data governance, source policy, and freshness."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SourceFreshness(BaseModel):
    """Freshness and governance status for one audited data source."""

    source_id: str
    stable_key: str
    display_name: str
    source_type: str
    audit_state: str
    dataset_license: str | None = None
    last_observation_timestamp: datetime | None = None
    last_retrieval_timestamp: datetime | None = None
    last_published_timestamp: datetime | None = None
    published_records_count: int = 0
    quarantined_records_count: int = 0
    open_quality_issues_count: int = 0
    expected_cadence: str = "manual_audited_ingestion"
    status: str = "healthy"


class DataFreshnessResponse(BaseModel):
    """User-facing per-source and derived freshness summary."""

    sources: list[SourceFreshness]
    accepted_dataset_generation_id: str
    prediction_cutoff_date: str
    summary_timestamp: datetime
    limitations: list[str] = Field(default_factory=list)
