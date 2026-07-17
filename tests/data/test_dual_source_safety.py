from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from ufc_predictor.canonical.review_queues import build_taxonomy_review_queue
from ufc_predictor.features.historical import HistoricalFight, pre_fight_features
from ufc_predictor.identity.review_queue import build_identity_review_queue
from ufc_predictor.reconciliation import (
    ReconciliationClass,
    SourceBout,
    reconcile_bouts,
)


def test_identity_queue_flags_known_variants_and_bruno_silva_without_merging() -> None:
    queue = build_identity_review_queue(
        source="fixture", observed_names=("Kai Kara France", "Kai Kara-France", "Bruno Silva")
    )
    assert any(item.raw_value == "Kai Kara France" for item in queue)
    bruno = next(item for item in queue if item.raw_value == "Bruno Silva")
    assert "separate" in bruno.reason
    assert bruno.proposed_value is None


def test_taxonomy_queue_includes_missing_stance_catch_weight_and_four_round_bouts() -> None:
    queue = build_taxonomy_review_queue(
        source="fixture",
        rows=(
            {
                "stance": "",
                "weight_class": "Catch Weight ",
                "no_of_rounds": "4",
                "finish_round": "5",
                "height": "300",
            },
        ),
    )
    reasons = {item.reason for item in queue}
    assert "stance whitespace or missing" in reasons
    assert "division naming, Catch Weight, or women's division" in reasons
    assert "four-round or scheduled-round review" in reasons


def test_reconciliation_retains_source_rows_and_identifies_classifications() -> None:
    red, blue, third = uuid4(), uuid4(), uuid4()
    left = SourceBout(
        "ultimate",
        "u1",
        date(2024, 1, 1),
        red,
        blue,
        "red",
        "KO",
        1,
        "1:00",
        3,
        "LW",
        "Event",
        "Vegas",
    )
    swapped = SourceBout(
        "datalab",
        "d1",
        date(2024, 1, 1),
        blue,
        red,
        "blue",
        "KO",
        1,
        "1:00",
        3,
        "LW",
        "Event",
        "Vegas",
    )
    conflict = SourceBout(
        "datalab",
        "d2",
        date(2024, 1, 1),
        red,
        blue,
        "blue",
        "KO",
        1,
        "1:00",
        3,
        "LW",
        "Event",
        "Vegas",
    )
    unmatched = SourceBout(
        "datalab",
        "d3",
        date(2024, 1, 3),
        red,
        third,
        "red",
        "KO",
        1,
        "1:00",
        3,
        "LW",
        "Event",
        "Vegas",
    )
    exact = reconcile_bouts((left,), (left,))[0]
    normalized = reconcile_bouts(
        (left,),
        (
            SourceBout(
                "datalab",
                "d-normal",
                date(2024, 1, 1),
                red,
                blue,
                "red",
                "KO",
                1,
                "1:00",
                3,
                "lw",
                "EVENT!",
                "vegas ",
            ),
        ),
    )[0]
    corner_swapped = reconcile_bouts((left,), (swapped,))[0]
    conflicting = reconcile_bouts((left,), (conflict,))[0]
    probable = reconcile_bouts(
        (left,),
        (
            SourceBout(
                "datalab",
                "d-probable",
                date(2024, 1, 1),
                red,
                blue,
                "red",
                "KO",
                1,
                "1:00",
                3,
                "LW",
                None,
                "Vegas",
            ),
        ),
    )[0]
    ambiguous = reconcile_bouts((left,), (swapped, exact_to_source_bout(left, "d-ambiguous")))[0]
    unmatched_results = reconcile_bouts((left,), (unmatched,))
    assert exact.classification is ReconciliationClass.EXACT
    assert normalized.classification is ReconciliationClass.NORMALIZED_EXACT
    assert corner_swapped.classification is ReconciliationClass.CORNER_SWAPPED
    assert conflicting.classification is ReconciliationClass.CONFLICT
    assert probable.classification is ReconciliationClass.PROBABLE
    assert ambiguous.classification is ReconciliationClass.AMBIGUOUS
    assert any(
        result.classification is ReconciliationClass.UNMATCHED for result in unmatched_results
    )


def exact_to_source_bout(bout: SourceBout, record_key: str) -> SourceBout:
    return SourceBout(
        "datalab",
        record_key,
        bout.event_date,
        bout.red_fighter_id,
        bout.blue_fighter_id,
        bout.winner,
        bout.method,
        bout.finish_round,
        bout.finish_time,
        bout.scheduled_rounds,
        bout.division,
        bout.event_name,
        bout.location,
    )


def test_pre_fight_features_exclude_same_and_future_fights_and_negate_differences() -> None:
    red, blue = uuid4(), uuid4()
    target = datetime(2024, 2, 1, tzinfo=UTC)
    history = (
        HistoricalFight(
            target - timedelta(days=10), red, blue, "win", "loss", {"strikes": 10}, {"strikes": 5}
        ),
        HistoricalFight(target, red, blue, "loss", "win", {"strikes": 999}, {"strikes": 999}),
        HistoricalFight(
            target + timedelta(days=1), red, blue, "loss", "win", {"strikes": 999}, {"strikes": 999}
        ),
    )
    forward = pre_fight_features(
        target_time=target, red_fighter_id=red, blue_fighter_id=blue, history=history
    )
    reverse = pre_fight_features(
        target_time=target, red_fighter_id=blue, blue_fighter_id=red, history=history
    )
    assert forward["red_career_strikes"] == 10
    assert forward["difference_career_strikes"] == -reverse["difference_career_strikes"]
    assert forward["red_prior_ufc_bouts"] == 1
