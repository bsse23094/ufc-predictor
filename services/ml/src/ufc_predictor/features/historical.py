"""Strictly prior-bout, orientation-safe historical feature construction."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ufc_predictor.features.model_ready import assert_pre_fight_feature_schema


@dataclass(frozen=True, slots=True)
class HistoricalFight:
    event_time: datetime
    red_fighter_id: UUID
    blue_fighter_id: UUID
    red_outcome: str
    blue_outcome: str
    red_statistics: dict[str, float]
    blue_statistics: dict[str, float]


def pre_fight_features(
    *,
    target_time: datetime,
    red_fighter_id: UUID,
    blue_fighter_id: UUID,
    history: tuple[HistoricalFight, ...],
) -> dict[str, float]:
    """Aggregate only fights strictly earlier than ``target_time`` and emit R-B deltas."""

    if target_time.tzinfo is None:
        raise ValueError("target_time must be timezone-aware")
    prior = tuple(fight for fight in history if fight.event_time < target_time)
    red = _fighter_features(red_fighter_id, prior, target_time)
    blue = _fighter_features(blue_fighter_id, prior, target_time)
    output = {f"red_{name}": value for name, value in red.items()}
    output.update({f"blue_{name}": value for name, value in blue.items()})
    output.update({f"difference_{name}": red[name] - blue[name] for name in red})
    assert_pre_fight_feature_schema(output)
    return output


def _fighter_features(
    fighter_id: UUID, history: tuple[HistoricalFight, ...], target_time: datetime
) -> dict[str, float]:
    fights = []
    for fight in history:
        if fight.red_fighter_id == fighter_id:
            fights.append((fight.event_time, fight.red_outcome, fight.red_statistics))
        elif fight.blue_fighter_id == fighter_id:
            fights.append((fight.event_time, fight.blue_outcome, fight.blue_statistics))
    fights.sort(key=lambda item: item[0])
    results = [result for _, result, _ in fights]
    output: dict[str, float] = {
        "prior_ufc_bouts": float(len(fights)),
        "prior_wins": float(results.count("win")),
        "prior_losses": float(results.count("loss")),
        "prior_draws": float(results.count("draw")),
        "prior_no_contests": float(results.count("nc")),
        "win_rate": results.count("win") / len(results) if results else 0.0,
        "streak": float(_streak(results)),
        "layoff_days": (target_time - fights[-1][0]).total_seconds() / 86400 if fights else -1.0,
    }
    metric_values: defaultdict[str, list[float]] = defaultdict(list)
    for _, _, statistics in fights:
        for metric, value in statistics.items():
            metric_values[metric].append(value)
    for metric, values in metric_values.items():
        career = sum(values) / len(values)
        output[f"career_{metric}"] = career
        for window in (1, 3, 5):
            recent = values[-window:]
            output[f"rolling_{window}_{metric}"] = sum(recent) / len(recent)
        output[f"trend_3_vs_career_{metric}"] = output[f"rolling_3_{metric}"] - career
    return output


def _streak(results: list[str]) -> int:
    if not results:
        return 0
    sign = 1 if results[-1] == "win" else -1 if results[-1] == "loss" else 0
    return sign * sum(1 for result in reversed(results) if result == results[-1])
