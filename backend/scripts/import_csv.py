"""
Import trades from a broker CSV export into the portfolio database.

The import is idempotent: every row gets a deterministic ``source_ref`` and re-running
the same file updates matching trades instead of inserting duplicates.

Expected columns (extra columns are ignored):
    Symbol, Trade Date (YYYYMMDD), Purchase Price, Quantity, Transaction Type (BUY/SELL)
    Commission (optional)

Usage:
    python scripts/import_csv.py portfolio.csv [--group-id 1] [--currency USD] [--dry-run]
"""

import argparse
import asyncio
import hashlib
import math
import os
import sys
from datetime import datetime

import pandas as pd
import yfinance as yf
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.orm_models import Asset, Group, Trade
from db.session import AsyncSessionLocal, engine

REQUIRED_COLUMNS = ["Symbol", "Trade Date", "Purchase Price", "Quantity", "Transaction Type"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="Path to the broker CSV export")
    parser.add_argument("--group-id", type=int, default=1, help="Group that owns these trades")
    parser.add_argument("--currency", default="USD", help="Currency of the traded prices")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would change without writing"
    )
    return parser.parse_args(argv)


def make_source_ref(
    symbol: str, trade_date: str, trade_type: str, group_id: int, occurrence: int
) -> str:
    """Stable id for a CSV row. The same row in the same group always maps to the same ref.

    Quantity and price are deliberately NOT part of the key, so correcting either in the
    broker export updates the existing trade instead of creating a second one. Several fills
    of the same symbol/side on one day are told apart by ``occurrence`` (their order in the
    file), which stays stable as long as the export keeps listing them in the same order.
    """
    raw = f"csv|{group_id}|{symbol.upper()}|{trade_date}|{trade_type}|{occurrence}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def effective_price(price: float, quantity: float, commission: float, trade_type: str) -> float:
    """Fold commission into the unit price: buys cost more, sells net less."""
    if not quantity or not commission:
        return price
    per_unit = commission / quantity
    return price + per_unit if trade_type == "buy" else price - per_unit


def load_rows(csv_path: str, group_id: int, currency: str) -> list[dict]:
    """Read and validate the CSV into normalized trade dicts."""
    df = pd.read_csv(csv_path)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SystemExit(f"CSV is missing required column(s): {', '.join(missing)}")

    df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce")
    df["Purchase Price"] = pd.to_numeric(df["Purchase Price"], errors="coerce")
    df["Commission"] = (
        pd.to_numeric(df.get("Commission"), errors="coerce").fillna(0.0)
        if "Commission" in df.columns
        else 0.0
    )

    before = len(df)
    df = df.dropna(subset=["Symbol", "Trade Date", "Quantity", "Purchase Price"])
    if before != len(df):
        print(f"WARNING: skipped {before - len(df)} row(s) missing symbol, date, quantity or price")

    rows: list[dict] = []
    occurrences: dict[tuple[str, str, str], int] = {}
    for _, row in df.iterrows():
        trade_type = str(row["Transaction Type"]).strip().lower()
        if trade_type not in ("buy", "sell"):
            print(f"WARNING: skipped row with unknown Transaction Type {row['Transaction Type']!r}")
            continue

        raw_date = str(row["Trade Date"]).strip().split(".")[0]
        try:
            trade_date = datetime.strptime(raw_date, "%Y%m%d")  # noqa: DTZ007 - naive, like the column
        except ValueError:
            parsed = pd.to_datetime(row["Trade Date"], errors="coerce")
            if pd.isna(parsed):
                print(f"WARNING: skipped row with unparseable Trade Date {row['Trade Date']!r}")
                continue
            trade_date = parsed.to_pydatetime()

        symbol = str(row["Symbol"]).strip().upper()
        quantity = float(row["Quantity"])
        price = effective_price(
            float(row["Purchase Price"]), quantity, float(row["Commission"]), trade_type
        )
        day_key = (symbol, trade_date.strftime("%Y%m%d"), trade_type)
        occurrence = occurrences.get(day_key, 0)
        occurrences[day_key] = occurrence + 1
        source_ref = make_source_ref(symbol, day_key[1], trade_type, group_id, occurrence)

        rows.append(
            {
                "symbol": symbol,
                "trade_type": trade_type,
                "trade_date": trade_date,
                "quantity": quantity,
                "price_per_unit": round(price, 6),
                "currency": currency,
                "group_id": group_id,
                "source_ref": source_ref,
            }
        )
    return rows


async def ensure_group_exists(db: AsyncSession, group_id: int) -> None:
    """Fail early with a readable message instead of a foreign key error mid-insert."""
    result = await db.execute(select(Group.id).where(Group.id == group_id))
    if result.scalar_one_or_none() is None:
        raise SystemExit(f"Group id {group_id} does not exist. Create it first or pass --group-id.")


async def fetch_existing_assets_map(db: AsyncSession, symbols: list[str]) -> dict[str, int]:
    """{'SYMBOL': asset_id} for symbols already in the database."""
    result = await db.execute(select(Asset.symbol, Asset.id).where(Asset.symbol.in_(symbols)))
    return {row.symbol: row.id for row in result.all()}


def get_yfinance_data_batch(symbols: list[str]) -> dict[str, dict]:
    """Look up name/market/type for symbols that need to be created."""
    if not symbols:
        return {}

    print(f"Fetching asset details for {len(symbols)} new symbol(s)...")
    tickers = yf.Tickers(" ".join(symbols))

    details: dict[str, dict] = {}
    for symbol in symbols:
        try:
            info = tickers.tickers[symbol].info
            details[symbol] = {
                "name": info.get("longName") or symbol,
                "market": info.get("exchange") or "Unknown",
                "type": (info.get("quoteType") or "EQUITY").lower(),
            }
        except Exception:
            print(f"WARNING: could not fetch details for {symbol}; using defaults")
            details[symbol] = {"name": symbol, "market": "Unknown", "type": "stock"}
    return details


async def resolve_assets(db: AsyncSession, symbols: list[str], dry_run: bool) -> dict[str, int]:
    """Return a symbol -> asset_id map, creating assets that don't exist yet."""
    symbol_id_map = await fetch_existing_assets_map(db, symbols)
    missing = [s for s in symbols if s not in symbol_id_map]
    if not missing:
        return symbol_id_map

    if dry_run:
        print(f"[dry-run] would create {len(missing)} asset(s): {', '.join(missing)}")
        # Placeholder ids so the dry run can still report the trade plan.
        return {**symbol_id_map, **{symbol: -1 for symbol in missing}}

    details = get_yfinance_data_batch(missing)
    now = datetime.now()  # noqa: DTZ005 - created_at/updated_at are naive columns
    db.add_all(
        [
            Asset(
                symbol=symbol,
                name=details[symbol]["name"],
                market=details[symbol]["market"],
                type=details[symbol]["type"],
                current_price=None,
                created_at=now,
                updated_at=now,
            )
            for symbol in missing
        ]
    )
    await db.commit()
    print(f"Created {len(missing)} asset(s): {', '.join(missing)}")
    return await fetch_existing_assets_map(db, symbols)


def _same(stored, incoming) -> bool:
    """Compare a stored value with an incoming one, tolerating FLOAT column rounding."""
    if isinstance(stored, float) and isinstance(incoming, int | float):
        # MySQL FLOAT is single precision, so an exact == would report a change every run.
        return math.isclose(stored, float(incoming), rel_tol=1e-6, abs_tol=1e-9)
    return bool(stored == incoming)


async def upsert_trades(db: AsyncSession, rows: list[dict], dry_run: bool) -> tuple[int, int, int]:
    """Insert new trades, update changed ones, leave identical ones alone."""
    refs = [r["source_ref"] for r in rows]
    result = await db.execute(select(Trade).where(Trade.source_ref.in_(refs)))
    existing = {t.source_ref: t for t in result.scalars().all()}

    trade_fields = (
        "asset_id",
        "trade_type",
        "trade_date",
        "quantity",
        "price_per_unit",
        "currency",
        "group_id",
    )
    inserted = updated = unchanged = 0
    to_insert = []

    for row in rows:
        current = existing.get(row["source_ref"])
        if current is None:
            to_insert.append(
                Trade(
                    **{f: row[f] for f in trade_fields},
                    source_ref=row["source_ref"],
                )
            )
            inserted += 1
            continue

        changes = {
            field: row[field]
            for field in trade_fields
            if not _same(getattr(current, field), row[field])
        }
        if not changes:
            unchanged += 1
            continue

        updated += 1
        print(
            f"  update {row['symbol']} {row['trade_type']} {row['trade_date']:%Y-%m-%d}: "
            + ", ".join(f"{k} {getattr(current, k)} -> {v}" for k, v in changes.items())
        )
        if not dry_run:
            for field, value in changes.items():
                setattr(current, field, value)

    if not dry_run:
        db.add_all(to_insert)
        await db.commit()

    return inserted, updated, unchanged


async def import_csv_to_db(args: argparse.Namespace) -> None:
    rows = load_rows(args.csv_path, args.group_id, args.currency)
    if not rows:
        print("Nothing to import.")
        return

    symbols = sorted({row["symbol"] for row in rows})
    print(f"Read {len(rows)} trade(s) across {len(symbols)} symbol(s): {', '.join(symbols)}")

    async with AsyncSessionLocal() as db:
        await ensure_group_exists(db, args.group_id)
        symbol_id_map = await resolve_assets(db, symbols, args.dry_run)

        resolved = []
        for row in rows:
            asset_id = symbol_id_map.get(row["symbol"])
            if asset_id is None:
                if not args.dry_run:
                    print(f"ERROR: no asset id for {row['symbol']}; skipping")
                continue
            resolved.append({**row, "asset_id": asset_id})

        if not resolved:
            print("Nothing to write.")
            return

        prefix = "[dry-run] " if args.dry_run else ""
        inserted, updated, unchanged = await upsert_trades(
            db, [dict(r) for r in resolved], args.dry_run
        )
        print(f"{prefix}inserted {inserted}, updated {updated}, unchanged {unchanged}")


async def run(args: argparse.Namespace) -> None:
    try:
        await import_csv_to_db(args)
    finally:
        await engine.dispose()


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
