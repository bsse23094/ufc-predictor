"""Local model factors reconcile with the symmetric winner estimate."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ufc_predictor.explain.attribution import AttributionEngine
from ufc_predictor.inference.m5_champion import ChampionRuntime


def test_model_factor_allocation_reconciles_with_prediction() -> None:
    bundle = Path(
        "data/processed/m4-final-champion/m3-74eeb9b7f49b5adca45e461a/m4_final_champion_bundle.json"
    )
    if not bundle.is_file():
        pytest.skip("accepted local model bundle unavailable")
    runtime = ChampionRuntime(bundle)
    a = "80909aa2-735a-5df9-b562-9492ebb4abd1"
    b = "d513febc-9943-592f-b220-05c3ae615169"
    target = date(2024, 11, 16)
    prediction = runtime.predict(a, b, target)
    explanation = AttributionEngine(runtime).explain_prediction(a, b, target)
    reconstructed = explanation.model_baseline_probability_a + sum(
        factor.impact_probability_points / 100 for factor in explanation.model_factors
    )
    assert reconstructed == pytest.approx(prediction.probability_a, abs=0.001)
    assert any(abs(factor.impact_probability_points) > 0.1 for factor in explanation.model_factors)
    assert explanation.algorithm == "symmetric_xgboost_margin_allocation_v1"
