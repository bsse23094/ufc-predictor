"""Public API contract for M5 champion inference with caching, idempotency, and persistence."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Header, Query, Request, Response

from ufc_api.core.errors import DomainError, ErrorDetail
from ufc_api.data.parquet_catalog import resolve_canonical_fighter_id
from ufc_api.predictions.repository import PredictionRepository
from ufc_api.predictions.schemas import (
    ConfidenceStatus,
    FightPredictionRequest,
    FightPredictionResponse,
    MatchupPredictionRequest,
    MatchupPredictionResponse,
    Prediction,
    PredictionPage,
)
from ufc_predictor.inference.m5_champion import (
    ChampionRuntime,
    FeatureMaterializationUnavailable,
)

router = APIRouter(prefix="/api/v1/predictions", tags=["predictions"])

# Local in-memory cache for idempotency & predictions when Redis is unavailable
_memory_cache: dict[str, tuple[str, float]] = {}  # key -> (json_str, expire_timestamp)


def _runtime(request: Request) -> ChampionRuntime:
    return cast(ChampionRuntime, request.app.state.champion_runtime)


def _get_repo(request: Request) -> PredictionRepository:
    session_factory = getattr(request.app.state, "session_factory", None)
    session = session_factory() if session_factory else None
    return PredictionRepository(session=session)


def _limitations(runtime: ChampionRuntime, target_date: date) -> list[str]:
    limitations = list(runtime.bundle["limitations"])
    training_cutoff = date.fromisoformat(str(runtime.bundle["training_date_cutoff"]))
    if (target_date - training_cutoff).days > 365:
        limitations.append(
            f"The accepted training/history cutoff is {training_cutoff}; "
            "this matchup is more than one year later and source freshness may limit reliability."
        )
    return limitations


async def _cache_get(request: Request, key: str) -> str | None:
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is not None:
        try:
            val = await redis_client.get(key)
            return cast(str | None, val)
        except Exception:
            pass
    if key in _memory_cache:
        val, exp = _memory_cache[key]
        if datetime.now(UTC).timestamp() < exp:
            return val
        del _memory_cache[key]
    return None


async def _cache_set(request: Request, key: str, value: str, ttl_seconds: int = 1800) -> None:
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is not None:
        try:
            await redis_client.set(key, value, ex=ttl_seconds)
            return
        except Exception:
            pass
    exp = datetime.now(UTC).timestamp() + ttl_seconds
    _memory_cache[key] = (value, exp)


@router.post(
    "/fight",
    response_model=FightPredictionResponse,
    responses={422: {"description": "Invalid request or unavailable pre-fight materialization"}},
)
async def predict_fight(
    payload: FightPredictionRequest, request: Request
) -> FightPredictionResponse:
    """Score only an accepted, strict-date pre-fight feature materialization."""

    target_a = resolve_canonical_fighter_id(payload.fighter_a_id)
    target_b = resolve_canonical_fighter_id(payload.fighter_b_id)

    try:
        prediction = _runtime(request).predict(target_a, target_b, payload.target_fight_date)
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
        limitations=_limitations(runtime, payload.target_fight_date),
        insufficient_history_indicators=list(prediction.insufficient_history_indicators),
        feature_source=prediction.feature_source,
        history_cutoff_date=prediction.history_cutoff_date,
        fighter_history_counts=prediction.fighter_history_counts,
    )


@router.post(
    "/matchup",
    response_model=MatchupPredictionResponse,
    summary="Compute comprehensive matchup prediction with method and round expectations",
)
async def predict_matchup(
    payload: MatchupPredictionRequest,
    request: Request,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MatchupPredictionResponse:
    """Evaluate full matchup prediction including finish method and round projections."""
    if payload.persist:
        raise DomainError(
            code="prediction_snapshot_unavailable",
            message="Durable prediction snapshots are not configured.",
            status_code=501,
        )
    if payload.model_version not in (None, "champion"):
        raise DomainError(
            code="model_version_unavailable",
            message="Only the accepted champion winner model is available.",
            status_code=422,
        )

    # Canonical request hash includes every option that changes the response.
    target_a = resolve_canonical_fighter_id(payload.fighter_a_id)
    target_b = resolve_canonical_fighter_id(payload.fighter_b_id)
    target_version = _runtime(request).bundle_hash
    cache_payload = (
        f"{target_a}:{target_b}:{payload.target_fight_date}:"
        f"{payload.scheduled_rounds}:{payload.mode}:{target_version}:{payload.explanation}"
    )
    req_hash = hashlib.sha256(cache_payload.encode()).hexdigest()
    cache_key = f"pred_matchup:{req_hash}"

    if idempotency_key:
        idem_key = f"idempotency:{idempotency_key}"
        owner_hash = await _cache_get(request, idem_key)
        if owner_hash and owner_hash != req_hash:
            raise DomainError(
                code="idempotency_key_conflict",
                message="Idempotency-Key was already used for a different request.",
                status_code=409,
            )
        if owner_hash:
            cached_idem = await _cache_get(request, cache_key)
            if cached_idem:
                response.headers["X-Cache"] = "HIT-IDEMPOTENT"
                return MatchupPredictionResponse.model_validate_json(cached_idem)

    cached_pred = await _cache_get(request, cache_key)
    if cached_pred:
        response.headers["X-Cache"] = "HIT"
        result = MatchupPredictionResponse.model_validate_json(cached_pred)
        if idempotency_key:
            await _cache_set(request, idem_key, req_hash, ttl_seconds=1800)
        return result

    response.headers["X-Cache"] = "MISS"

    runtime = _runtime(request)
    try:
        prediction = runtime.predict(target_a, target_b, payload.target_fight_date)
    except FeatureMaterializationUnavailable as exc:
        raise DomainError(
            code="prediction_materialization_unavailable",
            message="Prediction-safe pre-fight history is unavailable for this request.",
            status_code=422,
            details=[ErrorDetail(field="target_fight_date", reason=str(exc))],
        ) from exc

    points = prediction.confidence
    tier = (
        "high"
        if bool(points["high_confidence"]["covered"])
        else "medium"
        if bool(points["medium_confidence"]["covered"])
        else "default"
    )

    now = datetime.now(UTC)
    pred_id = str(uuid4())

    resp = MatchupPredictionResponse(
        prediction_id=pred_id,
        fighter_a_id=prediction.fighter_a_id,
        fighter_b_id=prediction.fighter_b_id,
        fighter_a_win_probability=prediction.probability_a,
        fighter_b_win_probability=prediction.probability_b,
        predicted_winner_id=prediction.predicted_winner_id,
        confidence_tier=tier,
        mode=payload.mode,
        method_probabilities=None,
        round_distribution=None,
        operating_points={
            name: ConfidenceStatus(margin=float(value["margin"]), covered=bool(value["covered"]))
            for name, value in points.items()
        },
        model_version=str(runtime.bundle["model"]["model_schema_version"]),
        feature_schema_version=str(runtime.bundle["feature_contract"]["feature_schema_version"]),
        bundle_hash=runtime.bundle_hash,
        prediction_timestamp=now,
        limitations=[
            *_limitations(runtime, payload.target_fight_date),
            "Method, round, and duration distributions have no accepted model and are unavailable.",
        ],
        insufficient_history_indicators=list(prediction.insufficient_history_indicators),
        feature_source=prediction.feature_source,
        history_cutoff_date=prediction.history_cutoff_date,
        fighter_history_counts=prediction.fighter_history_counts,
    )

    json_str = resp.model_dump_json()
    await _cache_set(request, cache_key, json_str, ttl_seconds=1800)
    if idempotency_key:
        await _cache_set(request, idem_key, req_hash, ttl_seconds=1800)

    return resp


@router.get(
    "/fights/{fight_id}",
    response_model=PredictionPage,
    summary="Get stored prediction snapshots for a fight",
)
async def get_fight_predictions(
    fight_id: str,
    request: Request,
    mode: Annotated[str | None, Query()] = None,
    model_version: Annotated[str | None, Query()] = None,
) -> PredictionPage:
    """Retrieve historical/stored prediction snapshots for a fight."""
    repo = _get_repo(request)
    predictions = await repo.list_predictions_for_fight(
        fight_id, mode=mode, model_version=model_version
    )
    return PredictionPage(items=predictions, next_cursor=None, has_more=False)


@router.get(
    "/{prediction_id}",
    response_model=Prediction,
    summary="Get prediction by ID",
)
async def get_prediction_by_id(prediction_id: str, request: Request) -> Prediction:
    """Retrieve a stored prediction snapshot by UUID."""
    repo = _get_repo(request)
    pred = await repo.get_prediction(prediction_id)
    if pred is None:
        raise DomainError(
            code="prediction_not_found",
            message=f"Prediction {prediction_id} was not found.",
            status_code=404,
        )
    return pred
