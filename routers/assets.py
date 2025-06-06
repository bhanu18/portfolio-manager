from fastapi import APIRouter, HTTPException, Depends
import yfinance as yf
from datetime import datetime, timedelta
from models.asset import Asset, AssetCreate
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

# Import our new dependencies and functions
from db.dependencies import get_db
from db import service
from models.asset import Asset, AssetCreate

router = APIRouter(
    prefix="/assets",  # All routes in this router will start with /assets
    tags=["Assets"],   # Groups endpoints in the API docs
    responses={404: {"description": "Not found"}},
)

@router.get("/", response_model=List[Asset])
async def read_all_assets(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
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
        raise HTTPException(status_code=400, detail=f"Asset with symbol '{asset_in.symbol}' already exists.")

    # 1. Fetch the current price from yfinance
    try:
        ticker = yf.Ticker(asset_in.symbol)
        # 'regularMarketPrice' is a reliable field for the current price
        # You can also use 'currentPrice'
        info = ticker.info
        current_price = info.get('regularMarketPrice')
        asset_currency = info.get('currency', 'USD').upper()

        if current_price is None:
            # Fallback for some assets or if the market is closed
            hist = ticker.history(period="1d")
            if not hist.empty:
                current_price = hist['Close'].iloc[-1]
            else:
                # If no price can be found, we can't create the asset
                raise HTTPException(
                    status_code=404,
                    detail=f"Could not find price data for symbol '{asset_in.symbol}'"
                )

    except Exception as e:
        # Handle cases where the ticker symbol is invalid or yfinance fails
        raise HTTPException(
            status_code=400,
            detail=f"Error fetching data from yfinance for symbol '{asset_in.symbol}': {e}"
        )

    # 2. Prepare the complete asset data dictionary
    asset_data = asset_in.model_dump()
    asset_data['current_price'] = current_price
    asset_data['currency'] = asset_currency
    asset_data['created_at'] = datetime.utcnow()
    asset_data['updated_at'] = datetime.utcnow()
    # 3. Call the CRUD function to create the asset in the database
    new_asset = await service.create_asset(db=db, asset_data=asset_data)

    # 4. Return the complete asset object to the user
    return new_asset

@router.post("/update-all-prices", summary="Update prices for all assets")
async def update_all_asset_prices(db: AsyncSession = Depends(get_db)):
    """
    Updates the current price for all assets that have not been updated
    in the last 24 hours.
    """
    updated_symbols = []
    skipped_symbols = []
    now = datetime.utcnow()
     # 1. Fetch all assets directly from the database
    db_assets = await service.get_all_assets(db)

    for asset in db_assets:
        # 2. Apply rate-limiting logic for each asset
        if asset.price_last_updated and (now - asset.price_last_updated < timedelta(days=1)):
            skipped_symbols.append(asset.symbol)
            continue # Skip this asset, it was updated recently

        # 3. If eligible, fetch the new price from yfinance
        try:
            ticker = yf.Ticker(asset.symbol)
            hist = ticker.history(period="1d")
            if not hist.empty:
                new_price = round(hist['Close'].iloc[-1], 2)
                
                # 4. Call the CRUD function to update the asset in the database
                await service.update_asset_price(db, asset=asset, new_price=new_price)
                
                updated_symbols.append(asset.symbol)
            else:
                # Could not find yfinance data
                skipped_symbols.append(asset.symbol)

        except Exception:
            # If yfinance fails for one symbol, just skip it and move on
            skipped_symbols.append(asset.symbol)
            continue

    return {
        "message": "Price update process finished.",
        "updated_count": len(updated_symbols),
        "skipped_count": len(skipped_symbols),
        "updated_symbols": updated_symbols,
        "skipped_symbols": skipped_symbols
    }