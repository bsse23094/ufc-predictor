"""Descriptive comparisons of actual pre-fight model features."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
import xgboost as xgb

from ufc_predictor.inference.m5_champion import ChampionRuntime


@dataclass(frozen=True, slots=True)
class FeatureContribution:
    factor_name: str
    category: str
    impact_score: float  # Normalized gap for display, not model attribution.
    direction: str
    description: str


@dataclass(frozen=True, slots=True)
class ModelFactor:
    factor_name: str
    impact_probability_points: float
    direction: str
    description: str


@dataclass(frozen=True, slots=True)
class PredictionExplanation:
    fighter_a_id: str
    fighter_b_id: str
    model_version: str
    top_factors: list[FeatureContribution]
    model_factors: list[ModelFactor]
    model_baseline_probability_a: float
    missing_data_caveats: list[str]
    baseline_cohort: str = "2020-2026_canonical_ufc_bouts"
    algorithm: str = "symmetric_xgboost_margin_allocation_v1"
    disclaimer: str = (
        "Model factors allocate XGBoost tree margin contributions into percentage-point "
        "changes for this symmetric estimate; correlated inputs and feature interactions "
        "make them associative, not causal. Feature-gap bars below are descriptive only."
    )


_FACTOR_SPECS = (
    ("Pre-fight Elo rating", "skill_rating", "diff_pre_fight_overall_elo", 150.0, "rating points"),
    ("Career win rate", "form_activity", "diff_prior_win_rate", 0.4, "win-rate points"),
    ("Recent five win rate", "form_activity", "diff_recent_five_win_rate", 0.4, "win-rate points"),
    (
        "Significant strikes per minute",
        "striking",
        "diff_career_significant_strikes_landed_per_minute",
        2.0,
        "strikes/min",
    ),
    (
        "Takedown attempts per 15 minutes",
        "grappling",
        "diff_career_takedown_attempts_per_15_minutes",
        3.0,
        "attempts/15 min",
    ),
)

_GROUP_DESCRIPTIONS = {
    "Opponent-adjusted strength": "Pre-fight Elo rating and rating-history features.",
    "Recent form and activity": "Recent win rate, streaks and time since the previous bout.",
    "Career record": "Historical results, bout count and finish history.",
    "Striking": "Recorded strike volume, accuracy and defensive features.",
    "Grappling": "Recorded takedown, submission and control features.",
    "Missing history": "Model flags for unavailable or limited prior history.",
    "Other model context": "Remaining accepted pre-fight model inputs.",
}


def _group(name: str) -> str:
    if name.endswith("_missing") or "cold_start" in name:
        return "Missing history"
    if "elo" in name:
        return "Opponent-adjusted strength"
    if any(term in name for term in ("significant_strike", "total_strike", "knockdown")):
        return "Striking"
    if any(term in name for term in ("takedown", "submission", "control_seconds")):
        return "Grappling"
    if any(term in name for term in ("recent", "streak", "days_since", "365_days")):
        return "Recent form and activity"
    if any(term in name for term in ("prior_", "finish_win", "eligible_")):
        return "Career record"
    return "Other model context"


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _probability_allocation(contributions: np.ndarray) -> tuple[float, np.ndarray]:
    """Allocate each margin SHAP value its proportional share of sigmoid movement."""
    baseline = float(contributions[-1])
    margins = contributions[:-1]
    margin_change = float(margins.sum())
    baseline_probability = _sigmoid(baseline)
    if abs(margin_change) < 1e-12:
        scale = baseline_probability * (1.0 - baseline_probability)
    else:
        scale = (_sigmoid(baseline + margin_change) - baseline_probability) / margin_change
    return baseline_probability, margins * scale


class AttributionEngine:
    """Read actual accepted feature values and display their directional differences."""

    def __init__(self, runtime: ChampionRuntime) -> None:
        self.runtime = runtime

    def explain_prediction(
        self, fighter_a_id: str, fighter_b_id: str, target_date: date
    ) -> PredictionExplanation:
        pred = self.runtime.predict(fighter_a_id, fighter_b_id, target_date)
        vector, _ = self.runtime._resolve_vector(fighter_a_id, fighter_b_id, target_date)
        factors: list[FeatureContribution] = []
        caveats = list(pred.insufficient_history_indicators[:4])
        for name, category, column, scale, unit in _FACTOR_SPECS:
            if column not in self.runtime.feature_columns:
                continue
            raw = vector.get(column)
            if raw is None or not math.isfinite(float(raw)):
                caveats.append(f"{name} is missing from the pre-fight snapshot.")
                continue
            value = float(raw)
            score = round(max(-1.0, min(1.0, value / scale)), 3)
            direction = (
                "favors_fighter_a"
                if score > 0.05
                else "favors_fighter_b"
                if score < -0.05
                else "neutral"
            )
            display_value = value * 100 if "win rate" in name.lower() else value
            display_unit = "percentage points" if "win rate" in name.lower() else unit
            factors.append(
                FeatureContribution(
                    factor_name=name,
                    category=category,
                    impact_score=score,
                    direction=direction,
                    description=(
                        f"Fighter A is {display_value:+.1f} {display_unit} relative to Fighter B."
                    ),
                )
            )
        factors.sort(key=lambda factor: abs(factor.impact_score), reverse=True)
        columns = self.runtime.feature_columns
        forward = pd.DataFrame([[vector[name] for name in columns]], columns=columns).astype(float)
        swapped_vector = self.runtime._swap_vector(vector)
        swapped = pd.DataFrame(
            [[swapped_vector[name] for name in columns]], columns=columns
        ).astype(float)
        booster = self.runtime.model.get_booster()
        forward_shap = booster.predict(xgb.DMatrix(forward), pred_contribs=True)[0]
        swapped_shap = booster.predict(xgb.DMatrix(swapped), pred_contribs=True)[0]
        forward_baseline, forward_parts = _probability_allocation(forward_shap)
        swapped_baseline, swapped_parts = _probability_allocation(swapped_shap)
        baseline = 0.5 * (forward_baseline + 1.0 - swapped_baseline)
        grouped: dict[str, float] = {}
        for name, effect in zip(columns, 0.5 * (forward_parts - swapped_parts), strict=True):
            category = _group(name)
            grouped[category] = grouped.get(category, 0.0) + float(effect)
        model_factors = [
            ModelFactor(
                factor_name=name,
                impact_probability_points=round(effect * 100, 2),
                direction=(
                    "favors_fighter_a"
                    if effect > 0
                    else "favors_fighter_b"
                    if effect < 0
                    else "neutral"
                ),
                description=_GROUP_DESCRIPTIONS[name],
            )
            for name, effect in grouped.items()
        ]
        model_factors.sort(key=lambda factor: abs(factor.impact_probability_points), reverse=True)
        if not caveats:
            caveats.append("No flagged missing-history indicators for this matchup.")
        return PredictionExplanation(
            fighter_a_id=fighter_a_id,
            fighter_b_id=fighter_b_id,
            model_version=str(self.runtime.bundle.get("champion_id", "m4_champion")),
            top_factors=factors,
            model_factors=model_factors,
            model_baseline_probability_a=round(baseline, 6),
            missing_data_caveats=caveats,
        )
