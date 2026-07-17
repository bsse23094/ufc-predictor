"""Reject tracked secrets, data, and model artifacts before CI proceeds."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_TRACKED_BYTES = 1_048_576
FORBIDDEN_SUFFIXES = {".pkl", ".pickle", ".joblib", ".onnx", ".pt", ".pth", ".cbm", ".duckdb"}
SECRET_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"AKIA",
    b"gh" + b"p_",
    b"github" + b"_pat_",
)
ALLOWED_DATA_FILES = {
    Path("data/README.md"),
    Path("data/incoming/.gitkeep"),
    Path("data/raw/.gitkeep"),
    Path("data/quarantine/.gitkeep"),
    Path("data/interim/.gitkeep"),
    Path("data/processed/.gitkeep"),
}
ALLOWED_MODEL_FILES = {Path("models/README.md"), Path("models/.gitkeep")}


def tracked_paths() -> list[Path]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True)
    return [Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]


def main() -> int:
    failures: list[str] = []
    for relative_path in tracked_paths():
        path = ROOT / relative_path
        if relative_path.parts[0:1] == ("data",) and relative_path not in ALLOWED_DATA_FILES:
            failures.append(f"tracked data file: {relative_path}")
        if relative_path.parts[0:1] == ("models",) and relative_path not in ALLOWED_MODEL_FILES:
            failures.append(f"tracked model artifact: {relative_path}")
        if relative_path.suffix.lower() in FORBIDDEN_SUFFIXES:
            failures.append(f"forbidden artifact format: {relative_path}")
        if not path.is_file():
            continue
        if path.stat().st_size > MAX_TRACKED_BYTES:
            failures.append(f"tracked file exceeds {MAX_TRACKED_BYTES} bytes: {relative_path}")
        contents = path.read_bytes()
        if any(marker in contents for marker in SECRET_MARKERS):
            failures.append(f"possible secret marker in: {relative_path}")

    if failures:
        print("Repository policy check failed:", file=sys.stderr)
        print("\n".join(f"- {failure}" for failure in failures), file=sys.stderr)
        return 1
    print("Repository policy check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
