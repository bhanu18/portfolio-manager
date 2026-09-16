import asyncio
import os
import sys
from datetime import datetime

import pandas as pd
import yfinance as yf
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

# Add path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.orm_models import Asset, Trade
from db.session import AsyncSessionLocal

# Usage: python scripts/import_csv.py path/to/portfolio_history.csv
CSV_FILE_PATH = sys.argv[1] if len(sys.argv) > 1 else "portfolio_history.csv"


async def fetch_existing_assets_map(db: AsyncSession, symbols: list) -> dict:
    """
    Queries the DB for all symbols in the list at once.
    Returns a dictionary: {'SYMBOL': asset_id}
    """
    # SQLAlchemy IN clause to fetch all matching assets in one query
    query = select(Asset.symbol, Asset.id).where(Asset.symbol.in_(symbols))
    result = await db.execute(query)

    # Create a quick lookup map
    return {row.symbol: row.id for row in result.all()}


async def get_yfinance_data_batch(symbols: list) -> dict:
    """
    Fetches data for a list of symbols.
    (Optimized to fetch unique symbols only)
    """
    if not symbols:
        return {}

    print(f"Fetching yfinance data for {len(symbols)} new assets...")

    # yf.Tickers is faster for multiple symbols than looping individual Ticker objects
    # Join symbols with space for yfinance format
    tickers_string = " ".join(symbols)
    tickers = yf.Tickers(tickers_string)

    asset_data_map = {}

    for symbol in symbols:
        try:
            # Accessing tickers.tickers[symbol].info might still trigger network calls,
            # but doing it specifically for the 'missing' list is much better.
            info = tickers.tickers[symbol].info
            asset_data_map[symbol] = {
                "name": info.get("longName", symbol),
                "market": info.get("exchange", "Unknown"),
                "type": info.get("quoteType", "EQUITY").lower(),
            }
        except Exception:
            print(f"Warning: Could not fetch details for {symbol}. Using defaults.")
            asset_data_map[symbol] = {
                "name": symbol,
                "market": "Unknown",
                "type": "stock",
            }

    return asset_data_map


async def import_csv_to_db():
    print("Reading CSV file...")
    df = pd.read_csv(CSV_FILE_PATH)

    # --- DATA CLEANING (Fixes the NaN Error) ---
    print("Cleaning data...")

    # 1. Force columns to numeric, turning text/errors into NaN
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce")
    df["Purchase Price"] = pd.to_numeric(df["Purchase Price"], errors="coerce")

    # 2. Drop rows where Quantity or Price is NaN (Invalid trades)
    initial_count = len(df)
    df.dropna(subset=["Quantity", "Purchase Price"], inplace=True)
    dropped_count = initial_count - len(df)

    if dropped_count > 0:
        print(f"⚠️ Dropped {dropped_count} rows due to missing Quantity or Price.")

    # 3. Replace any remaining NaNs (e.g. in Currency) with None (SQL NULL)
    df = df.where(pd.notnull(df), None)
    df["Date"] = pd.to_datetime(df["Date"])

    # 1. Identify all unique symbols in the CSV
    unique_symbols = df["Symbol"].unique().tolist()
    print(f"Found {len(df)} trades involving {len(unique_symbols)} unique symbols.")

    async with AsyncSessionLocal() as db:
        # --- STEP 1: Resolve Assets (Batch Read/Write) ---

        # Batch Read: Get IDs of assets that already exist
        symbol_id_map = await fetch_existing_assets_map(db, unique_symbols)

        # Identify which symbols are missing from the DB
        missing_symbols = [s for s in unique_symbols if s not in symbol_id_map]

        if missing_symbols:
            # Batch API: Get details only for the missing symbols
            new_assets_details = await get_yfinance_data_batch(missing_symbols)

            new_asset_objects = []
            for symbol in missing_symbols:
                details = new_assets_details.get(symbol)
                new_asset = Asset(
                    symbol=symbol,
                    name=details["name"],
                    market=details["market"],
                    type=details["type"],
                    current_price=0.0,  # Default
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                new_asset_objects.append(new_asset)

            # Batch Write: Insert all new assets at once
            if new_asset_objects:
                print(f"Creating {len(new_asset_objects)} new assets in DB...")
                db.add_all(new_asset_objects)
                await db.commit()  # Commit to generate IDs

                # Re-fetch the map to get the IDs of the newly created assets
                # (This is safer than relying on session memory for bulk inserts)
                symbol_id_map = await fetch_existing_assets_map(db, unique_symbols)

        # --- STEP 2: Create Trades (In-Memory Processing) ---

        print("Preparing trade records...")
        trades_to_insert = []

        for _index, row in df.iterrows():
            purchase_price = row["Purchase Price"]

            symbol = row["Symbol"]
            asset_id = symbol_id_map.get(symbol)

            if not asset_id:
                print(f"Error: ID for {symbol} not found even after creation step. Skipping.")
                continue

            trade = Trade(
                asset_id=asset_id,
                trade_type="buy",  # Assuming CSV is all buys based on your snippet
                trade_date=row["Date"],
                quantity=float(row["Quantity"]),
                price_per_unit=float(purchase_price),
                currency=row["Currency"],
                group_id=1,
            )
            trades_to_insert.append(trade)

        # --- STEP 3: Batch Insert Trades ---

        if trades_to_insert:
            print(f"Bulk inserting {len(trades_to_insert)} trades...")
            db.add_all(trades_to_insert)
            await db.commit()
            print("Success! All trades imported.")
        else:
            print("No trades to import.")


if __name__ == "__main__":
    asyncio.run(import_csv_to_db())
