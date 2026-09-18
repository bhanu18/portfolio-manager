"""
Import trades from a broker export into the portfolio database.

Supports Yahoo Finance today; Dime and Webull TH plug in as extra parsers under
service/imports/. The broker is auto-detected from the file's columns unless --broker
is given. Imports are idempotent: re-running the same file updates matching trades
rather than inserting duplicates.

Usage:
    python scripts/import_trades.py export.csv [--broker yahoo] [--group-id 1] [--dry-run]
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.session import AsyncSessionLocal, engine
from service.imports.base import ParseError
from service.imports.pipeline import ImportError_, ImportResult, import_trades
from service.imports.registry import PARSERS, parse_file


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Broker export file (.csv or .xlsx)")
    parser.add_argument(
        "--broker",
        choices=sorted(PARSERS),
        help="Skip auto-detection and use this parser",
    )
    parser.add_argument("--group-id", type=int, default=1, help="Group that owns these trades")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would change without writing"
    )
    return parser.parse_args(argv)


def report(result: ImportResult) -> None:
    prefix = "[dry-run] " if result.dry_run else ""
    if result.assets_created:
        verb = "would create" if result.dry_run else "created"
        print(
            f"{prefix}{verb} {len(result.assets_created)} asset(s): "
            f"{', '.join(result.assets_created)}"
        )
    for change in result.changes:
        print(f"  update {change}")
    for warning in result.warnings:
        print(f"  WARNING: {warning}")
    print(
        f"{prefix}{result.broker}: inserted {result.inserted}, updated {result.updated}, "
        f"unchanged {result.unchanged}, skipped {result.skipped}"
    )


async def run(args: argparse.Namespace) -> None:
    try:
        parser, rows = parse_file(args.path, args.broker)
    except (ParseError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from None

    print(f"Detected {parser.label}: {len(rows)} row(s)")
    try:
        async with AsyncSessionLocal() as db:
            result = await import_trades(
                db,
                rows,
                parser.code,
                args.group_id,
                args.dry_run,
                ref_prefix=getattr(parser, "ref_prefix", parser.code),
            )
        report(result)
    except ImportError_ as exc:
        raise SystemExit(str(exc)) from None
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
