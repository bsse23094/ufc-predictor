"""Guarded task helpers for commands whose owning milestone has not started."""

from __future__ import annotations

import argparse
import sys


def command_unavailable(command: str) -> int:
    print(
        f"{command} is unavailable: its owning architecture milestone has not passed its gate.",
        file=sys.stderr,
    )
    return 3


def main() -> int:
    parser = argparse.ArgumentParser(description="UFC Predictor guarded task runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("seed-test-data")

    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("source")
    ingest.add_argument("mode", choices=("full", "incremental", "backfill", "dry-run"))
    ingest.add_argument("range")

    unavailable = subparsers.add_parser("unavailable")
    unavailable.add_argument("operation")
    unavailable.add_argument("arguments", nargs="*")

    restore = subparsers.add_parser("restore-drill")
    restore.add_argument("environment")

    args = parser.parse_args()
    if args.command == "ingest":
        if args.mode == "backfill" and args.range.strip().lower() in {"all", "*", "unbounded"}:
            parser.error("backfill range must be explicit and bounded")
        return command_unavailable("ingest")
    if args.command == "restore-drill":
        if args.environment not in {"local", "staging", "test"}:
            parser.error("restore-drill is restricted to local, test, or staging")
        return command_unavailable("restore-drill")
    return command_unavailable(args.command if args.command != "unavailable" else args.operation)


if __name__ == "__main__":
    raise SystemExit(main())
