"""Fast, dependency-free architecture and local Markdown-link validation."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]*\]\(([^)]+)\)")
REQUIRED = (
    "apps/api/src/ufc_api/main.py",
    "apps/web/app/page.tsx",
    "services/ml/src/ufc_predictor/cli.py",
    "packages/shared-types/openapi.json",
    "packages/ui/src/tokens.css",
    "compose.yaml",
    "justfile",
    "data/raw/.gitkeep",
    "models/.gitkeep",
)


def validate_required_paths() -> list[str]:
    return [path for path in REQUIRED if not (ROOT / path).is_file()]


def validate_markdown_links() -> list[str]:
    failures: list[str] = []
    for document in [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]:
        text = document.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            target = match.group(1).strip().strip("<>")
            if (
                not target
                or "://" in target
                or target.startswith("#")
                or target.startswith("mailto:")
            ):
                continue
            target_path = target.split("#", maxsplit=1)[0]
            if not target_path:
                continue
            if not (document.parent / target_path).exists():
                failures.append(f"{document.relative_to(ROOT)} -> {target}")
    return failures


def main() -> int:
    failures = [f"missing required path: {path}" for path in validate_required_paths()]
    failures.extend(f"broken local link: {link}" for link in validate_markdown_links())
    if failures:
        print("Architecture/docs check failed:", file=sys.stderr)
        print("\n".join(f"- {failure}" for failure in failures), file=sys.stderr)
        return 1
    print("Architecture/docs check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
