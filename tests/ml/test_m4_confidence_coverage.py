from __future__ import annotations

import pandas as pd

from ufc_predictor.training.m4_confidence_coverage import (
    CONFIDENCE_MARGINS,
    _margin_report,
    _symmetry_audit,
    select_operating_points,
)


def test_coverage_rule_and_symmetry_are_order_invariant() -> None:
    frame = pd.DataFrame(
        {
            "fight_date": pd.to_datetime(["2020-01-01"] * 4),
            "target_fighter_a_won": [0, 0, 1, 1],
            "symmetric_probability": [0.30, 0.48, 0.52, 0.75],
        }
    )
    report, covered = _margin_report(frame, 0.05)
    assert covered.tolist() == [True, False, False, True]
    assert report["covered_rows"] == 2
    audit = _symmetry_audit(frame, 0.05)
    assert audit["coverage_decision_violations"] == 0
    assert audit["winner_complement_violations_non_ties"] == 0


def test_operating_points_use_deterministic_coverage_tie_breaking() -> None:
    aggregates = {
        0.0: {"coverage": 1.0, "fold_accuracy_mean": 0.60},
        0.025: {"coverage": 0.80, "fold_accuracy_mean": 0.70},
        0.05: {"coverage": 0.80, "fold_accuracy_mean": 0.70},
        0.10: {"coverage": 0.40, "fold_accuracy_mean": 0.80},
    }
    selected = select_operating_points(aggregates)
    assert selected["full_coverage"] == 0.0
    assert selected["highest_accuracy_at_least_75pct_coverage"] == 0.025
    assert selected["highest_accuracy_at_least_50pct_coverage"] == 0.025
    assert selected["highest_accuracy_at_least_25pct_coverage"] == 0.10
    assert tuple(round(value * 0.025, 3) for value in range(9)) == CONFIDENCE_MARGINS
