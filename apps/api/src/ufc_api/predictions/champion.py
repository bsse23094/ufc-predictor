"""Public, safe API contract for M5 champion inference."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import cast

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, model_validator

from ufc_api.core.errors import DomainError, ErrorDetail
from ufc_predictor.inference.m5_champion import (
    ChampionRuntime,
    FeatureMaterializationUnavailable,
)

router = APIRouter(prefix="/api/v1/predictions", tags=["predictions"])


class FightPredictionRequest(BaseModel):
    """A canonical, date-specific request for a pre-fight prediction."""

    fighter_a_id: str = Field(min_length=1, max_length=128)
    fighter_b_id: str = Field(min_length=1, max_length=128)
    target_fight_date: date

    @model_validator(mode="after")
    def distinct_fighters(self) -> FightPredictionRequest:
        if self.fighter_a_id == self.fighter_b_id:
            raise ValueError("fighter_a_id and fighter_b_id must differ")
        return self


class ConfidenceStatus(BaseModel):
    margin: float
    covered: bool


class FightPredictionResponse(BaseModel):
    fighter_a_id: str
    fighter_b_id: str
    fighter_a_win_probability: float
    fighter_b_win_probability: float
    predicted_winner_id: str | None
    confidence_tier: str
    operating_points: dict[str, ConfidenceStatus]
    model_version: str
    feature_schema_version: str
    bundle_hash: str
    prediction_timestamp: datetime
    limitations: list[str]
    insufficient_history_indicators: list[str]
    feature_source: str
    history_cutoff_date: str
    fighter_history_counts: dict[str, int]


def _runtime(request: Request) -> ChampionRuntime:
    return cast(ChampionRuntime, request.app.state.champion_runtime)


@router.post(
    "/fight",
    response_model=FightPredictionResponse,
    responses={422: {"description": "Invalid request or unavailable pre-fight materialization"}},
)
async def predict_fight(
    payload: FightPredictionRequest, request: Request
) -> FightPredictionResponse:
    """Score only an accepted, strict-date pre-fight feature materialization."""

    try:
        prediction = _runtime(request).predict(
            payload.fighter_a_id, payload.fighter_b_id, payload.target_fight_date
        )
    except FeatureMaterializationUnavailable as exc:
        raise DomainError(
            code="prediction_materialization_unavailable",
            message="Prediction-safe pre-fight history is unavailable for this request.",
            status_code=422,
            details=[ErrorDetail(field="target_fight_date", reason=str(exc))],
        ) from exc
    runtime = _runtime(request)
    points = prediction.confidence
    tier = (
        "high"
        if bool(points["high_confidence"]["covered"])
        else "medium"
        if bool(points["medium_confidence"]["covered"])
        else "default"
    )
    return FightPredictionResponse(
        fighter_a_id=prediction.fighter_a_id,
        fighter_b_id=prediction.fighter_b_id,
        fighter_a_win_probability=prediction.probability_a,
        fighter_b_win_probability=prediction.probability_b,
        predicted_winner_id=prediction.predicted_winner_id,
        confidence_tier=tier,
        operating_points={
            name: ConfidenceStatus(margin=float(value["margin"]), covered=bool(value["covered"]))
            for name, value in points.items()
        },
        model_version=str(runtime.bundle["model"]["model_schema_version"]),
        feature_schema_version=str(runtime.bundle["feature_contract"]["feature_schema_version"]),
        bundle_hash=runtime.bundle_hash,
        prediction_timestamp=datetime.now(UTC),
        limitations=list(runtime.bundle["limitations"]),
        insufficient_history_indicators=list(prediction.insufficient_history_indicators),
        feature_source=prediction.feature_source,
        history_cutoff_date=prediction.history_cutoff_date,
        fighter_history_counts=prediction.fighter_history_counts,
    )
