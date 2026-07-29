from __future__ import annotations

import joblib

from ufc_predictor.training.m4_final_champion import (
    PHASE3C_CHAMPION_ID,
    RECOMMENDED_OPERATING_POINTS,
    _feature_swap_registry,
)


def test_swap_registry_is_complete_and_recommended_points_are_fixed() -> None:
    registry = _feature_swap_registry(["a_x", "b_x", "diff_x"])
    assert registry == [
        {"feature": "a_x", "swap_feature": "b_x", "transform": "exchange"},
        {"feature": "b_x", "swap_feature": "a_x", "transform": "exchange"},
        {"feature": "diff_x", "swap_feature": "diff_x", "transform": "negate"},
    ]
    assert RECOMMENDED_OPERATING_POINTS == {
        "default_full_coverage": 0.0,
        "medium_confidence": 0.075,
        "high_confidence": 0.125,
    }
    assert PHASE3C_CHAMPION_ID.endswith("phase3a_shallow_xgboost")


def test_accepted_champion_model_loads() -> None:
    model = joblib.load(
        "data/processed/m4-phase3c-opponent-adjusted-performance/"
        "m3-74eeb9b7f49b5adca45e461a/m4_phase3c_selected_model.joblib"
    )
    assert hasattr(model, "predict_proba")
