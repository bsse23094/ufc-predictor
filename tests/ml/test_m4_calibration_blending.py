from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression

from ufc_predictor.training.m4_calibration_blending import (
    BLEND_WEIGHTS,
    Candidate,
    _candidate_probability,
    _symmetric_calibrated,
    select_phase4a_candidate,
)


def test_calibration_and_blending_preserve_symmetry() -> None:
    calibrator = LogisticRegression(random_state=20260719).fit(
        np.asarray([[0.2], [0.3], [0.6], [0.8]]), np.asarray([0, 0, 1, 1])
    )
    probabilities = np.asarray([0.22, 0.41, 0.63, 0.79])
    calibrated = _symmetric_calibrated(calibrator, probabilities)
    reverse = _symmetric_calibrated(calibrator, 1.0 - probabilities)
    assert np.allclose(calibrated + reverse, 1.0)
    blend = _candidate_probability(
        Candidate("blend", "fixed_grid_blend", None, 0.4, 2), calibrated, 1.0 - calibrated
    )
    assert np.allclose(blend + (1.0 - blend), 1.0)


def test_grid_and_selection_are_fixed_and_lexicographic() -> None:
    assert tuple(round(value / 10, 1) for value in range(11)) == BLEND_WEIGHTS
    candidates = (
        Candidate("more_complex", "calibrated_xgboost", "platt", None, 2),
        Candidate("simpler", "uncalibrated_xgboost", None, None, 1),
    )
    common = {
        "mean_log_loss": 0.66,
        "mean_brier_score": 0.23,
        "mean_ece": 0.02,
        "mean_roc_auc": 0.63,
        "std_log_loss": 0.01,
        "worst_fold_log_loss": 0.68,
        "selection_eligible": True,
    }
    aggregates = {
        candidate.candidate_id: {**common, "mean_symmetric_complement_error": 0.0}
        for candidate in candidates
    }
    aggregates["more_complex"]["selection_eligible"] = False
    assert select_phase4a_candidate(aggregates, candidates) == "simpler"
