from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl

from ufc_predictor.identity.candidates import generate_candidate_pairs
from ufc_predictor.identity.normalize import candidate_fighter_aliases
from ufc_predictor.identity.scorer import CandidateRecommendation, score_candidate_pair
from ufc_predictor.m3_dual_source import (
    CandidateReconciliationClass,
    generate_candidate_prior_history_features,
    reconcile_ultimate_and_datalab_candidate_records,
    reconcile_ultimate_and_datalab_candidates,
    write_reconciliation_artifacts,
)


def test_candidate_reconciliation_and_history_use_only_strictly_earlier_dates(
    tmp_path: Path,
) -> None:
    ultimate = tmp_path / "ultimate.csv"
    ultimate.write_text(
        "R_fighter,B_fighter,date,Winner,finish,no_of_rounds,weight_class,location\n"
        "Alpha Fighter,Beta Fighter,2024-01-01,Red,KO/TKO,3,Lightweight,Las Vegas\n",
        encoding="utf-8",
    )
    parquet = tmp_path / "datalab.parquet"
    pl.DataFrame(
        {
            "source_record_key": ["stats_raw.csv:row-2", "stats_raw.csv:row-3"],
            "fight_date": [date(2024, 1, 1), date(2024, 1, 2)],
            "red_fighter_source_name": ["Alpha Fighter", "Alpha Fighter"],
            "blue_fighter_source_name": ["Beta Fighter", "Gamma Fighter"],
            "outcome_source_value": ["red_win", "blue_win"],
            "method_source_value": ["KO/TKO", "Decision"],
            "scheduled_rounds": [3, 3],
            "division_source_value": ["Lightweight", "Lightweight"],
            "location": ["Las Vegas", "Las Vegas"],
            "detailed_statistics": [
                json.dumps(
                    {
                        "red_fighter_KD": "1",
                        "blue_fighter_KD": "0",
                        "red_fighter_sig_str": "10 of 20",
                        "blue_fighter_sig_str": "2 of 5",
                        "red_fighter_TD": "0 of 0",
                        "blue_fighter_TD": "0 of 0",
                        "red_fighter_sub_att": "0",
                        "blue_fighter_sub_att": "0",
                        "red_fighter_ctrl": "0:10",
                        "blue_fighter_ctrl": "0:00",
                    }
                ),
                json.dumps({}),
            ],
        }
    ).write_parquet(parquet)

    report = reconcile_ultimate_and_datalab_candidates(
        ultimate_csv=ultimate, datalab_parquet=parquet
    )
    feature_path = tmp_path / "features.parquet"
    dimensions = generate_candidate_prior_history_features(
        datalab_parquet=parquet, output_path=feature_path
    )
    features = pl.read_parquet(feature_path).sort("fight_date")

    assert report.exact == 1
    assert report.conflict == 0
    assert dimensions == (2, 51)
    assert features["red_prior_ufc_bouts"].to_list() == [0.0, 1.0]
    assert features["red_career_significant_strikes"].to_list() == [0.0, 10.0]
    assert "detailed_statistics" not in features.columns
    assert "red_fighter_sig_str" not in features.columns


def test_deterministic_normalization_preserves_source_winner_and_fighter_values(
    tmp_path: Path,
) -> None:
    ultimate = tmp_path / "ultimate.csv"
    ultimate.write_text(
        "R_fighter,B_fighter,date,Winner,finish,no_of_rounds,weight_class,location\n"
        "Jos\u00e9 Aldo,Renan Bar\u00e3o,2024-01-01,Red,KO/TKO,3,Featherweight,Las Vegas\n",
        encoding="utf-8",
    )
    parquet = tmp_path / "datalab.parquet"
    pl.DataFrame(
        {
            "source_record_key": ["stats_raw.csv:row-2"],
            "fight_date": [date(2024, 1, 1)],
            "red_fighter_source_name": ["JOSE\u0301 ALDO"],
            "blue_fighter_source_name": ["RENAN BAR\u00c3O"],
            "outcome_source_value": ["red_win"],
            "method_source_value": ["KO TKO"],
            "scheduled_rounds": [3],
            "finish_round": [None],
            "division_source_value": ["Featherweight Bout"],
            "event_name": [None],
            "location": ["Las-Vegas"],
            "detailed_statistics": [json.dumps({})],
        }
    ).write_parquet(parquet)

    records = reconcile_ultimate_and_datalab_candidate_records(
        ultimate_csv=ultimate, datalab_parquet=parquet
    )
    record = records[0]

    assert record.classification is CandidateReconciliationClass.EQUIVALENT
    assert record.left is not None and record.right is not None
    assert record.left.red_name == "Jos\u00e9 Aldo"
    assert record.right.red_name == "JOSE\u0301 ALDO"
    assert record.left.outcome == "Red"
    assert record.right.outcome == "red_win"
    outcome = next(item for item in record.comparisons if item.field == "outcome")
    assert outcome.left_normalized == outcome.right_normalized


def test_material_outcomes_and_ambiguous_matches_remain_in_human_review(tmp_path: Path) -> None:
    ultimate = tmp_path / "ultimate.csv"
    ultimate.write_text(
        "R_fighter,B_fighter,date,Winner,finish,no_of_rounds,weight_class,location\n"
        "Alpha Fighter,Beta Fighter,2024-01-01,Red,KO,3,Lightweight,Las Vegas\n"
        "Gamma Fighter,Delta Fighter,2024-01-02,Red,KO,3,Lightweight,Las Vegas\n",
        encoding="utf-8",
    )
    parquet = tmp_path / "datalab.parquet"
    pl.DataFrame(
        {
            "source_record_key": ["d-1", "d-2", "d-3"],
            "fight_date": [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 2)],
            "red_fighter_source_name": ["Alpha Fighter", "Gamma Fighter", "Gamma Fighter"],
            "blue_fighter_source_name": ["Beta Fighter", "Delta Fighter", "Delta Fighter"],
            "outcome_source_value": ["blue_win", "red_win", "red_win"],
            "method_source_value": ["KO", "KO", "KO"],
            "scheduled_rounds": [3, 3, 3],
            "finish_round": [None, None, None],
            "division_source_value": ["Lightweight", "Lightweight", "Lightweight"],
            "event_name": [None, None, None],
            "location": ["Las Vegas", "Las Vegas", "Las Vegas"],
            "detailed_statistics": [json.dumps({}), json.dumps({}), json.dumps({})],
        }
    ).write_parquet(parquet)

    records = reconcile_ultimate_and_datalab_candidate_records(
        ultimate_csv=ultimate, datalab_parquet=parquet
    )
    classes = {record.classification for record in records}
    report = reconcile_ultimate_and_datalab_candidates(
        ultimate_csv=ultimate, datalab_parquet=parquet
    )

    assert CandidateReconciliationClass.MATERIAL_OUTCOME in classes
    assert CandidateReconciliationClass.AMBIGUOUS in classes
    assert report.material_outcome_conflict == 1
    assert report.ambiguous_match == 1
    assert report.human_review_queue_size == 2


def test_ambiguous_fighter_alias_candidates_remain_unresolved() -> None:
    candidates = candidate_fighter_aliases(
        source_identifier="fixture-source",
        rows=tuple(
            {
                "source_record_key": f"fight-{index}",
                "source_raw_sha256": f"{index}" * 64,
                "fighter_one_source_name": "Alex Smith",
                "fighter_two_source_name": f"Opponent {index}",
            }
            for index in range(1, 4)
        ),
    )

    pairs = generate_candidate_pairs(candidates)
    scores = tuple(score_candidate_pair(pair) for pair in pairs)

    assert len(pairs) == 3
    assert all(score.recommendation is CandidateRecommendation.REVIEW_REQUIRED for score in scores)
    assert all(score.auto_link_threshold is None for score in scores)
    assert all(not hasattr(pair, "fighter_id") for pair in pairs)


def test_reconciliation_artifacts_are_deterministic_and_leave_sources_unchanged(
    tmp_path: Path,
) -> None:
    ultimate = tmp_path / "ultimate.csv"
    ultimate.write_text(
        "R_fighter,B_fighter,date,Winner,finish,no_of_rounds,weight_class,location\n"
        "Alpha Fighter,Beta Fighter,2024-01-01,Red,Decision,3,Lightweight,Las Vegas\n",
        encoding="utf-8",
    )
    parquet = tmp_path / "datalab.parquet"
    pl.DataFrame(
        {
            "source_record_key": ["d-1"],
            "fight_date": [date(2024, 1, 1)],
            "red_fighter_source_name": ["Alpha Fighter"],
            "blue_fighter_source_name": ["Beta Fighter"],
            "outcome_source_value": ["red_win"],
            "method_source_value": ["Decision"],
            "scheduled_rounds": [3],
            "finish_round": [None],
            "division_source_value": ["Lightweight"],
            "event_name": [None],
            "location": ["Las Vegas"],
            "detailed_statistics": [json.dumps({})],
        }
    ).write_parquet(parquet)
    source_bytes = (ultimate.read_bytes(), parquet.read_bytes())
    output_dir = tmp_path / "artifacts"

    first = write_reconciliation_artifacts(
        ultimate_csv=ultimate, datalab_parquet=parquet, output_dir=output_dir
    )
    artifact_bytes = tuple(path.read_bytes() for path in sorted(output_dir.iterdir()))
    second = write_reconciliation_artifacts(
        ultimate_csv=ultimate, datalab_parquet=parquet, output_dir=output_dir
    )

    assert first == second
    assert source_bytes == (ultimate.read_bytes(), parquet.read_bytes())
    assert artifact_bytes == tuple(path.read_bytes() for path in sorted(output_dir.iterdir()))
    payload = json.loads((output_dir / "deterministic_or_soft_conflicts.jsonl").read_text())
    assert payload["left_source"]["outcome"] == "Red"
    assert payload["right_source"]["outcome"] == "red_win"
