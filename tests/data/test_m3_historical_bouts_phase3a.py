from __future__ import annotations

import csv
import json
from hashlib import sha256
from pathlib import Path

import polars as pl
import pytest

from ufc_predictor.m3_materialization import (
    _HISTORICAL_FIELD_CLASSIFICATION,
    _HISTORICAL_SCHEMA,
    _PUBLISHED_ARTIFACTS,
    _artifact_row_key,
    _canonical_historical_bout_rows,
    materialize_m3_v6,
    resolve_m3_current_generation,
)

ROOT = Path(__file__).parents[2]
V6_DIR = ROOT / "data/quarantine/reviews/m3-corrections-v6"
ULTIMATE = ROOT / "data/incoming/ultimate-ufc-dataset/ufc-master.csv"
DATALAB = ROOT / "data/incoming/ufc-datalab/3268146c05211de9deab8b9b4c0bb4a954815f0b/stats_raw.csv"


def _materialize(output_dir: Path, failure_injection: str | None = None) -> dict[str, object]:
    return materialize_m3_v6(
        ultimate_csv=ULTIMATE,
        datalab_csv=DATALAB,
        v6_dir=V6_DIR,
        output_dir=output_dir,
        failure_injection=failure_injection,
    )


@pytest.fixture(scope="module")
def generation(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("m3-phase3a")
    _materialize(output)
    return resolve_m3_current_generation(output)


def _history(generation: Path) -> pl.DataFrame:
    return pl.read_parquet(generation / "m3_canonical_historical_bouts.parquet")


def test_historical_bouts_are_complete_canonical_and_outcome_safe(generation: Path) -> None:
    historical = _history(generation)
    reconciliation = pl.read_parquet(generation / "m3_bout_reconciliation.parquet")
    fighters = set(
        pl.read_parquet(generation / "m3_canonical_fighters.parquet")["canonical_fighter_id"]
    )
    assert historical.height == reconciliation.height == 9068
    assert historical["canonical_bout_id"].n_unique() == 9068
    assert set(historical["canonical_bout_id"]) == set(reconciliation["canonical_bout_id"])
    assert set(historical["canonical_fighter_a_id"]) <= fighters
    assert set(historical["canonical_fighter_b_id"]) <= fighters
    assert (
        historical.filter(
            pl.col("canonical_fighter_a_id") == pl.col("canonical_fighter_b_id")
        ).height
        == 0
    )
    decisive = historical.filter(~pl.col("is_no_contest") & ~pl.col("is_draw"))
    assert all(
        row["winner_canonical_fighter_id"]
        in {row["canonical_fighter_a_id"], row["canonical_fighter_b_id"]}
        and row["loser_canonical_fighter_id"]
        in {row["canonical_fighter_a_id"], row["canonical_fighter_b_id"]}
        for row in decisive.iter_rows(named=True)
    )
    non_decisive = historical.filter(pl.col("is_no_contest") | pl.col("is_draw"))
    assert non_decisive["winner_canonical_fighter_id"].null_count() == non_decisive.height
    assert non_decisive["loser_canonical_fighter_id"].null_count() == non_decisive.height


def test_reviewed_outcomes_exclusions_and_duplicate_collapse_survive(generation: Path) -> None:
    historical = _history(generation)
    reconciliation = pl.read_parquet(generation / "m3_bout_reconciliation.parquet")
    reviewed = historical.filter(pl.col("outcome_authority_id").is_not_null())
    assert reviewed.height == 14
    assert reviewed.filter(pl.col("is_no_contest")).height == 12
    assert (
        reviewed.filter(pl.col("outcome_authority_id") == "M3-OUT-50CDBFC0140F")[
            "winner_canonical_fighter_id"
        ].null_count()
        == 0
    )
    assert (
        reviewed.filter(pl.col("outcome_authority_id") == "M3-OUT-BFB8E0079B5C")[
            "winner_canonical_fighter_id"
        ].null_count()
        == 0
    )
    assert {"row-5170", "row-5658"}.isdisjoint(
        set(reconciliation["ultimate_source_row_id"].drop_nulls())
    )
    assert reconciliation.filter(pl.col("ufc_datalab_source_row_id") == "row-8604").height == 0
    assert historical["canonical_bout_id"].n_unique() == historical.height


def test_orientation_and_chronology_are_deterministic_and_conservative(generation: Path) -> None:
    historical = _history(generation)
    assert (
        historical.filter(
            pl.col("canonical_fighter_a_id") >= pl.col("canonical_fighter_b_id")
        ).height
        == 0
    )
    assert set(historical["fighter_orientation"]) == {"canonical_fighter_id_ascending"}
    assert historical["global_chronological_key"].to_list() == sorted(
        historical["global_chronological_key"].to_list()
    )
    assert set(historical["ordering_confidence"]) == {"ambiguous_same_date"}
    assert set(historical["same_date_history_policy"]) == {"exclude_same_fight_date_bouts"}
    # A serial key exists for reproducible files, but it is explicitly not an
    # asserted intra-day chronology for future historical feature computation.
    assert (
        historical.filter(pl.col("fight_date").is_duplicated())["ordering_confidence"]
        .eq("ambiguous_same_date")
        .all()
    )


def test_upstream_row_shuffling_does_not_change_historical_artifact_bytes(
    generation: Path, tmp_path: Path
) -> None:
    reconciliation = pl.read_parquet(generation / "m3_bout_reconciliation.parquet")
    fighters = set(
        pl.read_parquet(generation / "m3_canonical_fighters.parquet")["canonical_fighter_id"]
    )
    ultimate_by_row = {
        f"row-{number}": row
        for number, row in enumerate(
            csv.DictReader(ULTIMATE.open(encoding="utf-8-sig", newline="")), start=2
        )
    }
    datalab_by_row = {
        f"row-{number}": row
        for number, row in enumerate(
            csv.DictReader(DATALAB.open(encoding="utf-8-sig", newline=""), delimiter=";"), start=2
        )
    }

    def write_projected(frame: pl.DataFrame, path: Path) -> None:
        pl.DataFrame(
            _canonical_historical_bout_rows(
                reconciliation=frame,
                ultimate_by_row=ultimate_by_row,
                datalab_by_row=datalab_by_row,
                canonical_fighter_ids=fighters,
            ),
            schema=_HISTORICAL_SCHEMA,
        ).sort("global_chronological_key").write_parquet(path)

    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"
    write_projected(reconciliation, first)
    write_projected(reconciliation.sample(fraction=1.0, shuffle=True, seed=17), second)
    assert first.read_bytes() == second.read_bytes()


def test_leakage_classification_and_provenance_are_complete(generation: Path) -> None:
    historical = _history(generation)
    classifications = [json.loads(value) for value in historical["field_classification"].unique()]
    assert classifications == [json.loads(_HISTORICAL_FIELD_CLASSIFICATION)]
    safe = {
        name
        for name, classification in json.loads(_HISTORICAL_FIELD_CLASSIFICATION).items()
        if classification == "prediction-time-safe bout context"
    }
    forbidden_fragments = ("odds", "rank", "_dif", "sig_str", "total_str", "_td", "_kd")
    assert not [
        name for name in safe if any(part in name.casefold() for part in forbidden_fragments)
    ]
    provenance = pl.read_parquet(generation / "m3_normalized_provenance.parquet")
    historical_provenance = provenance.filter(
        pl.col("output_artifact") == "m3_canonical_historical_bouts.parquet"
    )
    assert historical_provenance["output_row_key"].n_unique() == 9068
    assert provenance.select(["output_artifact", "output_row_key"]).unique().height == 150162
    manifest = json.loads((generation / "m3_phase2_manifest.json").read_text(encoding="utf-8"))
    metadata = manifest["artifacts"]["m3_canonical_historical_bouts.parquet"]
    path = generation / "m3_canonical_historical_bouts.parquet"
    assert metadata["row_count"] == 9068
    assert metadata["column_count"] == historical.width
    assert metadata["sha256"] == sha256(path.read_bytes()).hexdigest()
    assert manifest["provenance"]["unique_covered_rows"] == 150162


def test_replay_and_failure_preserve_atomic_generation(tmp_path: Path) -> None:
    _materialize(tmp_path)
    first_generation = resolve_m3_current_generation(tmp_path)
    first = {
        path.name: sha256(path.read_bytes()).hexdigest() for path in first_generation.iterdir()
    }
    _materialize(tmp_path)
    assert resolve_m3_current_generation(tmp_path) == first_generation
    assert {
        path.name: sha256(path.read_bytes()).hexdigest() for path in first_generation.iterdir()
    } == first
    with pytest.raises(RuntimeError, match="injected failure"):
        _materialize(tmp_path, "after_validation_before_commit")
    assert resolve_m3_current_generation(tmp_path) == first_generation
    assert {
        path.name: sha256(path.read_bytes()).hexdigest() for path in first_generation.iterdir()
    } == first
    assert "m3_canonical_historical_bouts.parquet" in {name for name, _ in _PUBLISHED_ARTIFACTS}
    assert _artifact_row_key(
        "m3_canonical_historical_bouts.parquet", _history(first_generation).row(0, named=True)
    ) in set(_history(first_generation)["canonical_bout_id"])
