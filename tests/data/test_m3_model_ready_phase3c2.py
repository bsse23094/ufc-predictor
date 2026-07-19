from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from ufc_predictor.m3_materialization import (
    _PAIRWISE_FEATURE_REGISTRY,
    _model_ready_binary,
    _model_ready_feature_columns,
    materialize_m3_v6,
    resolve_m3_current_generation,
    swap_model_ready_row,
)

ROOT = Path(__file__).parents[2]


def _synthetic_pairwise() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for bout, winner, draw, no_contest in (
        ("a-win", 1, False, False),
        ("b-win", 0, False, False),
        ("draw", None, True, False),
        ("nc", None, False, True),
    ):
        row: dict[str, object] = {
            "canonical_bout_id": bout,
            "fight_date": "2020-01-01",
            "canonical_fighter_a_id": "a",
            "canonical_fighter_b_id": "b",
            "orientation_policy_id": "canonical",
            "feature_schema_version": "test",
            "pairwise_evidence_sha256": "evidence",
            "fighter_a_won": winner,
            "is_draw": draw,
            "is_no_contest": no_contest,
            "target_bout_performance_not_a_feature": 99,
        }
        for index, entry in enumerate(_PAIRWISE_FEATURE_REGISTRY):
            name = entry["source_column"]
            a_value: int | float | bool | None = 0 if index == 0 else index + 1
            b_value: int | float | bool | None = None if index == 1 else index
            if entry["data_type"] == "bool":
                a_value, b_value = True, False
            row[f"a_{name}"] = a_value
            row[f"b_{name}"] = b_value
            row[f"a_{name}_missing"] = a_value is None
            row[f"b_{name}_missing"] = b_value is None
            row[f"diff_{name}"] = (
                None if a_value is None or b_value is None else float(a_value) - float(b_value)
            )
        rows.append(row)
    return pl.DataFrame(rows)


@pytest.fixture(scope="module")
def generation(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("m3-phase3c2")
    materialize_m3_v6(
        ultimate_csv=ROOT / "data/incoming/ultimate-ufc-dataset/ufc-master.csv",
        datalab_csv=ROOT
        / "data/incoming/ufc-datalab/3268146c05211de9deab8b9b4c0bb4a954815f0b/stats_raw.csv",
        v6_dir=ROOT / "data/quarantine/reviews/m3-corrections-v6",
        output_dir=output,
    )
    return resolve_m3_current_generation(output)


def test_binary_projection_contract_and_provenance(generation: Path) -> None:
    frame = pl.read_parquet(generation / "m3_model_ready_binary.parquet")
    pairwise = pl.read_parquet(generation / "m3_prefight_pairwise_features.parquet")
    provenance = pl.read_parquet(generation / "m3_normalized_provenance.parquet")
    features = _model_ready_feature_columns()
    metadata = [
        "canonical_bout_id",
        "fight_date",
        "canonical_fighter_a_id",
        "canonical_fighter_b_id",
        "orientation_policy_id",
        "feature_schema_version",
        "pairwise_evidence_sha256",
    ]
    assert frame.height == frame["canonical_bout_id"].n_unique() == 8912
    assert frame.width == 138
    assert frame.columns[:7] == metadata
    assert frame.columns[-1] == "target_fighter_a_won"
    assert frame.schema["target_fighter_a_won"] in {pl.Int64, pl.UInt8, pl.Boolean}
    assert not set([*metadata, "target_fighter_a_won"]) & set(features)
    assert frame["target_fighter_a_won"].sum() == 4610
    assert frame.filter(pl.col("target_fighter_a_won") == 0).height == 4302
    assert pairwise.height - frame.height == 156
    assert len(features) == 130 and frame.columns[-131:-1] == features
    assert set(frame["canonical_bout_id"]) == set(
        pairwise.filter(~pl.col("is_draw") & ~pl.col("is_no_contest"))["canonical_bout_id"]
    )
    assert provenance.select(["output_artifact", "output_row_key"]).unique().height == 150162
    assert (
        provenance.filter(pl.col("output_artifact") == "m3_model_ready_binary.parquet")[
            "output_row_key"
        ].n_unique()
        == 8912
    )
    manifest = json.loads((generation / "m3_phase2_manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase_3c2"]["prediction_safe_feature_columns"] == features
    assert len(manifest["phase_3c2"]["excluded_draw_bout_ids"]) == 65
    assert len(manifest["phase_3c2"]["excluded_no_contest_bout_ids"]) == 91
    forbidden = (
        "odds",
        "rank",
        "winner_canonical",
        "loser_canonical",
        "canonical_finish",
        "source_order",
    )
    assert not [name for name in features if any(term in name.casefold() for term in forbidden)]


def test_model_ready_swap_and_missingness_contract(generation: Path) -> None:
    frame = pl.read_parquet(generation / "m3_model_ready_binary.parquet")
    for row in frame.to_dicts():
        swapped = swap_model_ready_row(row)
        assert swapped["target_fighter_a_won"] == 1 - row["target_fighter_a_won"]
        assert swap_model_ready_row(swapped) == row
    for feature in _model_ready_feature_columns():
        if feature.endswith("_missing"):
            value = feature.removesuffix("_missing")
            assert frame.filter(pl.col(feature) != pl.col(value).is_null()).height == 0
    floats = [name for name, dtype in frame.schema.items() if dtype == pl.Float64]
    assert (
        frame.select(
            pl.any_horizontal(
                [pl.col(name).is_not_null() & ~pl.col(name).is_finite() for name in floats]
            ).any()
        ).item()
        is False
    )


def test_synthetic_eligibility_target_null_and_mutation_boundaries(tmp_path: Path) -> None:
    pairwise = _synthetic_pairwise()
    projected = _model_ready_binary(pairwise, validate_cardinality=False)
    assert projected["canonical_bout_id"].to_list() == ["a-win", "b-win"]
    assert projected["target_fighter_a_won"].to_list() == [1, 0]
    assert set(pairwise["canonical_bout_id"]) - set(projected["canonical_bout_id"]) == {
        "draw",
        "nc",
    }
    assert projected["a_prior_bouts"][0] == 0
    assert projected["b_prior_decisive_bouts"][0] is None
    assert projected["b_prior_decisive_bouts_missing"][0] is True
    assert "target_bout_performance_not_a_feature" not in projected.columns

    changed_winner = pairwise.with_columns(
        pl.when(pl.col("canonical_bout_id") == "a-win")
        .then(pl.lit(0))
        .otherwise(pl.col("fighter_a_won"))
        .alias("fighter_a_won")
    )
    changed_projection = _model_ready_binary(changed_winner, validate_cardinality=False)
    assert changed_projection.drop("target_fighter_a_won").equals(
        projected.drop("target_fighter_a_won")
    )
    assert changed_projection["target_fighter_a_won"].to_list() == [0, 0]
    shuffled = _model_ready_binary(
        pairwise.sample(fraction=1, shuffle=True, seed=7), validate_cardinality=False
    )
    first, second = tmp_path / "first.parquet", tmp_path / "second.parquet"
    projected.write_parquet(first)
    shuffled.write_parquet(second)
    assert first.read_bytes() == second.read_bytes()
