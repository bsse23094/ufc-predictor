"""Make workspace packages importable in source-tree test runs."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for source_root in (ROOT / "apps/api/src", ROOT / "services/ml/src"):
    sys.path.insert(0, str(source_root))
