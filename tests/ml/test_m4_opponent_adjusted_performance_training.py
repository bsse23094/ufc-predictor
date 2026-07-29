from __future__ import annotations

import numpy as np
import pandas as pd

from ufc_predictor.training.m4_opponent_adjusted_performance import (
    PERFORMANCE_METRICS,
    adjusted_feature_names,
    build_opponent_adjusted_snapshots,
    feature_packs,
)


def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Three dates; the middle bout has a known opponent baseline."""

    performances: list[dict[str, object]] = []
    histories: list[dict[str, object]] = []
    bouts = [
        ("one", "2020-01-01", "a", "b", 4, 2),
        ("two", "2020-02-01", "a", "c", 10, 2),
        ("three", "2020-03-01", "a", "d", 9, 3),
    ]
    for bout_id, fight_date, fighter, opponent, fighter_value, opponent_value in bouts:
        for current, other, value in (
            (fighter, opponent, fighter_value),
            (opponent, fighter, opponent_value),
        ):
            performance: dict[str, object] = {
                "canonical_bout_id": bout_id,
                "canonical_fighter_id": current,
                "opponent_canonical_fighter_id": other,
                "fight_date": fight_date,
            }
            performance.update({metric: value for metric in PERFORMANCE_METRICS})
            performance.update({f"{metric}_available": True for metric in PERFORMANCE_METRICS})
            performances.append(performance)
            history: dict[str, object] = {
                "canonical_bout_id": bout_id,
                "canonical_fighter_id": current,
                "target_fight_date": fight_date,
            }
            for metric in PERFORMANCE_METRICS:
                # Only c's baseline at bout two is reliable: it allows 5 and
                # lands 2, therefore a's 8 differential adjusts to 5.
                history[f"career_{metric}_mean"] = 2.0 if current == "c" else np.nan
                history[f"career_{metric}_absorbed_per_observed_bout"] = (
                    5.0 if current == "c" else np.nan
                )
            histories.append(history)
    return pd.DataFrame(performances), pd.DataFrame(histories)


def test_strict_prior_snapshots_capture_historical_opponent_baseline() -> None:
    performance, history = _frames()
    snapshots = build_opponent_adjusted_snapshots(performance, history)
    middle = snapshots.query("canonical_bout_id == 'two' and canonical_fighter_id == 'a'").iloc[0]
    later = snapshots.query("canonical_bout_id == 'three' and canonical_fighter_id == 'a'").iloc[0]
    for metric in PERFORMANCE_METRICS:
        assert middle[f"opponent_adjusted_{metric}_observation_count"] == 0
        assert np.isnan(middle[f"opponent_adjusted_{metric}_career_mean"])
        assert later[f"opponent_adjusted_{metric}_observation_count"] == 1
        assert later[f"opponent_adjusted_{metric}_career_mean"] == 5


def test_same_date_isolation_row_order_and_null_policy() -> None:
    performance, history = _frames()
    same_day = performance.copy()
    same_day.loc[same_day["canonical_bout_id"] == "three", "fight_date"] = "2020-02-01"
    first = build_opponent_adjusted_snapshots(same_day, history)
    second = build_opponent_adjusted_snapshots(
        same_day.sample(frac=1, random_state=20260719), history.sample(frac=1, random_state=19)
    )
    pd.testing.assert_frame_equal(first, second)
    for fighter in ("a", "c", "d"):
        row = first.loc[
            (first["fight_date"] == pd.Timestamp("2020-02-01"))
            & (first["canonical_fighter_id"] == fighter)
        ].iloc[0]
        assert row["opponent_adjusted_significant_strikes_landed_observation_count"] == 0
    assert first.filter(like="_mean").isna().any().all()


def test_exact_pack_membership_is_small_and_fixed() -> None:
    base = ("base",)
    overall = ("a_elo", "b_elo", "diff_elo", "elo_expected_probability_a")
    packs = feature_packs(base, overall)
    assert [pack.pack_id for pack in packs] == [
        "base_plus_overall_elo",
        "overall_elo_plus_career_adjusted",
        "overall_elo_plus_recent_adjusted",
        "overall_elo_plus_all_adjusted",
    ]
    assert [pack.added_feature_count for pack in packs] == [0, 24, 24, 48]
    assert len(adjusted_feature_names()) == 16
    assert set(packs[-1].feature_columns) - set(base) - set(overall) == {
        f"{side}{feature}" for side in ("a_", "b_", "diff_") for feature in adjusted_feature_names()
    }
