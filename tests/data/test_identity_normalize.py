from __future__ import annotations

import pytest

from ufc_predictor.identity.normalize import (
    candidate_fighter_aliases,
    group_candidate_aliases,
    normalize_fighter_alias,
)

RAW_SHA = "a" * 64


def test_normalization_preserves_observed_unicode_alias_and_builds_a_comparison_key() -> None:
    alias = normalize_fighter_alias("  José O'Malley  ")

    assert alias.original_value == "  José O'Malley  "
    assert alias.normalized_value == "jose omalley"


def test_candidate_generation_retains_raw_provenance_without_assigning_an_identity() -> None:
    candidates = candidate_fighter_aliases(
        source_identifier="kaggle-ultimate-ufc-dataset",
        rows=(
            {
                "source_record_key": "fight-001",
                "source_raw_sha256": RAW_SHA,
                "fighter_one_source_name": "José O'Malley",
                "fighter_two_source_name": "Beta Fighter",
            },
        ),
    )

    assert [
        (candidate.source_field, candidate.alias.original_value) for candidate in candidates
    ] == [
        ("fighter_one_source_name", "José O'Malley"),
        ("fighter_two_source_name", "Beta Fighter"),
    ]
    assert {candidate.source_raw_sha256 for candidate in candidates} == {RAW_SHA}
    assert all(not hasattr(candidate, "fighter_id") for candidate in candidates)


def test_equal_normalized_names_remain_unresolved_candidate_occurrences() -> None:
    candidates = candidate_fighter_aliases(
        source_identifier="kaggle-ultimate-ufc-dataset",
        rows=(
            {
                "source_record_key": "fight-001",
                "source_raw_sha256": RAW_SHA,
                "fighter_one_source_name": "Jose Aldo",
                "fighter_two_source_name": "Alpha Fighter",
            },
            {
                "source_record_key": "fight-002",
                "source_raw_sha256": "b" * 64,
                "fighter_one_source_name": "José Aldo",
                "fighter_two_source_name": "Beta Fighter",
            },
        ),
    )

    grouped = group_candidate_aliases(candidates)

    assert [candidate.source_record_key for candidate in grouped["jose aldo"]] == [
        "fight-001",
        "fight-002",
    ]
    assert len(grouped["jose aldo"]) == 2


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            {
                "source_record_key": "fight-001",
                "source_raw_sha256": RAW_SHA,
                "fighter_one_source_name": "Alpha Fighter",
                "fighter_two_source_name": "",
            },
            "fighter_two_source_name",
        ),
        (
            {
                "source_record_key": "fight-001",
                "source_raw_sha256": "not-a-sha",
                "fighter_one_source_name": "Alpha Fighter",
                "fighter_two_source_name": "Beta Fighter",
            },
            "source_raw_sha256",
        ),
    ],
)
def test_candidate_generation_rejects_incomplete_or_untraceable_interim_rows(
    row: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        candidate_fighter_aliases(source_identifier="fixture-source", rows=(row,))
