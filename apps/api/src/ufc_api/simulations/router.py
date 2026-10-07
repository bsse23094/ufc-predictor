"""API Router for Matchup Counterfactual and Monte Carlo simulations."""

from __future__ import annotations

from datetime import date
from typing import cast

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, model_validator

from ufc_api.core.errors import DomainError, ErrorDetail
from ufc_api.data.parquet_catalog import resolve_canonical_fighter_id
from ufc_predictor.inference.m5_champion import ChampionRuntime
from ufc_predictor.simulation.engine import SimulationEngine

router = APIRouter(prefix="/api/v1/simulations", tags=["simulations"])


class CounterfactualRequest(BaseModel):
    fighter_a_id: str = Field(min_length=1)
    fighter_b_id: str = Field(min_length=1)
    target_fight_date: date = Field(default_factory=date.today)
    adjustments: dict[str, float] = Field(
        default_factory=dict,
        description="Feature adjustments e.g. reach_advantage_cms, age_difference_years",
    )

    @model_validator(mode="after")
    def distinct_fighters(self) -> CounterfactualRequest:
        if self.fighter_a_id == self.fighter_b_id:
            raise ValueError("fighter_a_id and fighter_b_id must differ")
        return self


class CounterfactualResponse(BaseModel):
    fighter_a_id: str
    fighter_b_id: str
    base_probability_a: float
    base_probability_b: float
    counterfactual_probability_a: float
    counterfactual_probability_b: float
    probability_delta_a: float
    adjustments_applied: dict[str, float]
    plausibility_warnings: list[str]
    synthetic_label: str


class MonteCarloRequest(BaseModel):
    fighter_a_id: str = Field(min_length=1)
    fighter_b_id: str = Field(min_length=1)
    target_fight_date: date = Field(default_factory=date.today)
    iterations: int = Field(default=10000, ge=100, le=50000)
    seed: int = Field(default=42)
    scheduled_rounds: int = Field(default=3, ge=3, le=5)

    @model_validator(mode="after")
    def distinct_fighters(self) -> MonteCarloRequest:
        if self.fighter_a_id == self.fighter_b_id:
            raise ValueError("fighter_a_id and fighter_b_id must differ")
        return self


class MonteCarloResponse(BaseModel):
    fighter_a_id: str
    fighter_b_id: str
    iterations: int
    seed: int
    simulated_win_rate_a: float
    simulated_win_rate_b: float
    method_distribution: dict[str, float]
    round_distribution: dict[str, float]
    average_duration_seconds: float
    duration_quantiles: dict[str, float]
    assumptions: str = (
        "Winner draws use the accepted champion probability. Method and duration draws "
        "use illustrative fixed priors and are not evaluated predictive estimates."
    )


def _runtime(request: Request) -> ChampionRuntime:
    runtime = getattr(request.app.state, "champion_runtime", None)
    if runtime is None:
        raise DomainError(
            code="model_runtime_unavailable",
            message="Model runtime is not loaded.",
            status_code=503,
        )
    return cast(ChampionRuntime, runtime)


@router.post(
    "/counterfactual",
    response_model=CounterfactualResponse,
    summary="Simulate counterfactual adjustments",
)
async def run_counterfactual_simulation(
    payload: CounterfactualRequest, request: Request
) -> CounterfactualResponse:
    """Evaluate what-if modifications to fighter attributes without modifying canonical data."""
    runtime = _runtime(request)
    engine = SimulationEngine(runtime)
    target_a = resolve_canonical_fighter_id(payload.fighter_a_id)
    target_b = resolve_canonical_fighter_id(payload.fighter_b_id)
    try:
        res = engine.run_counterfactual(
            target_a,
            target_b,
            payload.target_fight_date,
            payload.adjustments,
        )
    except Exception as exc:
        raise DomainError(
            code="simulation_failed",
            message=f"Counterfactual simulation could not be evaluated: {exc}",
            status_code=422,
            details=[ErrorDetail(field="adjustments", reason=str(exc))],
        ) from exc

    return CounterfactualResponse(
        fighter_a_id=res.fighter_a_id,
        fighter_b_id=res.fighter_b_id,
        base_probability_a=res.base_probability_a,
        base_probability_b=res.base_probability_b,
        counterfactual_probability_a=res.counterfactual_probability_a,
        counterfactual_probability_b=res.counterfactual_probability_b,
        probability_delta_a=res.probability_delta_a,
        adjustments_applied=res.adjustments_applied,
        plausibility_warnings=res.plausibility_warnings,
        synthetic_label=res.synthetic_label,
    )


@router.post(
    "/monte-carlo",
    response_model=MonteCarloResponse,
    summary="Run Monte Carlo bout distribution simulation",
)
async def run_monte_carlo_simulation(
    payload: MonteCarloRequest, request: Request
) -> MonteCarloResponse:
    """Run stochastic bout simulations for method and round completion distributions."""
    runtime = _runtime(request)
    engine = SimulationEngine(runtime)
    target_a = resolve_canonical_fighter_id(payload.fighter_a_id)
    target_b = resolve_canonical_fighter_id(payload.fighter_b_id)
    try:
        res = engine.run_monte_carlo(
            target_a,
            target_b,
            payload.target_fight_date,
            iterations=payload.iterations,
            seed=payload.seed,
            scheduled_rounds=payload.scheduled_rounds,
        )
    except Exception as exc:
        raise DomainError(
            code="simulation_failed",
            message=f"Monte Carlo simulation could not be evaluated: {exc}",
            status_code=422,
            details=[ErrorDetail(field="iterations", reason=str(exc))],
        ) from exc

    return MonteCarloResponse(
        fighter_a_id=res.fighter_a_id,
        fighter_b_id=res.fighter_b_id,
        iterations=res.iterations,
        seed=res.seed,
        simulated_win_rate_a=res.simulated_win_rate_a,
        simulated_win_rate_b=res.simulated_win_rate_b,
        method_distribution=res.method_distribution,
        round_distribution=res.round_distribution,
        average_duration_seconds=res.average_duration_seconds,
        duration_quantiles=res.duration_quantiles,
    )
