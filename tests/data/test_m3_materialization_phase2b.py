from __future__ import annotations

import csv
from collections import Counter
from hashlib import sha256
from pathlib import Path

import polars as pl
import pytest

from ufc_predictor.m3_materialization import (
    _fighter,
    _reconciliation_rows,
    load_authority_index,
    materialize_m3_v6,
    resolve_m3_current_generation,
)

ROOT = Path(__file__).parents[2]
OUTPUT = ROOT / "data/processed/m3-v6"
V6_DIR = ROOT / "data/quarantine/reviews/m3-corrections-v6"
ULTIMATE = ROOT / "data/incoming/ultimate-ufc-dataset/ufc-master.csv"
DATALAB = ROOT / "data/incoming/ufc-datalab/3268146c05211de9deab8b9b4c0bb4a954815f0b/stats_raw.csv"


def _artifacts() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    return (
        pl.read_parquet(OUTPUT / "m3_bout_reconciliation.parquet"),
        pl.read_parquet(OUTPUT / "m3_source_bout_crosswalk.parquet"),
        pl.read_parquet(OUTPUT / "m3_semantic_bout_groups.parquet"),
        pl.read_parquet(OUTPUT / "m3_reviewed_exclusions.parquet"),
        pl.read_parquet(OUTPUT / "m3_duplicate_collapses.parquet"),
    )


def test_phase2b_reconciliation_has_one_row_per_accepted_semantic_group() -> None:
    reconciliation, crosswalk, groups, _, _ = _artifacts()
    assert reconciliation.height == groups.height == 9068
    assert reconciliation["canonical_bout_id"].n_unique() == 9068
    assert set(crosswalk["canonical_bout_id"]) == set(reconciliation["canonical_bout_id"])
    assert crosswalk.height == 15911
    assert reconciliation.group_by("source_presence").len().sort("source_presence").to_dicts() == [
        {"source_presence": "dual_source", "len": 6843},
        {"source_presence": "ufc_datalab_only", "len": 1893},
        {"source_presence": "ultimate_only", "len": 332},
    ]
    dual = reconciliation.filter(pl.col("source_presence") == "dual_source")
    assert dual["ultimate_source_row_id"].null_count() == 0
    assert dual["ufc_datalab_source_row_id"].null_count() == 0


def test_reviewed_outcomes_are_applied_with_exact_lineage() -> None:
    reconciliation, _, _, _, _ = _artifacts()
    reviewed = reconciliation.filter(pl.col("outcome_authority_id").is_not_null())
    assert reviewed.height == 14
    assert reviewed.filter(pl.col("reconciliation_status") == "canonical_no_contest").height == 12
    assert reviewed.filter(pl.col("is_no_contest")).height == 12
    index = load_authority_index(V6_DIR)
    assert all(
        index.resolve(row["outcome_authority_id"], row["authority_ledger_identifier"]).payload[
            "reviewer_decision"
        ]
        in {"confirm_overturned", "select_ufc_datalab"}
        and row["decision_reference"] == row["outcome_authority_id"]
        for row in reviewed.iter_rows(named=True)
    )
    datalab = {
        f"row-{number}": row
        for number, row in enumerate(csv.DictReader(DATALAB.open(), delimiter=";"), start=2)
    }
    virna = reviewed.filter(pl.col("outcome_authority_id") == "M3-OUT-50CDBFC0140F").row(
        0, named=True
    )
    mike = reviewed.filter(pl.col("outcome_authority_id") == "M3-OUT-BFB8E0079B5C").row(
        0, named=True
    )
    assert datalab[virna["ufc_datalab_source_row_id"]]["red_fighter_name"] == "VIRNA JANDIROBA"
    assert (
        virna["winner_canonical_fighter_id"]
        == _fighter("VIRNA JANDIROBA", datalab[virna["ufc_datalab_source_row_id"]]["bout_type"])[0]
    )
    assert datalab[mike["ufc_datalab_source_row_id"]]["red_fighter_name"] == "MIKE DAVIS"
    assert (
        mike["winner_canonical_fighter_id"]
        == _fighter("MIKE DAVIS", datalab[mike["ufc_datalab_source_row_id"]]["bout_type"])[0]
    )


def test_unresolved_dual_source_conflict_fails_before_materialization() -> None:
    crosswalk = pl.DataFrame(
        [
            {
                "canonical_bout_id": "bout",
                "source_name": "ultimate",
                "source_row_id": "row-2",
                "canonical_fighter_a_id": "a",
                "canonical_fighter_b_id": "b",
            },
            {
                "canonical_bout_id": "bout",
                "source_name": "ufc-datalab",
                "source_row_id": "row-3",
                "canonical_fighter_a_id": "a",
                "canonical_fighter_b_id": "b",
            },
        ]
    )
    with pytest.raises(ValueError, match="unresolved source conflict"):
        _reconciliation_rows(
            crosswalk=crosswalk,
            ultimate_by_row={
                "row-2": {
                    "Winner": "Red",
                    "R_fighter": "Alpha",
                    "B_fighter": "Beta",
                    "weight_class": "Flyweight",
                }
            },
            datalab_by_row={
                "row-3": {
                    "fight_outcome": "blue_win",
                    "red_fighter_name": "ALPHA",
                    "blue_fighter_name": "BETA",
                    "bout_type": "Flyweight Bout",
                }
            },
            outcome_authorities={},
        )


def test_exclusions_and_duplicate_collapse_are_structured_and_traceable() -> None:
    reconciliation, crosswalk, _, exclusions, duplicates = _artifacts()
    assert exclusions.height == 2
    assert set(exclusions["source_row_id"]) == {"row-5170", "row-5658"}
    assert not set(exclusions["source_row_id"]).intersection(
        crosswalk.filter(pl.col("source_name") == "ultimate")["source_row_id"]
    )
    assert not set(exclusions["source_row_id"]).intersection(
        reconciliation["ultimate_source_row_id"]
    )
    assert duplicates.height == 1
    duplicate = duplicates.row(0, named=True)
    assert duplicate["duplicate_source_row_id"] == "row-8604"
    assert duplicate["duplicate_reason"] == "duplicate_normalized_candidate_key"
    assert duplicate["authority_id"] is None
    assert duplicate["duplicate_source_row_id"] not in set(exclusions["source_row_id"])
    assert duplicate["retained_source_row_id"] in set(crosswalk["source_row_id"])
    assert duplicate["canonical_bout_id"] in set(reconciliation["canonical_bout_id"])


def test_phase2b_authorities_baselines_and_replay_are_exact(tmp_path: Path) -> None:
    reconciliation, _, _, exclusions, duplicates = _artifacts()
    index = load_authority_index(V6_DIR)
    authority_rows = [
        *reconciliation.filter(pl.col("outcome_authority_id").is_not_null())
        .select(["outcome_authority_id", "authority_ledger_identifier"])
        .iter_rows(),
        *exclusions.select(["authority_id", "ledger_identifier"]).iter_rows(),
    ]
    assert len(authority_rows) == 16
    assert all(
        index.resolve(authority_id, ledger_id).authority_id == authority_id
        for authority_id, ledger_id in authority_rows
    )
    assert duplicates["authority_id"].null_count() == 1
    assert sha256((OUTPUT / "m3_semantic_bout_groups.parquet").read_bytes()).hexdigest() == (
        "7561e3950e86ad4bea4c18dd0293f157c006ca315763ddfa22a9aa91a1936bb8"
    )
    assert sha256((OUTPUT / "m3_source_bout_crosswalk.parquet").read_bytes()).hexdigest() == (
        "170842cc7822f66547f1626a24b709a784d562ba3f1b133519372c811612fdb3"
    )
    assert sha256((OUTPUT / "m3_taxonomy_authorities.parquet").read_bytes()).hexdigest() == (
        "2a418a84ca15bea62069bde976a627f38228fe76de0ea4b48c6d0d5a44442372"
    )
    materialize_m3_v6(
        ultimate_csv=ULTIMATE, datalab_csv=DATALAB, v6_dir=V6_DIR, output_dir=tmp_path
    )
    first_generation = resolve_m3_current_generation(tmp_path)
    first = {
        path.name: sha256(path.read_bytes()).hexdigest()
        for path in sorted(first_generation.glob("m3_*reconciliation.parquet"))
        + sorted(first_generation.glob("m3_*exclusions.parquet"))
        + sorted(first_generation.glob("m3_*collapses.parquet"))
    }
    materialize_m3_v6(
        ultimate_csv=ULTIMATE, datalab_csv=DATALAB, v6_dir=V6_DIR, output_dir=tmp_path
    )
    second_generation = resolve_m3_current_generation(tmp_path)
    second = {
        path.name: sha256(path.read_bytes()).hexdigest()
        for path in sorted(second_generation.glob("m3_*reconciliation.parquet"))
        + sorted(second_generation.glob("m3_*exclusions.parquet"))
        + sorted(second_generation.glob("m3_*collapses.parquet"))
    }
    assert Counter(first) == Counter(second)
