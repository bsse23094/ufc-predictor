from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from ufc_predictor.m3_materialization import (
    _PAIRWISE_FEATURE_REGISTRY,
    _pairwise_feature_columns,
    materialize_m3_v6,
    resolve_m3_current_generation,
    swap_pairwise_row,
)

ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def generation(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("m3-phase3c1")
    materialize_m3_v6(
        ultimate_csv=ROOT / "data/incoming/ultimate-ufc-dataset/ufc-master.csv",
        datalab_csv=ROOT
        / "data/incoming/ufc-datalab/3268146c05211de9deab8b9b4c0bb4a954815f0b/stats_raw.csv",
        v6_dir=ROOT / "data/quarantine/reviews/m3-corrections-v6",
        output_dir=output,
    )
    return resolve_m3_current_generation(output)


def test_pairwise_grain_registry_labels_and_provenance(generation: Path) -> None:
    pairwise = pl.read_parquet(generation / "m3_prefight_pairwise_features.parquet")
    provenance = pl.read_parquet(generation / "m3_normalized_provenance.parquet")
    assert pairwise.height == pairwise["canonical_bout_id"].n_unique() == 9068
    assert (
        pairwise.filter(pl.col("canonical_fighter_a_id") == pl.col("canonical_fighter_b_id")).height
        == 0
    )
    assert _pairwise_feature_columns() <= set(pairwise.columns)
    labels = {"canonical_outcome", "fighter_a_won", "is_draw", "is_no_contest"}
    assert not labels & _pairwise_feature_columns()
    assert (
        pairwise.select(
            pl.any_horizontal(
                [
                    pl.col(c).is_not_null() & ~pl.col(c).is_finite()
                    for c in pairwise.columns
                    if pairwise.schema[c] == pl.Float64
                ]
            ).any()
        ).item()
        is False
    )
    assert provenance.select(["output_artifact", "output_row_key"]).unique().height == 150162
    assert (
        provenance.filter(pl.col("output_artifact") == "m3_prefight_pairwise_features.parquet")[
            "output_row_key"
        ].n_unique()
        == 9068
    )
    manifest = json.loads((generation / "m3_phase2_manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase_3c1"]["feature_registry"] == list(_PAIRWISE_FEATURE_REGISTRY)


def test_production_corner_swap_is_an_involution(generation: Path) -> None:
    pairwise = pl.read_parquet(generation / "m3_prefight_pairwise_features.parquet")
    for row in pairwise.to_dicts():
        swapped = swap_pairwise_row(row)
        assert swapped["canonical_fighter_a_id"] == row["canonical_fighter_b_id"]
        assert swapped["canonical_fighter_b_id"] == row["canonical_fighter_a_id"]
        assert swap_pairwise_row(swapped) == row
        for entry in _PAIRWISE_FEATURE_REGISTRY:
            name = entry["source_column"]
            assert swapped[f"a_{name}"] == row[f"b_{name}"]
            assert swapped[f"b_{name}"] == row[f"a_{name}"]
            assert swapped[f"diff_{name}"] == (
                -row[f"diff_{name}"] if row[f"diff_{name}"] is not None else None
            )
        if row["fighter_a_won"] is not None:
            assert swapped["fighter_a_won"] == 1 - row["fighter_a_won"]
        else:
            assert swapped["fighter_a_won"] is None
        assert (
            swapped["is_draw"] == row["is_draw"]
            and swapped["is_no_contest"] == row["is_no_contest"]
        )
