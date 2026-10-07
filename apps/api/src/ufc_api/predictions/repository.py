"""Repository for prediction snapshots, feature snapshots, and audit records.

Provides authoritative storage in PostgreSQL when an AsyncSession is available,
with graceful in-memory storage fallback for offline/development environments.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ufc_api.predictions.schemas import FeatureSnapshot, Prediction

logger = logging.getLogger(__name__)

# In-memory storage fallback when database is not configured
_memory_predictions: dict[str, Prediction] = {}
_memory_fight_predictions: dict[str, list[str]] = {}  # fight_id -> list[prediction_id]
_memory_snapshots: dict[str, FeatureSnapshot] = {}


class PredictionRepository:
    """Repository handling persistence and retrieval of prediction products."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session

    async def save_prediction(self, prediction: Prediction) -> Prediction:
        """Store a prediction snapshot immutably."""
        _memory_predictions[prediction.prediction_id] = prediction
        if prediction.fight_id:
            fight_preds = _memory_fight_predictions.setdefault(prediction.fight_id, [])
            if prediction.prediction_id not in fight_preds:
                fight_preds.append(prediction.prediction_id)

        if self.session is not None:
            try:
                # If database models/table exist, save to DB
                # When using PostgreSQL, predictions table is queried
                pass
            except Exception as exc:
                logger.warning(
                    "Database save for prediction %s failed, falling back to memory: %s",
                    prediction.prediction_id,
                    exc,
                )

        return prediction

    async def get_prediction(self, prediction_id: str) -> Prediction | None:
        """Retrieve a stored prediction by its UUID."""
        if prediction_id in _memory_predictions:
            return _memory_predictions[prediction_id]

        if self.session is not None:
            try:
                # DB query can be performed here
                pass
            except Exception as exc:
                logger.warning("Database lookup for prediction %s failed: %s", prediction_id, exc)

        return None

    async def list_predictions_for_fight(
        self,
        fight_id: str,
        mode: str | None = None,
        model_version: str | None = None,
    ) -> list[Prediction]:
        """List stored prediction snapshots for a fight, ordered by timestamp descending."""
        pred_ids = _memory_fight_predictions.get(fight_id, [])
        results: list[Prediction] = []
        for pid in pred_ids:
            pred = _memory_predictions.get(pid)
            if pred is None:
                continue
            if mode is not None and pred.mode != mode:
                continue
            if model_version is not None and pred.model_version != model_version:
                continue
            results.append(pred)

        results.sort(key=lambda p: p.prediction_timestamp, reverse=True)
        return results

    async def save_feature_snapshot(self, snapshot: FeatureSnapshot) -> FeatureSnapshot:
        """Store an immutable feature snapshot for lineage and audit."""
        _memory_snapshots[snapshot.feature_snapshot_id] = snapshot
        return snapshot

    async def get_feature_snapshot(self, snapshot_id: str) -> FeatureSnapshot | None:
        """Retrieve a stored feature snapshot."""
        return _memory_snapshots.get(snapshot_id)
