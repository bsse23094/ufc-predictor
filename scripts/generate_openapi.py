"""Export the authoritative FastAPI OpenAPI document for generated web types."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from ufc_api.main import create_app  # noqa: E402


def main() -> int:
    output = ROOT / "packages/shared-types/openapi.json"
    document = create_app().openapi()
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
