"""Pydantic schemas for the prediction domain.

Covers canonical prediction requests, calibrated win probabilities,
method/round distributions, confidence scores, and feature snapshots
per the UFC Predictor API Specification.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ConfidenceStatus(BaseModel):
    """Operating point margin and coverage indicator."""

    margin: float
    covered: bool


class MethodProbabilities(BaseModel):
    """Predicted win-method probability distribution."""

    decision: float = Field(ge=0.0, le=1.0)
    ko_tko: float = Field(ge=0.0, le=1.0)
    submission: float = Field(ge=0.0, le=1.0)


class RoundDistribution(BaseModel):
    """Predicted round-by-round finish probabilities."""

    round_1: float = Field(ge=0.0, le=1.0)
    round_2: float = Field(ge=0.0, le=1.0)
    round_3: float = Field(ge=0.0, le=1.0)
    round_4: float | None = Field(default=None, ge=0.0, le=1.0)
    round_5: float | None = Field(default=None, ge=0.0, le=1.0)


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


class FightPredictionResponse(BaseModel):
    """Lightweight champion scoring response for strict-date materialization."""

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


class MatchupPredictionRequest(BaseModel):
    """Comprehensive matchup prediction request with mode and parameters."""

    fighter_a_id: str = Field(min_length=1, max_length=128)
    fighter_b_id: str = Field(min_length=1, max_length=128)
    target_fight_date: date = Field(default_factory=date.today)
    scheduled_rounds: int = Field(default=3, ge=3, le=5)
    mode: Literal["pure"] = Field(default="pure", description="Accepted pure winner model")
    model_version: str | None = Field(
        default=None, description="Target model version (analyst role required for non-champion)"
    )
    persist: bool = Field(default=False, description="Durable snapshots are not yet supported")
    explanation: str = Field(
        default="none", description="Explanation mode: 'none', 'cached', or 'async'"
    )

    @model_validator(mode="after")
    def distinct_fighters(self) -> MatchupPredictionRequest:
        if self.fighter_a_id == self.fighter_b_id:
            raise ValueError("fighter_a_id and fighter_b_id must differ")
        return self


class MatchupPredictionResponse(BaseModel):
    """Rich matchup prediction including finish methods and round distributions."""

    prediction_id: str | None = None
    fighter_a_id: str
    fighter_b_id: str
    fighter_a_win_probability: float
    fighter_b_win_probability: float
    predicted_winner_id: str | None
    confidence_tier: str
    mode: str
    method_probabilities: MethodProbabilities | None = None
    round_distribution: RoundDistribution | None = None
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


class Prediction(BaseModel):
    """Full canonical Prediction domain model per the API specification."""

    prediction_id: str
    fight_id: str | None = None
    mode: str = "pure"
    status: str = "published"
    prediction_timestamp: datetime
    prediction_as_of: datetime
    target_fight_timestamp: datetime | None = None
    horizon_seconds: int | None = None
    fighter_a_id: str
    fighter_b_id: str
    fighter_a_win_probability: float
    fighter_b_win_probability: float
    predicted_winner_id: str | None = None
    confidence_tier: str = "default"
    confidence_score: float = 0.5
    operating_points: dict[str, ConfidenceStatus] = {}
    method_probabilities: MethodProbabilities | None = None
    round_distribution: RoundDistribution | None = None
    model_version: str
    model_bundle_version: str | None = None
    calibration_version: str | None = None
    dataset_version: str | None = None
    feature_set_version: str | None = None
    feature_snapshot_hash: str | None = None
    bundle_hash: str
    market_metadata: dict[str, Any] | None = None
    explanation_id: str | None = None
    explanation_status: str = "none"
    limitations: list[str] = []
    warnings: list[str] = []
    insufficient_history_indicators: list[str] = []
    feature_source: str = "materialized"
    history_cutoff_date: str | None = None
    fighter_history_counts: dict[str, int] = {}


class PredictionPage(BaseModel):
    """Keyset-paginated list of predictions."""

    items: list[Prediction]
    next_cursor: str | None = None
    has_more: bool = False


class PredictionSet(BaseModel):
    """Compact prediction set comparing pure and market predictions for a fight."""

    fight_id: str
    pure_prediction: Prediction | None = None
    market_prediction: Prediction | None = None


class FeatureSnapshot(BaseModel):
    """Feature snapshot record for reproducibility audit."""

    feature_snapshot_id: str
    target_fight_id: str | None = None
    fighter_a_id: str
    fighter_b_id: str
    prediction_as_of: datetime
    target_fight_timestamp: datetime | None = None
    orientation: str = "canonical"
    dataset_version: str
    feature_set_version: str
    pipeline_version: str
    latest_source_timestamp: datetime | None = None
    generated_at: datetime
    values: dict[str, Any] = {}
    input_completeness: dict[str, float] = {}
    content_hash: str
    status: str = "published"
