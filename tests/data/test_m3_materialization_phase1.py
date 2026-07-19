from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import polars as pl

from ufc_predictor.m3_materialization import _bout


def test_source_independent_bout_id_ignores_source_row_and_orientation() -> None:
    first = _bout(
        "row-1",
        "ultimate",
        "2020-01-01",
        "fighter-a",
        "fighter-b",
        "Red",
        "Decision",
        3,
        "3",
        None,
        None,
    )
    second = _bout(
        "row-999",
        "ufc-datalab",
        "2020-01-01",
        "fighter-b",
        "fighter-a",
        "Blue",
        "KO",
        1,
        "3 Rnd",
        "Event",
        "Place",
    )
    assert first["canonical_bout_id"] == second["canonical_bout_id"]


def test_bout_id_changes_for_date_or_fighter() -> None:
    base = _bout(
        "row-1",
        "ultimate",
        "2020-01-01",
        "fighter-a",
        "fighter-b",
        "Red",
        "Decision",
        3,
        "3",
        None,
        None,
    )
    changed_date = _bout(
        "row-1",
        "ultimate",
        "2020-01-02",
        "fighter-a",
        "fighter-b",
        "Red",
        "Decision",
        3,
        "3",
        None,
        None,
    )
    changed_fighter = _bout(
        "row-1",
        "ultimate",
        "2020-01-01",
        "fighter-a",
        "fighter-c",
        "Red",
        "Decision",
        3,
        "3",
        None,
        None,
    )
    assert base["canonical_bout_id"] != changed_date["canonical_bout_id"]
    assert base["canonical_bout_id"] != changed_fighter["canonical_bout_id"]


def test_phase1_production_crosswalk_cardinality_and_exclusions() -> None:
    root = Path("data/processed/m3-v6")
    groups = pl.read_parquet(root / "m3_semantic_bout_groups.parquet")
    crosswalk = pl.read_parquet(root / "m3_source_bout_crosswalk.parquet")
    assert groups.height == 9068
    assert crosswalk.height == 15911
    counts = crosswalk.group_by("canonical_bout_id").len()
    dual = counts.filter(pl.col("len") == 2).height
    ultimate_only = groups.filter(pl.col("sources") == ["ultimate"]).height
    datalab_only = groups.filter(pl.col("sources") == ["ufc-datalab"]).height
    assert dual == 6843
    assert ultimate_only == 332 and datalab_only == 1893
    assert dual + ultimate_only + datalab_only == groups.height
    assert 2 * dual + ultimate_only + datalab_only == crosswalk.height
    assert crosswalk.select(["source_name", "source_row_id"]).is_duplicated().sum() == 0
    assert sha256((root / "m3_semantic_bout_groups.parquet").read_bytes()).hexdigest() == (
        "7561e3950e86ad4bea4c18dd0293f157c006ca315763ddfa22a9aa91a1936bb8"
    )
    assert sha256((root / "m3_source_bout_crosswalk.parquet").read_bytes()).hexdigest() == (
        "170842cc7822f66547f1626a24b709a784d562ba3f1b133519372c811612fdb3"
    )
    assert not crosswalk.filter(
        (pl.col("source_name") == "ultimate")
        & pl.col("source_row_id").is_in(["row-5170", "row-5658"])
    ).height
    assert (
        "row-8604"
        not in crosswalk.filter(pl.col("source_name") == "ufc-datalab")["source_row_id"].to_list()
    )


def test_crosswalk_ordering_and_group_references_are_deterministic() -> None:
    root = Path("data/processed/m3-v6")
    groups = pl.read_parquet(root / "m3_semantic_bout_groups.parquet")
    crosswalk = pl.read_parquet(root / "m3_source_bout_crosswalk.parquet")
    assert crosswalk.equals(crosswalk.sort(["canonical_bout_id", "source_name", "source_row_id"]))
    assert set(crosswalk["canonical_bout_id"]) == set(groups["canonical_bout_id"])
    assert not groups.filter(pl.col("canonical_bout_id").is_duplicated()).height
