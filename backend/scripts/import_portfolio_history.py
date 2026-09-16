#!/usr/bin/env python3
"""
Import portfolio history from an Excel file into the MySQL database.

Each sheet in the Excel file maps to a Group. Each row maps to a buy Trade.
Assets are upserted by symbol.

Usage:
    python scripts/import_portfolio_history.py --file /path/to/portfolio_history.xlsx
    python scripts/import_portfolio_history.py  # uses default path

Requires SYNC_DATABASE_URL to be set in .env or as an environment variable.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import openpyxl
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Allow imports from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import settings
from db.orm_models import Asset, Group, Trade

# Excel column indices (0-based)
COL_SYMBOL = 0
COL_CURRENT_PRICE = 1
COL_TRADE_DATE = 9
COL_PURCHASE_PRICE = 10
COL_QUANTITY = 11
COL_ASSET_TYPE = 16
COL_CURRENCY = 17

# Maps Excel Asset Type strings to the DB's allowed type literals
ASSET_TYPE_MAP = {
    "STOCK": "stock",
    "CRYPTO": "crypto",
    "CASH": "cash",
    "ETF": "etf",
}


# Maps sheet names to a human-friendly group name (identity mapping by default)
def sheet_to_group_name(sheet_name: str) -> str:
    return sheet_name.replace("_", " ").title()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import portfolio history from Excel to MySQL")
    parser.add_argument(
        "--file",
        default=str(Path.home() / "Downloads" / "portfolio_history.xlsx"),
        help="Path to the Excel file (default: ~/Downloads/portfolio_history.xlsx)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate the file without writing to the database",
    )
    return parser.parse_args()


def get_or_create_asset(
    session: Session, symbol: str, asset_type: str, currency: str, current_price: float | None
) -> Asset:
    asset = session.query(Asset).filter_by(symbol=symbol).first()
    if asset:
        # Update current price if we have a fresher value
        if current_price is not None:
            asset.current_price = current_price
            asset.price_last_updated = datetime.utcnow()
            asset.updated_at = datetime.utcnow()
        return asset

    now = datetime.utcnow()
    asset = Asset(
        symbol=symbol,
        name=symbol,  # Name defaults to symbol; can be updated later via the API
        market=currency,  # Use currency as a proxy for market (e.g. USD → US market, THB → Thai market)
        type=asset_type,
        current_price=current_price,
        price_last_updated=now if current_price is not None else None,
        created_at=now,
        updated_at=now,
    )
    session.add(asset)
    session.flush()  # Populate asset.id without committing
    return asset


def get_or_create_group(session: Session, name: str) -> Group:
    group = session.query(Group).filter_by(name=name).first()
    if group:
        return group
    group = Group(name=name)
    session.add(group)
    session.flush()
    return group


def import_sheet(session: Session, ws, group_name: str, dry_run: bool) -> tuple[int, list[str]]:
    """
    Process one worksheet. Returns (rows_imported, list_of_warnings).
    """
    warnings: list[str] = []
    rows_imported = 0

    group = None if dry_run else get_or_create_group(session, group_name)

    for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if row_idx == 1:
            continue  # skip header

        symbol = row[COL_SYMBOL]
        trade_date = row[COL_TRADE_DATE]
        purchase_price = row[COL_PURCHASE_PRICE]
        quantity = row[COL_QUANTITY]
        asset_type_raw = row[COL_ASSET_TYPE]
        currency = row[COL_CURRENCY]
        current_price = row[COL_CURRENT_PRICE]

        # Validate required fields
        if not symbol:
            warnings.append(f"Row {row_idx}: missing Symbol — skipped")
            continue
        if not trade_date or not isinstance(trade_date, datetime):
            warnings.append(f"Row {row_idx} ({symbol}): invalid or missing Trade Date — skipped")
            continue
        if purchase_price is None:
            warnings.append(f"Row {row_idx} ({symbol}): missing Purchase Price — skipped")
            continue
        if quantity is None:
            warnings.append(f"Row {row_idx} ({symbol}): missing Quantity — skipped")
            continue

        asset_type = ASSET_TYPE_MAP.get(
            str(asset_type_raw).upper() if asset_type_raw else "", "stock"
        )
        currency_str = str(currency).strip() if currency else "USD"

        if dry_run:
            print(
                f"  [dry-run] Would insert Trade: symbol={symbol}, date={trade_date.date()}, "
                f"qty={quantity}, price={purchase_price}, currency={currency_str}, group={group_name}"
            )
            rows_imported += 1
            continue

        asset = get_or_create_asset(session, symbol, asset_type, currency_str, current_price)

        trade = Trade(
            asset_id=asset.id,
            group_id=group.id,
            trade_type="buy",
            trade_date=trade_date,
            quantity=float(quantity),
            price_per_unit=float(purchase_price),
            currency=currency_str,
        )
        session.add(trade)
        rows_imported += 1

    return rows_imported, warnings


def main() -> None:
    args = parse_args()
    xlsx_path = Path(args.file)

    if not xlsx_path.exists():
        print(f"ERROR: File not found: {xlsx_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading: {xlsx_path}")
    wb = openpyxl.load_workbook(xlsx_path)
    print(f"Sheets found: {wb.sheetnames}")

    if args.dry_run:
        print("\n--- DRY RUN MODE: no data will be written ---\n")

    engine = create_engine(settings.SYNC_DATABASE_URL, echo=False)

    total_imported = 0
    total_warnings: list[str] = []

    with Session(engine) as session:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            group_name = sheet_to_group_name(sheet_name)
            print(
                f"\nProcessing sheet '{sheet_name}' → group '{group_name}' ({ws.max_row - 1} data rows)"
            )

            imported, warnings = import_sheet(session, ws, group_name, dry_run=args.dry_run)
            total_imported += imported
            total_warnings.extend(warnings)

            print(f"  Queued {imported} trade(s)")
            for w in warnings:
                print(f"  WARNING: {w}")

        if not args.dry_run:
            session.commit()
            print("\nCommitted successfully.")

    print(f"\nSummary: {total_imported} trade(s) imported, {len(total_warnings)} warning(s)")
    if total_warnings:
        print("Warnings:")
        for w in total_warnings:
            print(f"  - {w}")


if __name__ == "__main__":
    main()
