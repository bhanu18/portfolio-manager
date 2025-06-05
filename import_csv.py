import sys
import os

# Add the project root directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime
import yfinance as yf

# Import our database and model components
from db.session import AsyncSessionLocal, engine
from db.orm_models import Asset, Trade, Base
from db.service import get_asset_by_symbol, create_asset

# --- Configuration ---
CSV_FILE_PATH = 'C:/Users/bhanu/Downloads/portfolio_history_miracle_portfolio.csv'

async def get_asset_details(symbol: str):
    """Fetches additional asset details from yfinance."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        return {
            "name": info.get('longName', symbol),
            "market": info.get('exchange', 'Unknown'),
            "type": info.get('quoteType', 'EQUITY').lower()
        }
    except Exception:
        # Fallback for symbols yfinance might not recognize
        return {
            "name": symbol,
            "market": "Unknown",
            "type": "stock" # Default type
        }

async def import_csv_to_db():
    """
    Reads the CSV file and imports the data into the database.
    """
    print("Reading CSV file...")
    df = pd.read_csv(CSV_FILE_PATH)
    
    print("Found the following columns:", df.columns.tolist())
    
    # Convert 'Date' column to datetime objects
    df['Date'] = pd.to_datetime(df['Date'])
    
    print(f"Found {len(df)} records to process.")

    # Get a database session
    db: AsyncSession
    async with AsyncSessionLocal() as db:
        for index, row in df.iterrows():
            symbol = row['Symbol']
            print(f"Processing row {index + 1}: {'buy'} {row['Quantity']} of {symbol} on {row['Date'].date()}...")

            # --- Step 1: Find or Create the Asset ---
            asset = await get_asset_by_symbol(db, symbol)
            
            if not asset:
                print(f"  -> Asset '{symbol}' not found. Creating it...")
                asset_details = await get_asset_details(symbol)
                
                asset_data = {
                    "symbol": symbol,
                    "name": asset_details["name"],
                    "market": asset_details["market"],
                    "type": asset_details["type"],
                    "created_at": datetime.utcnow(), 
                    "updated_at": datetime.utcnow()
                }
                # We are creating a basic asset record here. Price can be updated later.
                asset = await create_asset(db, asset_data=asset_data)
                print(f"  -> Created asset with ID: {asset.id}")

            # --- Step 2: Create the Trade Record ---
            trade_data = {
                "trade_type": 'buy',
                "trade_date": row['Date'],
                "quantity": row['Quantity'],
                "price_per_unit": row['Purchase Price'],
                "currency": row['Currency']
            }
            
            # Create an instance of the Trade ORM model
            db_trade = Trade(**trade_data, asset_id=asset.id)
            db.add(db_trade)
            
        # Commit all the new trades at once
        print("\nCommitting all transactions to the database...")
        await db.commit()
        print("Data import successful!")

async def main():
    # Optional: You can create tables here if they don't exist,
    # but it's better to use Alembic migrations.
    # async with engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.create_all)
    await import_csv_to_db()

if __name__ == "__main__":
    # Run the main async function
    asyncio.run(main())