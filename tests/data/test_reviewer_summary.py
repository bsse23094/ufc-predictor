from __future__ import annotations

from pathlib import Path

from ufc_predictor.identity.review_queue import build_identity_review_queue
from ufc_predictor.reviewer_summary import reviewer_markdown, write_reviewer_markdown_once


def test_reviewer_summary_is_compact_review_only_and_separates_bruno_silva(tmp_path: Path) -> None:
    queue = build_identity_review_queue(source="fixture", observed_names=("Bruno Silva",))
    content = reviewer_markdown(queue, title="Identity review")
    path = write_reviewer_markdown_once(
        tmp_path / "identity.md", items=queue, title="Identity review"
    )

    assert "Review ID" in content
    assert "separate Flyweight and Middleweight identities" in content
    assert "must not be applied automatically" in content
    assert path.read_text(encoding="utf-8") == content
