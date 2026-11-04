"""Offline entry point; intentionally separate from the operational CLI."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

from .evaluation import ForecastLedger, evaluate, timestamp


def _records(path: str) -> list[dict]:
    values = []
    with Path(path).open(encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise TypeError("JSON record must be an object")
                values.append(record)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
    if not values:
        raise ValueError("input JSONL contains no records")
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline solar forecast evidence and evaluation")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Create and score deterministic synthetic inputs")
    demo.add_argument("--directory", required=True, help="New output directory (must not exist)")
    for command in ("import-forecasts", "import-actuals"):
        sub = commands.add_parser(command, help="Append JSONL records; conflicting retries fail")
        sub.add_argument("--ledger", required=True)
        sub.add_argument(
            "--input", required=True, help="JSONL using the documented v1 record schema"
        )
    sub = commands.add_parser(
        "evaluate", help="Compare a fixed chronological plan without refitting"
    )
    sub.add_argument("--ledger", required=True)
    sub.add_argument("--plan", required=True)
    sub.add_argument(
        "--as-of", required=True, help="Aware ISO timestamp: evidence availability cutoff"
    )
    sub.add_argument("--phase", choices=("validation", "test"), default="test")
    sub.add_argument(
        "--allow-retrospective",
        action="store_true",
        help="Include explicitly labeled archive/synthetic forecasts",
    )
    sub.add_argument("--output", help="Create report JSON; refuses to overwrite existing evidence")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            from .evaluation_demo import create_demo

            result = create_demo(args.directory)
        elif args.command.startswith("import-"):
            with ForecastLedger(args.ledger) as ledger:
                result = ledger.append(args.command.removeprefix("import-"), _records(args.input))
        else:
            as_of = timestamp(args.as_of, "as_of")
            if as_of > datetime.now(UTC):
                raise ValueError("as_of cannot be in the future")
            with ForecastLedger(args.ledger, readonly=True) as ledger:
                result = evaluate(
                    ledger,
                    json.loads(Path(args.plan).read_text()),
                    as_of=as_of,
                    phase=args.phase,
                    allow_retrospective=args.allow_retrospective,
                )
        rendered = json.dumps(result, indent=2, allow_nan=False)
        if args.command == "evaluate" and args.output:
            with Path(args.output).open("x", encoding="utf-8") as output:
                output.write(rendered + "\n")
        print(rendered)
        return 3 if result.get("status") == "insufficient_data" else 0
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, ZoneInfoNotFoundError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
