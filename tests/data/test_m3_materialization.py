from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from ufc_predictor.m3_reviewer_packet import (
    LegacyAuthorityMigrationReport,
    ReviewerDecisionImportError,
    migrate_m3_legacy_authorities,
)

ROOT = Path(__file__).parents[2]
REVIEWS = ROOT / "data/quarantine/reviews"


def _migrate_legacy_authorities(
    *, review_dir: Path, output_dir: Path
) -> LegacyAuthorityMigrationReport:
    return migrate_m3_legacy_authorities(
        legacy_identity_csv=review_dir / "m3/m3_identity_decisions.csv",
        legacy_taxonomy_csv=review_dir / "m3/m3_taxonomy_decisions.csv",
        legacy_packet_dir=review_dir / "m3",
        v6_packet_dir=review_dir / "m3-corrections-v6",
        output_dir=output_dir,
    )


def test_legacy_authority_migration_accepts_only_current_approved_rows(tmp_path: Path) -> None:
    report = _migrate_legacy_authorities(review_dir=REVIEWS, output_dir=tmp_path)

    rows = [
        json.loads(line) for line in report.ledger_path.read_text(encoding="utf-8").splitlines()
    ]
    assert (
        report.accepted_identity_count,
        report.accepted_taxonomy_count,
        report.retired_or_superseded_count,
        report.rejected_count,
    ) == (49, 53, 12, 0)
    assert len(rows) == 102
    assert {row["authority_kind"] for row in rows} == {"identity", "taxonomy"}
    assert "M3-ID-45CDDFCF91DA" not in {row["legacy_review_id"] for row in rows}


def test_stale_legacy_evidence_is_rejected(tmp_path: Path) -> None:
    copied = tmp_path / "reviews"
    shutil.copytree(REVIEWS, copied)
    path = copied / "m3/m3_identity_decisions.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = tuple(reader.fieldnames or ())
        rows = list(reader)
    rows[0]["representative_evidence"] = "tampered"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(ReviewerDecisionImportError, match="stale source evidence"):
        _migrate_legacy_authorities(review_dir=copied, output_dir=tmp_path)
