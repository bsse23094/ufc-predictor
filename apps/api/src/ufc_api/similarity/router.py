"""API Router for historical fight similarity."""

from __future__ import annotations

from datetime import date
from typing import Annotated, cast

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from ufc_api.core.errors import DomainError
from ufc_api.data.parquet_catalog import resolve_canonical_fighter_id
from ufc_predictor.inference.m5_champion import ChampionRuntime
from ufc_predictor.similarity.engine import SimilarityEngine

router = APIRouter(prefix="/api/v1/similarity", tags=["similarity"])


class SimilarMatchupResponse(BaseModel):
    canonical_bout_id: str
    fight_date: str
    fighter_a_name: str
    fighter_b_name: str
    winner_name: str | None
    finish_method: str | None
    finish_round: int | None
    similarity_score: float
    similarity_factors: list[str]
    important_differences: list[str] = []
    feature_coverage: float = 1.0


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
    "/matchups",
    response_model=list[SimilarMatchupResponse],
    summary="Find historically similar fights",
)
async def get_similar_matchups(
    request: Request,
    fighter_a_id: Annotated[str, Query(min_length=1)],
    fighter_b_id: Annotated[str, Query(min_length=1)],
    target_fight_date: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
) -> list[SimilarMatchupResponse]:
    """Return historical fights with closest stylistic and analytical similarity."""
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
    engine = SimilarityEngine(runtime)

    try:
        matches = engine.find_similar_matchups(
            fighter_a_id=resolved_a,
            fighter_b_id=resolved_b,
            target_date=resolved_date,
            k=limit,
        )
    except Exception:
        matches = []

    return [
        SimilarMatchupResponse(
            canonical_bout_id=m.canonical_bout_id,
            fight_date=m.fight_date,
            fighter_a_name=m.fighter_a_name,
            fighter_b_name=m.fighter_b_name,
            winner_name=m.winner_name,
            finish_method=m.finish_method,
            finish_round=m.finish_round,
            similarity_score=m.similarity_score,
            similarity_factors=m.similarity_factors,
        )
        for m in matches
    ]
