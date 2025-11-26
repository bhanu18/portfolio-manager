from fastapi import APIRouter, HTTPException, Depends, status
import yfinance as yf
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
import asyncio

# Import our new dependencies and functions
import models.users as user_schema
from models.asset import Asset, AssetCreate, AssetUpdate
from db.dependencies import get_db, get_current_active_admin_user
from db import service

router = APIRouter(
    prefix="/assets",  # All routes in this router will start with /assets
    tags=["Assets"],  # Groups endpoints in the API docs
    responses={404: {"description": "Not found"}},
)


@router.get("/", response_model=List[Asset])
async def read_all_assets(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: user_schema.User = Depends(get_current_active_admin_user),
):
    """
    Retrieve all assets from the database with pagination.
    """
    assets = await service.get_all_assets(db, skip=skip, limit=limit)
    return assets


@router.get("/{symbol}")
async def get_asset_by_symbol(symbol: str):

    asset = await service.get_asset_by_symbol_or_id(symbol=symbol)
    if asset:
        return asset
    return {"error": "Asset not found"}, 404


@router.get("/{asset_id}", response_model=Asset)
async def read_asset_by_id(asset_id: int, db: AsyncSession = Depends(get_db)):
    """
    Retrieve a single asset by its ID.
    """
    db_asset = await service.get_asset_by_id(db, asset_id=asset_id)
    if db_asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return db_asset


@router.post("/create", response_model=Asset, status_code=201)
async def create_asset(asset_in: AssetCreate, db: AsyncSession = Depends(get_db)):
    """
    Create a new asset. The current price will be fetched from Yahoo Finance.
    """
    # Check if asset already exists
    db_asset = await service.get_asset_by_symbol(db, symbol=asset_in.symbol)
    if db_asset:
        raise HTTPException(
            status_code=400,
            detail=f"Asset with symbol '{asset_in.symbol}' already exists.",
        )

    # 1. Fetch the current price from yfinance
    try:
        ticker = yf.Ticker(asset_in.symbol)
        # 'regularMarketPrice' is a reliable field for the current price
        # You can also use 'currentPrice'
        info = ticker.info
        current_price = info.get("regularMarketPrice")
        asset_currency = info.get("currency", "USD").upper()

        if current_price is None:
            # Fallback for some assets or if the market is closed
            hist = ticker.history(period="1d")
            if not hist.empty:
                current_price = hist["Close"].iloc[-1]
            else:
                # If no price can be found, we can't create the asset
                raise HTTPException(
                    status_code=404,
                    detail=f"Could not find price data for symbol '{asset_in.symbol}'",
                )

    except Exception as e:
        # Handle cases where the ticker symbol is invalid or yfinance fails
        raise HTTPException(
            status_code=400,
            detail=f"Error fetching data from yfinance for symbol '{asset_in.symbol}': {e}",
        )

    # 2. Prepare the complete asset data dictionary
    asset_data = asset_in.model_dump()
    asset_data["current_price"] = current_price
    asset_data["currency"] = asset_currency
    asset_data["created_at"] = datetime.utcnow()
    asset_data["updated_at"] = datetime.utcnow()
    # 3. Call the CRUD function to create the asset in the database
    new_asset = await service.create_asset(db=db, asset_data=asset_data)

    # 4. Return the complete asset object to the user
    return new_asset


def fetch_price_sync(symbol: str) -> float | None:
    """
    A standard synchronous function that fetches a price. This is what will be run
    in a separate thread.
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d", auto_adjust=True)
        if not hist.empty:
            # Return the latest closing price, rounded
            return round(hist["Close"].iloc[-1], 2)
    except Exception as e:
        # Print the error for debugging but don't crash the loop
        print(f"  ...ERROR fetching yfinance data for {symbol}: {e}")
    return None


@router.post("/update-all-prices", summary="Update prices for all assets")
async def update_all_asset_prices(db: AsyncSession = Depends(get_db)):
    """
    Fetches all assets from the database and updates the current price for each
    one that has not been updated in the last 24 hours.
    """
    updated_symbols = []
    skipped_symbols = []
    now = datetime.utcnow()
    db.expire_on_commit = False
    db_assets = await service.get_all_assets(db)

    for asset in db_assets:
        if asset.price_last_updated and (
            now - asset.price_last_updated < timedelta(days=1)
        ):
            skipped_symbols.append(asset.symbol)
            continue

        # Run the blocking yfinance call in a separate thread
        # The main event loop is NOT blocked while this runs.
        new_price = await asyncio.to_thread(fetch_price_sync, asset.symbol)

        if new_price is not None:
            # If we got a price, call our async database service function
            await service.update_asset_price(db, asset=asset, new_price=new_price)
            updated_symbols.append(asset.symbol)
        else:
            # If fetching failed, just skip this asset
            skipped_symbols.append(asset.symbol)

    return {
        "message": "Price update process finished.",
        "updated_count": len(updated_symbols),
        "skipped_count": len(skipped_symbols),
        "updated_symbols": updated_symbols,
        "skipped_symbols": skipped_symbols,
    }


@router.patch("/{asset_id}", response_model=Asset, tags=["Admin"])
async def update_an_asset(
    asset_id: int,
    asset_in: AssetUpdate,
    db: AsyncSession = Depends(get_db),
    admin_user: user_schema.User = Depends(get_current_active_admin_user),
):
    """Update a global asset's details. (Admin Only)"""
    # Use the public get_asset_by_id function since it's a global asset
    db_asset = await service.get_asset_by_id(db, asset_id=asset_id)
    if not db_asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    return await service.update_asset(db, db_asset=db_asset, asset_in=asset_in)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Admin"])
async def delete_an_asset(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: user_schema.User = Depends(get_current_active_admin_user),
):
    """Delete a global asset. Fails if trades are linked to it. (Admin Only)"""
    db_asset = await service.get_asset_by_id(db, asset_id=asset_id)
    if not db_asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    success = await service.delete_asset(db, db_asset=db_asset)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete asset. It is linked to existing trades.",
        )
    return {"message": "Asset deleted successfully."}
