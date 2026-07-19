from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import polars as pl
import pytest

from ufc_predictor.m3_materialization import (
    _PUBLISHED_ARTIFACTS,
    _artifact_row_key,
    _raw_source_descriptor,
    load_authority_index,
    materialize_m3_v6,
    resolve_m3_current_generation,
)

ROOT = Path(__file__).parents[2]
OUTPUT = ROOT / "data/processed/m3-v6"
V6_DIR = ROOT / "data/quarantine/reviews/m3-corrections-v6"
ULTIMATE = ROOT / "data/incoming/ultimate-ufc-dataset/ufc-master.csv"
DATALAB = ROOT / "data/incoming/ufc-datalab/3268146c05211de9deab8b9b4c0bb4a954815f0b/stats_raw.csv"

ACCEPTED_CHECKSUMS = {
    "m3_semantic_bout_groups.parquet": (
        "7561e3950e86ad4bea4c18dd0293f157c006ca315763ddfa22a9aa91a1936bb8"
    ),
    "m3_source_bout_crosswalk.parquet": (
        "170842cc7822f66547f1626a24b709a784d562ba3f1b133519372c811612fdb3"
    ),
    "m3_taxonomy_authorities.parquet": (
        "2a418a84ca15bea62069bde976a627f38228fe76de0ea4b48c6d0d5a44442372"
    ),
    "m3_bout_reconciliation.parquet": (
        "749930e613ee021514a0eef8a7b22bd2a37e283e90a5433d0674d796c4821be8"
    ),
    "m3_reviewed_exclusions.parquet": (
        "3d7becb0cdc2658e3974dbddb5d823e97264d3054eeb035ba1a33768ac39e8b4"
    ),
    "m3_duplicate_collapses.parquet": (
        "8f81c701828ba4fca99d3dbcdd1f046e652001bf304fa268db3c250c18784b99"
    ),
}


def _materialize(output_dir: Path, failure_injection: str | None = None) -> dict[str, object]:
    return materialize_m3_v6(
        ultimate_csv=ULTIMATE,
        datalab_csv=DATALAB,
        v6_dir=V6_DIR,
        output_dir=output_dir,
        failure_injection=failure_injection,
    )


@pytest.fixture(scope="module")
def published_generation(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    output = tmp_path_factory.mktemp("m3-phase2c")
    _materialize(output)
    return output, resolve_m3_current_generation(output)


def _frames(generation: Path) -> dict[str, pl.DataFrame]:
    return {
        artifact_name: pl.read_parquet(generation / artifact_name)
        for artifact_name, _ in _PUBLISHED_ARTIFACTS
    }


def _hashes(generation: Path) -> dict[str, str]:
    return {
        path.name: sha256(path.read_bytes()).hexdigest()
        for path in sorted(generation.iterdir())
        if path.is_file()
    }


def test_normalized_provenance_covers_the_complete_accepted_artifact_set(
    published_generation: tuple[Path, Path],
) -> None:
    _, generation = published_generation
    frames = _frames(generation)
    provenance = pl.read_parquet(generation / "m3_normalized_provenance.parquet")
    covered = provenance.group_by("output_artifact").agg(
        pl.col("output_row_key").n_unique().alias("covered")
    )
    coverage = dict(covered.iter_rows())
    assert set(coverage) == set(frames)
    assert coverage == {name: frame.height for name, frame in frames.items()}
    assert sum(coverage.values()) == 150162
    assert provenance.select(["output_artifact", "output_row_key"]).unique().height == 150162


def test_provenance_has_no_orphans_and_raw_lineage_resolves(
    published_generation: tuple[Path, Path],
) -> None:
    _, generation = published_generation
    frames = _frames(generation)
    provenance = pl.read_parquet(generation / "m3_normalized_provenance.parquet")
    for artifact_name, frame in frames.items():
        keys = {_artifact_row_key(artifact_name, row) for row in frame.to_dicts()}
        provenance_keys = set(
            provenance.filter(pl.col("output_artifact") == artifact_name)[
                "output_row_key"
            ].to_list()
        )
        assert provenance_keys <= keys
    expected_raw = {
        descriptor["path"]: descriptor["sha256"]
        for descriptor in (
            _raw_source_descriptor(ULTIMATE, "completed-bouts-v1"),
            _raw_source_descriptor(DATALAB, "stats-raw-v1"),
        )
    }
    raw = provenance.filter(pl.col("lineage_type") == "raw_source_lineage")
    assert raw.height > 0
    assert all(
        expected_raw[row["raw_artifact_path"]] == row["raw_artifact_sha256"]
        for row in raw.iter_rows(named=True)
    )


def test_dual_source_authority_exclusion_and_duplicate_lineage_are_explicit(
    published_generation: tuple[Path, Path],
) -> None:
    _, generation = published_generation
    provenance = pl.read_parquet(generation / "m3_normalized_provenance.parquet")
    reconciliation = pl.read_parquet(generation / "m3_bout_reconciliation.parquet")
    dual = reconciliation.filter(pl.col("source_presence") == "dual_source").row(0, named=True)
    dual_raw = provenance.filter(
        (pl.col("output_artifact") == "m3_bout_reconciliation.parquet")
        & (pl.col("output_row_key") == dual["canonical_bout_id"])
        & (pl.col("lineage_type") == "raw_source_lineage")
    )
    assert set(dual_raw["source_dataset"].to_list()) == {"ultimate", "ufc-datalab"}
    authority_rows = provenance.filter(pl.col("authority_id").is_not_null())
    index = load_authority_index(V6_DIR)
    assert all(
        index.resolve(row["authority_id"], row["authority_ledger_identifier"]).authority_id
        == row["authority_id"]
        for row in authority_rows.iter_rows(named=True)
    )
    authority_columns = {
        "m3_canonical_fighters.parquet": ("authority_id", "ledger_identifier"),
        "m3_canonical_fighter_aliases.parquet": ("authority_id", "ledger_identifier"),
        "m3_taxonomy_authorities.parquet": ("authority_id", "ledger_identifier"),
        "m3_bout_reconciliation.parquet": (
            "outcome_authority_id",
            "authority_ledger_identifier",
        ),
        "m3_reviewed_exclusions.parquet": ("authority_id", "ledger_identifier"),
    }
    authority_lineage = {
        tuple(row)
        for row in authority_rows.select(
            [
                "output_artifact",
                "output_row_key",
                "authority_id",
                "authority_ledger_identifier",
            ]
        ).iter_rows()
    }
    for artifact_name, (authority_column, ledger_column) in authority_columns.items():
        for record in (
            pl.read_parquet(generation / artifact_name)
            .filter(pl.col(authority_column).is_not_null())
            .iter_rows(named=True)
        ):
            key = _artifact_row_key(artifact_name, record)
            assert (
                artifact_name,
                key,
                record[authority_column],
                record[ledger_column],
            ) in authority_lineage
    exclusions = provenance.filter(pl.col("output_artifact") == "m3_reviewed_exclusions.parquet")
    assert {"raw_source_lineage", "direct_reviewer_authority"} <= set(
        exclusions["lineage_type"].to_list()
    )
    duplicate = provenance.filter(pl.col("output_artifact") == "m3_duplicate_collapses.parquet")
    assert (
        duplicate.filter(
            pl.col("lineage_type") == "deterministic_duplicate_collapse_lineage"
        ).height
        == 1
    )
    assert duplicate.filter(pl.col("authority_id").is_not_null()).height == 0


def test_manifest_is_deterministic_complete_and_matches_emitted_files(
    published_generation: tuple[Path, Path],
) -> None:
    _, generation = published_generation
    manifest_path = generation / "m3_phase2_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {name for name, _ in _PUBLISHED_ARTIFACTS} | {"m3_normalized_provenance.parquet"}
    assert set(manifest["artifacts"]) == expected
    assert manifest["provenance"]["unique_covered_rows"] == 150162
    assert manifest["provenance"]["coverage_denominator"] == 150162
    assert manifest["provenance"]["coverage_percentage"] == 100
    assert manifest["validation_status"] == "passed"
    serialized = manifest_path.read_text(encoding="utf-8")
    assert "D:\\" not in serialized and "202" not in manifest["generation_id"]
    for artifact_name, metadata in manifest["artifacts"].items():
        path = generation / artifact_name
        frame = pl.read_parquet(path)
        assert metadata["row_count"] == frame.height
        assert metadata["column_count"] == frame.width
        assert metadata["sha256"] == sha256(path.read_bytes()).hexdigest()
        assert metadata["schema"] == [
            {"name": name, "type": str(dtype)} for name, dtype in frame.schema.items()
        ]


@pytest.mark.parametrize(
    "failure_injection",
    [
        "after_staging_before_validation",
        "after_validation_before_commit",
        "during_publication_before_pointer",
    ],
)
def test_injected_failure_preserves_the_prior_generation(
    tmp_path: Path, failure_injection: str
) -> None:
    _materialize(tmp_path)
    prior = resolve_m3_current_generation(tmp_path)
    before = _hashes(prior)
    with pytest.raises(RuntimeError, match="injected failure"):
        _materialize(tmp_path, failure_injection)
    assert resolve_m3_current_generation(tmp_path) == prior
    assert _hashes(prior) == before


def test_replay_is_byte_identical_and_preserves_all_accepted_artifact_bytes(tmp_path: Path) -> None:
    _materialize(tmp_path)
    first_generation = resolve_m3_current_generation(tmp_path)
    first = _hashes(first_generation)
    first_manifest = json.loads((first_generation / "m3_phase2_manifest.json").read_text())
    _materialize(tmp_path)
    second_generation = resolve_m3_current_generation(tmp_path)
    second = _hashes(second_generation)
    second_manifest = json.loads((second_generation / "m3_phase2_manifest.json").read_text())
    assert first_generation == second_generation
    assert first == second
    assert first_manifest["generation_id"] == second_manifest["generation_id"]
    for name, expected in ACCEPTED_CHECKSUMS.items():
        assert sha256((OUTPUT / name).read_bytes()).hexdigest() == expected
        assert sha256((second_generation / name).read_bytes()).hexdigest() == expected
