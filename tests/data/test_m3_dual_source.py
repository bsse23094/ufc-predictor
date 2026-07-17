from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl

from ufc_predictor.m3_dual_source import (
    generate_candidate_prior_history_features,
    reconcile_ultimate_and_datalab_candidates,
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
