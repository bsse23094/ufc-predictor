"""API Router for pre-fight prediction explanations."""

from __future__ import annotations

from datetime import date
from typing import Annotated, cast

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from ufc_api.core.errors import DomainError
from ufc_api.data.parquet_catalog import resolve_canonical_fighter_id
from ufc_predictor.explain.attribution import AttributionEngine
from ufc_predictor.inference.m5_champion import ChampionRuntime

router = APIRouter(prefix="/api/v1/explanations", tags=["explanations"])


class FeatureContributionResponse(BaseModel):
    factor_name: str
    category: str
    impact_score: float
    direction: str
    description: str


class ModelFactorResponse(BaseModel):
    factor_name: str
    impact_probability_points: float
    direction: str
    description: str


class PredictionExplanationResponse(BaseModel):
    fighter_a_id: str
    fighter_b_id: str
    model_version: str
    top_factors: list[FeatureContributionResponse]
    model_factors: list[ModelFactorResponse]
    model_baseline_probability_a: float
    missing_data_caveats: list[str]
    baseline_cohort: str = "2020-2026_canonical_ufc_bouts"
    algorithm: str = "symmetric_xgboost_margin_allocation_v1"
    disclaimer: str


def _runtime(request: Request) -> ChampionRuntime:
    runtime = getattr(request.app.state, "champion_runtime", None)
    if runtime is None:
        raise DomainError(
            code="model_runtime_unavailable",
            message="Model runtime is not loaded.",
            status_code=503,
        )
    return cast(ChampionRuntime, runtime)


@router.get(
    "",
    response_model=PredictionExplanationResponse,
    summary="Get model factor allocation and pre-fight comparisons",
)
async def get_prediction_explanation(
    request: Request,
    fighter_a_id: Annotated[str, Query(min_length=1)],
    fighter_b_id: Annotated[str, Query(min_length=1)],
    target_fight_date: Annotated[date | None, Query()] = None,
) -> PredictionExplanationResponse:
    resolved_a = resolve_canonical_fighter_id(fighter_a_id)
    resolved_b = resolve_canonical_fighter_id(fighter_b_id)

    if resolved_a == resolved_b:
        raise DomainError(
            code="invalid_fighters",
            message="Fighter A and Fighter B must be distinct.",
            status_code=422,
        )

    resolved_date = target_fight_date or date.today()
    runtime = _runtime(request)
    engine = AttributionEngine(runtime)

    try:
        res = engine.explain_prediction(resolved_a, resolved_b, resolved_date)
    except Exception as exc:
        raise DomainError(
            code="explanation_failed",
            message=f"Prediction explanation could not be computed: {exc}",
            status_code=422,
        ) from exc

    return PredictionExplanationResponse(
        fighter_a_id=res.fighter_a_id,
        fighter_b_id=res.fighter_b_id,
        model_version=res.model_version,
        top_factors=[
            FeatureContributionResponse(
                factor_name=f.factor_name,
                category=f.category,
                impact_score=f.impact_score,
                direction=f.direction,
                description=f.description,
            )
            for f in res.top_factors
        ],
        model_factors=[
            ModelFactorResponse(
                factor_name=f.factor_name,
                impact_probability_points=f.impact_probability_points,
                direction=f.direction,
                description=f.description,
            )
            for f in res.model_factors
        ],
        model_baseline_probability_a=res.model_baseline_probability_a,
        missing_data_caveats=res.missing_data_caveats,
        baseline_cohort=res.baseline_cohort,
        algorithm=res.algorithm,
        disclaimer=res.disclaimer,
    )
