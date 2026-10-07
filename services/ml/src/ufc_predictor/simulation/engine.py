"""Matchup simulation engine for counterfactual analysis and Monte Carlo distributions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from ufc_predictor.inference.m5_champion import ChampionRuntime


@dataclass(frozen=True, slots=True)
class CounterfactualAdjustment:
    feature_name: str
    delta_value: float


@dataclass(frozen=True, slots=True)
class CounterfactualResult:
    fighter_a_id: str
    fighter_b_id: str
    base_probability_a: float
    base_probability_b: float
    counterfactual_probability_a: float
    counterfactual_probability_b: float
    probability_delta_a: float
    adjustments_applied: dict[str, float]
    plausibility_warnings: list[str]
    synthetic_label: str = "SYNTHETIC_COUNTERFACTUAL_ESTIMATE"


@dataclass(frozen=True, slots=True)
class MonteCarloSimulationResult:
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


ALLOWED_COUNTERFACTUAL_BOUNDS: dict[str, tuple[float, float]] = {
    "reach_advantage_cms": (-25.0, 25.0),
    "height_advantage_cms": (-25.0, 25.0),
    "age_difference_years": (-15.0, 15.0),
    "takedown_defense_pct": (-0.40, 0.40),
    "striking_pace_multiplier": (0.50, 2.00),
    "recent_win_streak_adjustment": (-5.0, 5.0),
    "elo_rating_shift": (-300.0, 300.0),
}


class SimulationEngine:
    """Engine executing what-if counterfactual adjustments and Monte Carlo fight simulations."""

    def __init__(self, runtime: ChampionRuntime) -> None:
        self.runtime = runtime

    def run_counterfactual(
        self,
        fighter_a_id: str,
        fighter_b_id: str,
        target_date: date,
        adjustments: dict[str, float],
    ) -> CounterfactualResult:
        base_pred = self.runtime.predict(fighter_a_id, fighter_b_id, target_date)
        base_prob_a = base_pred.probability_a
        base_prob_b = base_pred.probability_b

        applied: dict[str, float] = {}
        warnings: list[str] = [
            "Sensitivity weights are illustrative assumptions, not fitted counterfactual effects."
        ]

        # Calculate estimated impact of each adjustment using sensitivity approximation
        # around the margin of the sigmoid.
        logit_delta = 0.0

        for key, value in adjustments.items():
            if key not in ALLOWED_COUNTERFACTUAL_BOUNDS:
                warnings.append(
                    f"Feature '{key}' is not an authorized counterfactual control; ignored."
                )
                continue

            lower, upper = ALLOWED_COUNTERFACTUAL_BOUNDS[key]
            clamped = float(np.clip(value, lower, upper))
            if clamped != value:
                warnings.append(
                    f"Value for '{key}' ({value}) exceeded plausibility bounds "
                    f"[{lower}, {upper}]; clamped to {clamped}."
                )

            applied[key] = clamped

            # Illustrative sensitivity weights; these are not fitted causal effects.
            if key == "reach_advantage_cms":
                logit_delta += clamped * 0.015
            elif key == "height_advantage_cms":
                logit_delta += clamped * 0.010
            elif key == "age_difference_years":
                # Being older relative to opponent generally has negative log-odds
                logit_delta += clamped * (-0.025)
            elif key == "takedown_defense_pct":
                logit_delta += clamped * 0.45
            elif key == "striking_pace_multiplier":
                logit_delta += (clamped - 1.0) * 0.30
            elif key == "recent_win_streak_adjustment":
                logit_delta += clamped * 0.08
            elif key == "elo_rating_shift":
                logit_delta += (clamped / 400.0) * np.log(10)

        # Convert base prob to log-odds, apply delta, convert back
        eps = 1e-6
        base_clamped = np.clip(base_prob_a, eps, 1.0 - eps)
        base_logit = np.log(base_clamped / (1.0 - base_clamped))
        new_logit = base_logit + logit_delta
        cf_prob_a = float(1.0 / (1.0 + np.exp(-new_logit)))
        cf_prob_a = float(np.clip(cf_prob_a, 0.01, 0.99))
        cf_prob_b = float(1.0 - cf_prob_a)

        return CounterfactualResult(
            fighter_a_id=fighter_a_id,
            fighter_b_id=fighter_b_id,
            base_probability_a=round(base_prob_a, 4),
            base_probability_b=round(base_prob_b, 4),
            counterfactual_probability_a=round(cf_prob_a, 4),
            counterfactual_probability_b=round(cf_prob_b, 4),
            probability_delta_a=round(cf_prob_a - base_prob_a, 4),
            adjustments_applied=applied,
            plausibility_warnings=warnings,
        )

    def run_monte_carlo(
        self,
        fighter_a_id: str,
        fighter_b_id: str,
        target_date: date,
        iterations: int = 10000,
        seed: int = 42,
        scheduled_rounds: int = 3,
    ) -> MonteCarloSimulationResult:
        """Run stochastic bout simulations to generate method and round distributions."""
        bounded_iterations = max(100, min(iterations, 50000))
        rng = np.random.default_rng(seed)

        pred = self.runtime.predict(fighter_a_id, fighter_b_id, target_date)
        p_a = pred.probability_a

        # Base UFC historical method distribution priors (adjusted by fighter win probabilities)
        # Decision: ~50%, KO/TKO: ~32%, Submission: ~18%
        decision_prob = 0.52 if scheduled_rounds == 3 else 0.44
        ko_prob = 0.30 if scheduled_rounds == 3 else 0.36
        sub_prob = 0.18 if scheduled_rounds == 3 else 0.20

        sim_winners = rng.binomial(1, p_a, size=bounded_iterations)
        wins_a = int(np.sum(sim_winners))
        wins_b = bounded_iterations - wins_a

        # Sample finish method
        methods = rng.choice(
            ["Decision - Unanimous", "Decision - Split", "KO/TKO", "Submission"],
            size=bounded_iterations,
            p=[decision_prob * 0.8, decision_prob * 0.2, ko_prob, sub_prob],
        )

        method_counts: dict[str, int] = {}
        for m in methods:
            method_counts[m] = method_counts.get(m, 0) + 1

        method_dist = {k: round(v / bounded_iterations, 4) for k, v in method_counts.items()}

        # Sample round distribution
        round_counts: dict[str, int] = {}
        durations: list[float] = []

        round_len = 300.0  # 5 minutes
        for i in range(bounded_iterations):
            m = methods[i]
            if "Decision" in m:
                r_num = scheduled_rounds
                dur = float(scheduled_rounds * round_len)
            else:
                # Finished before decision: sample round
                r_weights = (
                    [0.45, 0.35, 0.20] if scheduled_rounds == 3 else [0.35, 0.25, 0.20, 0.12, 0.08]
                )
                r_num = int(rng.choice(range(1, scheduled_rounds + 1), p=r_weights))
                # Random time within round
                time_in_round = float(rng.uniform(30.0, round_len))
                dur = float((r_num - 1) * round_len + time_in_round)

            r_key = f"Round {r_num}"
            round_counts[r_key] = round_counts.get(r_key, 0) + 1
            durations.append(dur)

        round_dist = {
            f"Round {r}": round(round_counts.get(f"Round {r}", 0) / bounded_iterations, 4)
            for r in range(1, scheduled_rounds + 1)
        }

        dur_arr = np.array(durations)
        quantiles = {
            "p10": round(float(np.percentile(dur_arr, 10)), 1),
            "p25": round(float(np.percentile(dur_arr, 25)), 1),
            "p50_median": round(float(np.median(dur_arr)), 1),
            "p75": round(float(np.percentile(dur_arr, 75)), 1),
            "p90": round(float(np.percentile(dur_arr, 90)), 1),
        }

        return MonteCarloSimulationResult(
            fighter_a_id=fighter_a_id,
            fighter_b_id=fighter_b_id,
            iterations=bounded_iterations,
            seed=seed,
            simulated_win_rate_a=round(wins_a / bounded_iterations, 4),
            simulated_win_rate_b=round(wins_b / bounded_iterations, 4),
            method_distribution=method_dist,
            round_distribution=round_dist,
            average_duration_seconds=round(float(np.mean(dur_arr)), 1),
            duration_quantiles=quantiles,
        )
