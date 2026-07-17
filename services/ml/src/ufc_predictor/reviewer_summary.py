"""Compact, non-mutating reviewer summaries for identity and taxonomy queues."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, cast


def reviewer_markdown(items: Iterable[object], *, title: str) -> str:
    """Render queue items without treating a proposal as an approved mapping."""

    rows = [_as_mapping(item) for item in items]
    header = (
        f"# {title}\n\n"
        "Proposals are review-only and must not be applied automatically.\n\n"
        "| Review ID | Raw value | Proposed mapping | Affected rows | Confidence | "
        "Evidence | Recommended action |\n"
        "| --- | --- | --- | ---: | --- | --- | --- |\n"
    )
    lines = []
    for index, row in enumerate(rows, start=1):
        raw = _cell(row.get("raw_value"))
        proposed = _cell(row.get("proposed_value"))
        count = _cell(row.get("affected_count"))
        confidence = _cell(row.get("confidence"))
        evidence = _cell(row.get("reason"))
        example_values = row.get("examples", ())
        examples = _cell(
            ", ".join(str(value) for value in example_values)
            if isinstance(example_values, tuple)
            else ""
        )
        lines.append(
            f"| review-{index:04d} | {raw} | {proposed} | {count} | {confidence} | "
            f"{evidence}; examples: {examples} | review / approve explicit decision / reject |"
        )
    return header + "\n".join(lines) + "\n"


def write_reviewer_markdown_once(path: Path, *, items: Iterable[object], title: str) -> Path:
    """Write a deterministic, non-overwriting reviewer artifact."""

    content = reviewer_markdown(items, title=title)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise RuntimeError(f"reviewer artifact already exists with different content: {path}")
        return path
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _as_mapping(item: object) -> dict[str, object]:
    if not is_dataclass(item):
        raise TypeError("reviewer summary items must be dataclasses")
    return cast(dict[str, object], asdict(cast(Any, item)))


def _cell(value: object) -> str:
    return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")
