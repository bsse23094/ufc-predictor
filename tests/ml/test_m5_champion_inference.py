"""M5 Phase 1 immutable champion loading and symmetric inference tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ufc_predictor.inference.m5_champion import (
    DEFAULT_BUNDLE_PATH,
    ChampionRuntime,
    ChampionRuntimeError,
    FeatureMaterializationUnavailable,
    write_m5_runtime_artifacts,
)


@pytest.fixture(scope="module")
def runtime() -> ChampionRuntime:
    return ChampionRuntime()


def _known_request(runtime: ChampionRuntime) -> tuple[str, str, date]:
    row = next(iter(runtime._rows.values()))
    return (
        str(row["canonical_fighter_a_id"]),
        str(row["canonical_fighter_b_id"]),
        row["fight_date"],
    )


def test_bundle_contract_and_ordered_inference_are_deterministic(runtime: ChampionRuntime) -> None:
    fighter_a, fighter_b, fight_date = _known_request(runtime)
    first = runtime.predict(fighter_a, fighter_b, fight_date)
    second = runtime.predict(fighter_a, fighter_b, fight_date)

    assert len(runtime.feature_columns) == 167
    assert first == second
    assert 0.0 <= first.probability_a <= 1.0
    assert first.probability_a + first.probability_b == pytest.approx(1.0, abs=1e-12)
    assert first.confidence["default_full_coverage"]["covered"] is True


def test_swapped_request_complements_probability_and_preserves_coverage(
    runtime: ChampionRuntime,
) -> None:
    fighter_a, fighter_b, fight_date = _known_request(runtime)
    forward = runtime.predict(fighter_a, fighter_b, fight_date)
    swapped = runtime.predict(fighter_b, fighter_a, fight_date)

    assert forward.probability_a == pytest.approx(swapped.probability_b, abs=1e-12)
    assert forward.probability_b == pytest.approx(swapped.probability_a, abs=1e-12)
    assert forward.confidence == swapped.confidence
    assert forward.predicted_winner_id == swapped.predicted_winner_id


def test_invalid_or_unavailable_history_fails_closed(runtime: ChampionRuntime) -> None:
    fighter_a, _, fight_date = _known_request(runtime)
    with pytest.raises(FeatureMaterializationUnavailable):
        runtime.predict(fighter_a, fighter_a, fight_date)
    with pytest.raises(FeatureMaterializationUnavailable):
        runtime.predict("not-a-canonical-fighter", fighter_a, fight_date)


def test_corrupted_bundle_is_rejected_before_model_loading(tmp_path: Path) -> None:
    corrupted = tmp_path / "bundle.json"
    corrupted.write_bytes(DEFAULT_BUNDLE_PATH.read_bytes() + b"corrupt")

    with pytest.raises(ChampionRuntimeError, match="hash"):
        ChampionRuntime(corrupted)


def test_runtime_artifacts_are_deterministic_and_do_not_copy_model(
    runtime: ChampionRuntime, tmp_path: Path
) -> None:
    first = write_m5_runtime_artifacts(runtime, tmp_path)
    second = write_m5_runtime_artifacts(runtime, tmp_path)

    assert first == second
    assert (
        tmp_path / "m3-74eeb9b7f49b5adca45e461a" / "m5_champion_runtime_contract.json"
    ).is_file()
    assert not list((tmp_path / "m3-74eeb9b7f49b5adca45e461a").glob("*.joblib"))
