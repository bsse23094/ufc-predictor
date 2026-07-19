from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path

import polars as pl
import pytest

from ufc_predictor.m3_materialization import (
    SUPPLEMENTAL_LEDGER_IDENTIFIER,
    V6_LEDGER_IDENTIFIER,
    AuthorityIndex,
    AuthorityRecord,
    _canonical_fighter,
    _fighter,
    identity_context_key,
    load_authority_index,
    materialize_m3_v6,
    resolve_m3_current_generation,
    taxonomy_authority_coverage,
)

ROOT = Path(__file__).parents[2]
V6_DIR = ROOT / "data/quarantine/reviews/m3-corrections-v6"
ULTIMATE = ROOT / "data/incoming/ultimate-ufc-dataset/ufc-master.csv"
DATALAB = ROOT / "data/incoming/ufc-datalab/3268146c05211de9deab8b9b4c0bb4a954815f0b/stats_raw.csv"


def test_authority_index_requires_one_matching_immutable_ledger_record() -> None:
    index = AuthorityIndex((AuthorityRecord("M3-ID-1", "legacy", {"review_id": "M3-ID-1"}),))
    assert index.resolve("M3-ID-1", "legacy").authority_id == "M3-ID-1"
    with pytest.raises(ValueError, match="zero"):
        index.resolve("M3-ID-UNKNOWN", "legacy")
    with pytest.raises(ValueError, match="mismatch"):
        index.resolve("M3-ID-1", "v6")


def test_authority_index_rejects_duplicate_ids_across_ledgers() -> None:
    with pytest.raises(ValueError, match="multiple"):
        AuthorityIndex(
            (AuthorityRecord("M3-ID-1", "legacy", {}), AuthorityRecord("M3-ID-1", "v6", {}))
        )


def test_real_immutable_ledgers_resolve_only_their_authoritative_ids() -> None:
    index = load_authority_index(V6_DIR)
    assert index.record_count == 136
    assert index.count_for_ledger(V6_LEDGER_IDENTIFIER) == 34
    assert index.count_for_ledger(SUPPLEMENTAL_LEDGER_IDENTIFIER) == 102
    assert index.resolve("M3-ID-524AA01602F1", V6_LEDGER_IDENTIFIER).payload[
        "reviewer_decision"
    ] == ("approve_corrected_mapping")
    assert (
        index.resolve("M3-ID-8956BE143EA0", SUPPLEMENTAL_LEDGER_IDENTIFIER).payload[
            "authority_kind"
        ]
        == "identity"
    )


def test_bruno_silva_context_is_the_reviewed_division_homonym_rule() -> None:
    flyweight = identity_context_key("Bruno Silva", "Flyweight Bout")
    middleweight = identity_context_key("Bruno Silva", "Middleweight Bout")
    bantamweight = identity_context_key("Bruno Silva", "Bantamweight")
    assert flyweight == "bruno silva|flyweight"
    assert middleweight == "bruno silva|middleweight"
    assert bantamweight == "bruno silva|bantamweight"
    assert flyweight != middleweight


def test_roldan_punctuation_aliases_share_exact_normalized_context() -> None:
    assert identity_context_key("Roldan Sangcha-an", "") == identity_context_key(
        "Roldan Sangcha'an", ""
    )
    assert (
        _canonical_fighter("Roldan Sangcha-an", "")[0]
        == _canonical_fighter("Roldan Sangcha'an", "")[0]
    )
    assert _fighter("Roldan Sangcha-an", "")[0] != _fighter("Roldan Sangcha'an", "")[0]


def test_missing_stance_is_a_reviewed_null_policy_not_an_inferred_taxonomy(tmp_path: Path) -> None:
    materialize_m3_v6(
        ultimate_csv=ULTIMATE, datalab_csv=DATALAB, v6_dir=V6_DIR, output_dir=tmp_path
    )
    taxonomy = pl.read_parquet(
        resolve_m3_current_generation(tmp_path) / "m3_taxonomy_authorities.parquet"
    )
    stance = taxonomy.filter(pl.col("field_name") == "stance").row(0, named=True)
    assert stance["raw_value"] is None and stance["canonical_value"] is None
    assert stance["is_null_policy"] is True
    assert stance["authority_id"] == "M3-TAX-B61B2075D451"
    assert stance["ledger_identifier"] == V6_LEDGER_IDENTIFIER


def test_taxonomy_authority_coverage_is_exact_and_scope_unique(tmp_path: Path) -> None:
    coverage = taxonomy_authority_coverage(
        ultimate_csv=ULTIMATE, datalab_csv=DATALAB, v6_dir=V6_DIR
    )
    classifications = Counter(authority.classification for authority in coverage)
    assert len(coverage) == 60
    assert classifications == {
        "active_and_applicable": 44,
        "active_but_not_applicable_to_retained_approved_source_fields": 16,
    }
    materialize_m3_v6(
        ultimate_csv=ULTIMATE, datalab_csv=DATALAB, v6_dir=V6_DIR, output_dir=tmp_path
    )
    emitted = pl.read_parquet(
        resolve_m3_current_generation(tmp_path) / "m3_taxonomy_authorities.parquet"
    )
    active = [
        authority for authority in coverage if authority.classification == "active_and_applicable"
    ]
    inactive = {authority.authority_id for authority in coverage if authority not in active}
    assert emitted.height == len(active) == 44
    assert Counter(emitted["authority_id"].to_list()) == Counter(
        authority.authority_id for authority in active
    )
    assert not inactive.intersection(emitted["authority_id"].to_list())
    assert (
        not emitted.select(["source_name", "source_schema_version", "field_name", "raw_value"])
        .is_duplicated()
        .any()
    )
    index = load_authority_index(V6_DIR)
    assert all(
        index.resolve(row["authority_id"], row["ledger_identifier"]).authority_id
        == row["authority_id"]
        for row in emitted.iter_rows(named=True)
    )
    stance = emitted.filter(pl.col("authority_id") == "M3-TAX-B61B2075D451").row(0, named=True)
    assert stance["raw_value"] is None and stance["canonical_value"] is None
    assert stance["is_null_policy"] is True


def test_phase2a_replay_is_byte_identical_and_preserves_bruno_context(tmp_path: Path) -> None:
    raw_before = sha256(ULTIMATE.read_bytes() + DATALAB.read_bytes()).hexdigest()
    materialize_m3_v6(
        ultimate_csv=ULTIMATE, datalab_csv=DATALAB, v6_dir=V6_DIR, output_dir=tmp_path
    )
    first_generation = resolve_m3_current_generation(tmp_path)
    first = {
        path.name: sha256(path.read_bytes()).hexdigest()
        for path in sorted(first_generation.glob("*.parquet"))
    }
    materialize_m3_v6(
        ultimate_csv=ULTIMATE, datalab_csv=DATALAB, v6_dir=V6_DIR, output_dir=tmp_path
    )
    second_generation = resolve_m3_current_generation(tmp_path)
    second = {
        path.name: sha256(path.read_bytes()).hexdigest()
        for path in sorted(second_generation.glob("*.parquet"))
    }
    fighters = pl.read_parquet(second_generation / "m3_canonical_fighters.parquet")
    aliases = pl.read_parquet(second_generation / "m3_canonical_fighter_aliases.parquet")
    groups = pl.read_parquet(second_generation / "m3_semantic_bout_groups.parquet")
    bruno = fighters.filter(pl.col("canonical_display_name") == "Bruno Silva")
    assert bruno.height == 3
    assert set(bruno["identity_context_key"].to_list()) == {
        "bruno silva|flyweight",
        "bruno silva|middleweight",
        "bruno silva|bantamweight",
    }
    assert set(bruno["authority_id"].to_list()) == {"M3-ID-8956BE143EA0"}
    roldan = aliases.filter(pl.col("raw_fighter_name").str.to_lowercase().str.contains("roldan"))
    assert roldan.height == 4
    assert roldan["canonical_fighter_id"].n_unique() == 1
    assert set(roldan["authority_id"].to_list()) == {"M3-ID-524AA01602F1"}
    assert set(aliases["canonical_fighter_id"]).issubset(set(fighters["canonical_fighter_id"]))
    assert set(aliases["canonical_bout_id"]) == set(groups["canonical_bout_id"]).intersection(
        set(aliases["canonical_bout_id"])
    )
    assert first == second
    assert sha256(ULTIMATE.read_bytes() + DATALAB.read_bytes()).hexdigest() == raw_before
