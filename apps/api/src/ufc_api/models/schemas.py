"""Schemas for model registry and evaluation cards."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModelSummaryMetrics(BaseModel):
    """Core evaluation metrics on chronological rolling validation folds."""

    accuracy: float
    balanced_accuracy: float
    brier_score: float
    log_loss: float
    roc_auc: float
    expected_calibration_error: float
    evaluated_row_count: int


class PublicModelCard(BaseModel):
    """Public model card disclosing architecture, versions, and validation metrics."""

    model_id: str
    family: str
    promotion_status: str
    feature_count: int
    feature_schema_version: str
    training_cutoff_date: str
    bundle_hash: str
    metrics: ModelSummaryMetrics
    operating_points: dict[str, float]
    limitations: list[str] = Field(default_factory=list)


class CalibrationBin(BaseModel):
    """One bin of the model reliability / calibration diagram."""

    lower_inclusive: float
    upper_exclusive: float | None = None
    upper_inclusive: float | None = None
    count: int
    mean_predicted_probability: float | None = None
    observed_positive_rate: float | None = None


class EvaluationSummary(BaseModel):
    """Detailed evaluation summary including calibration curve and confidence coverage."""

    model_id: str
    bundle_hash: str
    benchmark_period: dict[str, str]
    metrics: ModelSummaryMetrics
    calibration_bins: list[CalibrationBin] = Field(default_factory=list)
    confidence_operating_points: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
