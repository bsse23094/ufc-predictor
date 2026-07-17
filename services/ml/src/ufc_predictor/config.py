"""Shared ML-side configuration with no source enabled by default."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MlSettings:
    """Local paths are configuration only; source commands remain audit-gated."""

    raw_root: Path = Path("data/raw")
    interim_root: Path = Path("data/interim")
    processed_root: Path = Path("data/processed")
    enabled_sources: tuple[str, ...] = ()

    def assert_no_sources_enabled(self) -> None:
        """Prevent accidental fetching before the source-policy milestone is approved."""

        if self.enabled_sources:
            raise RuntimeError("no source may be enabled before the completed M2 source audit")
