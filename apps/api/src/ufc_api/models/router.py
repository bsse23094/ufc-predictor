"""Model cards and evaluation metrics API router."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Request

from ufc_api.core.errors import DomainError, ErrorDetail
from ufc_api.models.schemas import (
    CalibrationBin,
    EvaluationSummary,
    ModelSummaryMetrics,
    PublicModelCard,
)
from ufc_predictor.inference.m5_champion import ChampionRuntime

router = APIRouter(prefix="/api/v1/models", tags=["models"])


def _runtime(request: Request) -> ChampionRuntime:
    return cast(ChampionRuntime, request.app.state.champion_runtime)


@router.get("", response_model=list[PublicModelCard], summary="List published model cards")
async def list_models(request: Request) -> list[PublicModelCard]:
    """Return published model cards disclosing architecture, features, and metrics."""
    runtime = _runtime(request)
    bundle = runtime.bundle
    cov = bundle["full_coverage_metrics"]["covered_metrics"]
    cal = bundle["full_coverage_metrics"]["calibration"]

    metrics = ModelSummaryMetrics(
        accuracy=float(cov["accuracy"]),
        balanced_accuracy=float(cov["balanced_accuracy"]),
        brier_score=float(cov["brier_score"]),
        log_loss=float(cov["log_loss"]),
        roc_auc=float(cov["roc_auc"]),
        expected_calibration_error=float(cal["expected_calibration_error"]),
        evaluated_row_count=int(cov["row_count"]),
    )

    card = PublicModelCard(
        model_id=str(bundle["champion_id"]),
        family=str(bundle["model"]["family"]),
        promotion_status="champion",
        feature_count=int(bundle["feature_contract"]["feature_count"]),
        feature_schema_version=str(bundle["feature_contract"]["feature_schema_version"]),
        training_cutoff_date=str(bundle["training_date_cutoff"]),
        bundle_hash=runtime.bundle_hash,
        metrics=metrics,
        operating_points={
            name: float(margin)
            for name, margin in bundle["confidence_operating_points"]["recommended"].items()
        },
        limitations=list(bundle.get("limitations", [])),
    )
    return [card]


@router.get(
    "/{model_id}/metrics",
    response_model=EvaluationSummary,
    summary="Get model evaluation metrics and calibration curves",
    responses={404: {"description": "Model not found"}},
)
async def get_model_metrics(model_id: str, request: Request) -> EvaluationSummary:
    """Return comprehensive out-of-time evaluation metrics, calibration curve, and margins."""
    runtime = _runtime(request)
    bundle = runtime.bundle
    champion_id = str(bundle["champion_id"])

    if model_id != champion_id and model_id != "champion":
        raise DomainError(
            code="model_not_found",
            message=f"Model {model_id} was not found in the model registry.",
            status_code=404,
            details=[ErrorDetail(field="model_id", reason="unknown model identifier")],
        )

    cov = bundle["full_coverage_metrics"]["covered_metrics"]
    cal = bundle["full_coverage_metrics"]["calibration"]

    metrics = ModelSummaryMetrics(
        accuracy=float(cov["accuracy"]),
        balanced_accuracy=float(cov["balanced_accuracy"]),
        brier_score=float(cov["brier_score"]),
        log_loss=float(cov["log_loss"]),
        roc_auc=float(cov["roc_auc"]),
        expected_calibration_error=float(cal["expected_calibration_error"]),
        evaluated_row_count=int(cov["row_count"]),
    )

    bins = [
        CalibrationBin(
            lower_inclusive=float(b["lower_inclusive"]),
            upper_exclusive=float(b["upper_exclusive"]) if b.get("upper_exclusive") else None,
            upper_inclusive=float(b["upper_inclusive"]) if b.get("upper_inclusive") else None,
            count=int(b["count"]),
            mean_predicted_probability=(
                float(b["mean_predicted_probability"])
                if b.get("mean_predicted_probability") is not None
                else None
            ),
            observed_positive_rate=(
                float(b["observed_positive_rate"])
                if b.get("observed_positive_rate") is not None
                else None
            ),
        )
        for b in cal.get("bins", [])
    ]

    return EvaluationSummary(
        model_id=champion_id,
        bundle_hash=runtime.bundle_hash,
        benchmark_period={
            "date_start": str(bundle["inspected_benchmark"]["date_start"]),
            "date_end": str(bundle["inspected_benchmark"]["date_end"]),
        },
        metrics=metrics,
        calibration_bins=bins,
        confidence_operating_points=dict(bundle.get("confidence_operating_points", {})),
        limitations=list(bundle.get("limitations", [])),
    )
