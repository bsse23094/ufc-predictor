from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from ufc_predictor.m3_reviewer_packet import (
    ReviewerDecisionImportError,
    ReviewerPacketItem,
    generate_m3_correction_packet,
    generate_m3_reviewer_packet,
    import_m3_reviewer_decisions,
    prepare_m3_v6_reviewer_package,
    profile_ufc_datalab_round_semantics,
    validate_m3_v6_reviewer_package,
)


def test_packet_deduplicates_queues_preserves_bruno_and_compacts_outcomes(tmp_path: Path) -> None:
    inputs = _packet_inputs(tmp_path)

    report = generate_m3_reviewer_packet(**inputs, output_dir=tmp_path / "packet")

    assert report.identity_count == 2
    assert report.taxonomy_count == 1
    assert report.outcome_count == 1
    packet = report.packet_path.read_text(encoding="utf-8")
    assert "preserve separate Flyweight and Middleweight Bruno Silva identities" in packet
    identity = _rows(report.identity_csv_path)
    alias = next(row for row in identity if row["category"] == "identity.alias_candidate")
    assert alias["affected_row_count"] == "5"
    assert "ultimate: Kai Kara-France" in alias["source_values"]
    assert "ufc-datalab: KAI KARA-FRANCE" in alias["source_values"]
    outcome = _rows(report.outcome_csv_path)[0]
    assert outcome["category"] == "outcome.no_contest_vs_winner"
    assert "ultimate: u-1" in outcome["source_values"]
    assert "ufc-datalab: d-1" in outcome["source_values"]
    assert outcome["reviewer_decision"] == ""
    assert outcome["reviewer_notes"] == ""


def test_decision_import_validates_missing_duplicate_contradictory_and_stale_rows(
    tmp_path: Path,
) -> None:
    inputs = _packet_inputs(tmp_path)
    packet_dir = tmp_path / "packet"
    report = generate_m3_reviewer_packet(**inputs, output_dir=packet_dir)
    decision_file = tmp_path / "completed.csv"
    rows = _rows(report.identity_csv_path)
    _complete(rows[0])
    _write_rows(decision_file, rows)

    first = import_m3_reviewer_decisions(packet_dir=packet_dir, decision_files=(decision_file,))
    replay = import_m3_reviewer_decisions(packet_dir=packet_dir, decision_files=(decision_file,))
    assert first.applied == 1 and first.replayed == 0
    assert replay.applied == 0 and replay.replayed == 1

    missing = dict(rows[1])
    missing["reviewer_decision"] = "approve"
    with pytest.raises(ReviewerDecisionImportError, match="missing reviewer"):
        import_m3_reviewer_decisions(
            packet_dir=packet_dir, decision_files=(_single_row(tmp_path, "missing.csv", missing),)
        )

    duplicate = dict(rows[1])
    _complete(duplicate)
    with pytest.raises(ReviewerDecisionImportError, match="duplicate decision"):
        import_m3_reviewer_decisions(
            packet_dir=packet_dir,
            decision_files=(_multi_row(tmp_path, "duplicate.csv", (duplicate, duplicate)),),
        )

    contradictory = dict(rows[0])
    _complete(contradictory, decision="reject")
    with pytest.raises(ReviewerDecisionImportError, match="contradictory"):
        import_m3_reviewer_decisions(
            packet_dir=packet_dir,
            decision_files=(_single_row(tmp_path, "contradictory.csv", contradictory),),
        )

    stale = dict(rows[1])
    _complete(stale)
    stale["source_evidence_sha256"] = "0" * 64
    with pytest.raises(ReviewerDecisionImportError, match="stale source evidence"):
        import_m3_reviewer_decisions(
            packet_dir=packet_dir, decision_files=(_single_row(tmp_path, "stale.csv", stale),)
        )

    unknown = dict(rows[1])
    _complete(unknown)
    unknown["review_id"] = "M3-ID-UNKNOWN"
    with pytest.raises(ReviewerDecisionImportError, match="unknown review ID"):
        import_m3_reviewer_decisions(
            packet_dir=packet_dir, decision_files=(_single_row(tmp_path, "unknown.csv", unknown),)
        )


def test_correction_packet_retires_stale_ids_and_splits_bout_anomalies(tmp_path: Path) -> None:
    ultimate = tmp_path / "ultimate.csv"
    ultimate.write_text(
        "R_fighter,B_fighter,date,weight_class,no_of_rounds,finish_round\n"
        "Alpha,Beta,2020-01-01,Lightweight,4,3\n"
        "Gamma,Delta,2020-01-02,Lightweight,4,3\n",
        encoding="utf-8",
    )
    datalab = tmp_path / "datalab.csv"
    datalab.write_text(
        "red_fighter_name;blue_fighter_name;event_name;event_date;time_format;round\n"
        "ALPHA;BETA;Event;01/01/2020;3 Rnd + OT (5-5-5-5);3\n",
        encoding="utf-8",
    )
    output = tmp_path / "corrections"
    retire = tmp_path / "m3_retired_review_ids.json"

    report = generate_m3_correction_packet(
        ultimate_csv=ultimate,
        datalab_csv=datalab,
        output_dir=output,
        retire_manifest_path=retire,
    )

    assert report.identity_replacement_id == "M3-ID-524AA01602F1"
    assert report.taxonomy_replacement_count == 7
    assert report.bout_review_count == 3
    assert report.proposed_exclusion_count == 1
    assert "M3-ID-45CDDFCF91DA" in retire.read_text(encoding="utf-8")
    rows = _rows(output / "m3_taxonomy_correction_decisions.csv")
    stance = next(row for row in rows if row["category"] == "taxonomy.missing_stance_policy")
    assert stance["recommended_decision"] == "preserve_null or defer"
    bout_rows = _rows(output / "m3_bout_format_decisions.csv")
    assert {row["category"] for row in bout_rows} == {
        "bout_format.special_format",
        "bout_format.cross_source_four_round_confirmation",
        "bout_format.unresolved_cross_source_match",
    }
    _complete(stance, decision="preserve_null")
    decision_file = _single_row(tmp_path, "preserve-null.csv", stance)
    imported = import_m3_reviewer_decisions(packet_dir=output, decision_files=(decision_file,))
    assert imported.applied == 1


def test_round_detector_preserves_normal_and_special_bout_formats(tmp_path: Path) -> None:
    datalab = tmp_path / "rounds.csv"
    records = [
        ("A", "B", "01/01/2020", "3 Rnd (5-5-5)", "3"),
        ("C", "D", "02/01/2020", "3 Rnd (5-5-5)", "1"),
        ("E", "F", "03/01/2020", "3 Rnd (5-5-5)", "2"),
        *(
            (
                f"Five{round_number}",
                f"Opponent{round_number}",
                "04/01/2020",
                "5 Rnd (5-5-5-5-5)",
                str(round_number),
            )
            for round_number in range(1, 6)
        ),
        ("Special", "Format", "05/01/2020", "1 Rnd + 2OT (15-3-3)", "2"),
        ("Impossible", "Round", "06/01/2020", "3 Rnd (5-5-5)", "4"),
    ]
    _write_datalab_rounds(datalab, records)

    profile = profile_ufc_datalab_round_semantics(datalab)

    assert profile.row_count == 10
    assert profile.unique_bout_count == 10
    assert profile.violation_row_count == 1
    assert profile.violation_unique_bout_count == 1
    assert profile.special_format_row_count == 1
    assert profile.special_format_unique_bout_count == 1


def test_round_detector_deduplicates_repeated_bout_records_for_review(tmp_path: Path) -> None:
    ultimate = tmp_path / "ultimate.csv"
    ultimate.write_text(
        "R_fighter,B_fighter,date,weight_class,no_of_rounds,finish_round\n",
        encoding="utf-8",
    )
    datalab = tmp_path / "datalab.csv"
    _write_datalab_rounds(
        datalab,
        (
            ("ALPHA", "BETA", "01/01/2020", "1 Rnd + 2OT (15-3-3)", "2"),
            ("BETA", "ALPHA", "01/01/2020", "1 Rnd + 2OT (15-3-3)", "2"),
        ),
    )
    output = tmp_path / "corrections"
    generate_m3_correction_packet(
        ultimate_csv=ultimate,
        datalab_csv=datalab,
        output_dir=output,
        retire_manifest_path=tmp_path / "retired.json",
    )

    profile = profile_ufc_datalab_round_semantics(datalab)
    rows = _rows(output / "m3_bout_format_decisions.csv")
    assert profile.row_count == 2
    assert profile.unique_bout_count == 1
    assert profile.special_format_row_count == 2
    assert profile.special_format_unique_bout_count == 1
    assert len(rows) == 1
    assert rows[0]["affected_row_count"] == "2"
    assert rows[0]["affected_bout_count"] == "1"


def test_v6_outcome_authorization_preserves_completed_actions_and_evidence(tmp_path: Path) -> None:
    source = tmp_path / "reviewed-outcomes.csv"
    source_rows = _v6_rows(include_corrections=False, complete_corrections=False)
    _write_rows(source, source_rows)

    outcome_path = prepare_m3_v6_reviewer_package(
        outcome_source_csv=source,
        output_dir=tmp_path / "v6",
    )

    authorized = _rows(outcome_path)
    assert len(authorized) == 14
    assert [row["review_id"] for row in authorized] == [row["review_id"] for row in source_rows]
    assert [row["source_evidence_sha256"] for row in authorized] == [
        row["source_evidence_sha256"] for row in source_rows
    ]
    assert {row["reviewer_decision"] for row in authorized} == {
        "confirm_overturned",
        "select_ufc_datalab",
    }


def test_v6_validator_reports_blanks_and_blocks_atomic_import(tmp_path: Path) -> None:
    packet_dir = tmp_path / "v6"
    packet_dir.mkdir()
    rows = _v6_rows(include_corrections=True, complete_corrections=False)
    _write_rows(packet_dir / "m3_identity_correction_decisions.csv", rows[:1])
    _write_rows(packet_dir / "m3_taxonomy_correction_decisions.csv", rows[1:8])
    _write_rows(packet_dir / "m3_bout_format_decisions.csv", rows[8:20])
    _write_rows(packet_dir / "m3_outcome_decisions.csv", rows[20:])

    report = validate_m3_v6_reviewer_package(packet_dir)

    assert report.total_required_count == 34
    assert report.completed_count == 14
    assert report.valid_completed_count == 14
    assert report.blank_count == 20
    assert not report.is_complete
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(ReviewerDecisionImportError, match="blank or invalid"):
        import_m3_reviewer_decisions(
            packet_dir=packet_dir,
            decision_files=tuple(sorted(packet_dir.glob("*decisions.csv"))),
            ledger_path=ledger,
            require_complete=True,
        )
    assert not ledger.exists()


def _packet_inputs(tmp_path: Path) -> dict[str, Path]:
    ultimate_identity = tmp_path / "ultimate_identity.md"
    datalab_identity = tmp_path / "datalab_identity.md"
    ultimate_taxonomy = tmp_path / "ultimate_taxonomy.md"
    datalab_taxonomy = tmp_path / "datalab_taxonomy.md"
    _write_queue(
        ultimate_identity,
        (
            (
                "review-0001",
                "Kai Kara-France",
                "Kai Kara-France",
                "2",
                "known punctuation candidate",
            ),
            (
                "review-0002",
                "Bruno Silva",
                "",
                "4",
                "known homonym; separate Flyweight and Middleweight Bruno Silva identities",
            ),
        ),
    )
    _write_queue(
        datalab_identity,
        (("review-0001", "KAI KARA-FRANCE", "kai kara france", "3", "normalization changes case"),),
    )
    _write_queue(
        ultimate_taxonomy,
        (("review-0001", " Catch Weight ", "Catch Weight", "2", "division naming"),),
    )
    _write_queue(
        datalab_taxonomy,
        (("review-0001", " Catch Weight ", "Catch Weight", "1", "division naming"),),
    )
    conflicts = tmp_path / "conflicts.jsonl"
    conflicts.write_text(json.dumps(_outcome_conflict()) + "\n", encoding="utf-8")
    return {
        "ultimate_identity_queue": ultimate_identity,
        "datalab_identity_queue": datalab_identity,
        "ultimate_taxonomy_queue": ultimate_taxonomy,
        "datalab_taxonomy_queue": datalab_taxonomy,
        "residual_outcome_conflicts": conflicts,
    }


def _write_queue(path: Path, rows: tuple[tuple[str, str, str, str, str], ...]) -> None:
    content = [
        "# queue",
        "| Review ID | Raw value | Proposed mapping | Affected rows | Confidence | Evidence | "
        "Recommended action |",
        "| --- | --- | --- | ---: | --- | --- | --- |",
    ]
    content.extend(
        f"| {review_id} | {raw} | {proposed} | {count} | review_required | {evidence} | review |"
        for review_id, raw, proposed, count, evidence in rows
    )
    path.write_text("\n".join(content) + "\n", encoding="utf-8")


def _write_datalab_rounds(
    path: Path,
    rows: tuple[tuple[str, str, str, str, str], ...] | list[tuple[str, str, str, str, str]],
) -> None:
    content = [
        "red_fighter_name;blue_fighter_name;event_name;event_date;time_format;round",
        *(
            f"{red};{blue};Event;{event_date};{time_format};{finish_round}"
            for red, blue, event_date, time_format, finish_round in rows
        ),
    ]
    path.write_text("\n".join(content) + "\n", encoding="utf-8")


def _v6_rows(*, include_corrections: bool, complete_corrections: bool) -> list[dict[str, str]]:
    categories = (
        (["identity.consolidated_alias_identity"] if include_corrections else [])
        + (["taxonomy.division_exact_normalization"] if include_corrections else [])
        + (["taxonomy.finish_method_exact_mapping"] * 5 if include_corrections else [])
        + (["taxonomy.missing_stance_policy"] if include_corrections else [])
        + (["bout_format.special_format"] * 9 if include_corrections else [])
        + (["bout_format.cross_source_four_round_confirmation"] if include_corrections else [])
        + (["bout_format.unresolved_cross_source_match"] * 2 if include_corrections else [])
        + ["outcome.no_contest_vs_winner"] * 12
        + ["outcome.winner_disagreement"] * 2
    )
    rows: list[dict[str, str]] = []
    for index, category in enumerate(categories, start=1):
        item = ReviewerPacketItem(
            review_id=f"M3-TEST-{index:03d}",
            category=category,
            source_values=(f"source-value-{index}",),
            proposed_canonical_value_or_action=f"proposal-{index}",
            affected_row_count=1,
            affected_bout_count=1,
            representative_evidence=f"evidence-{index}",
            confidence="review_required",
            recommended_decision="review",
        )
        row = item.csv_row()
        is_outcome = category.startswith("outcome.")
        if is_outcome or complete_corrections:
            if category == "outcome.no_contest_vs_winner":
                decision = "confirm_overturned"
            elif category == "outcome.winner_disagreement":
                decision = "select_ufc_datalab"
            elif category == "taxonomy.missing_stance_policy":
                decision = "preserve_null"
            elif category == "bout_format.unresolved_cross_source_match":
                decision = "exclude_affected_record"
            else:
                decision = "approve_corrected_mapping"
            _complete(row, decision=decision)
        rows.append(row)
    return rows


def _outcome_conflict() -> dict[str, object]:
    return {
        "left_source": {
            "source": "ultimate",
            "source_record_key": "u-1",
            "fight_date": "2020-01-01",
            "red_name": "Alpha",
            "blue_name": "Beta",
            "outcome": "Red",
            "method": "Decision",
        },
        "right_source": {
            "source": "ufc-datalab",
            "source_record_key": "d-1",
            "fight_date": "2020-01-01",
            "red_name": "ALPHA",
            "blue_name": "BETA",
            "outcome": "no_contest",
            "method": "Overturned",
        },
        "comparisons": [
            {
                "field": "outcome",
                "left_value": "Red",
                "right_value": "no_contest",
                "left_normalized": "alpha",
                "right_normalized": "no_contest",
            }
        ],
    }


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _complete(row: dict[str, str], *, decision: str = "approve") -> None:
    row["reviewer_decision"] = decision
    row["reviewer"] = "steward@example.test"
    row["decision_timestamp"] = "2026-07-18T12:00:00+00:00"
    row["reviewer_notes"] = "Reviewed source evidence."


def _single_row(tmp_path: Path, name: str, row: dict[str, str]) -> Path:
    return _multi_row(tmp_path, name, (row,))


def _multi_row(tmp_path: Path, name: str, rows: tuple[dict[str, str], ...]) -> Path:
    path = tmp_path / name
    _write_rows(path, list(rows))
    return path


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
