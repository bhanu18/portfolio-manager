from fastapi import APIRouter, HTTPException, Depends
from typing import List

# Import the Trade model
from models.trade import Trade, TradeCreate
from models.responses import TradeResponse
from db.dependencies import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from db import service

# Create a new router object for trades
router = APIRouter(
    prefix="/trades",
    tags=["Trades"]
)

@router.get("/", response_model=List[Trade])
async def read_all_trades(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    """
    Retrieve all trades from the database.
    """
    trades = await service.get_all_trades(db, skip=skip, limit=limit)
    return trades

@router.get("/symbol/{symbol}", response_model=List[TradeResponse])
async def read_trades_by_symbol(symbol: str, db: AsyncSession = Depends(get_db)):
    """
    Retrieve all trades for a specific asset by its symbol.
    """
    # 1. Find the asset to get its ID
    db_asset = await service.get_asset_by_symbol(db, symbol=symbol.upper())
    if not db_asset:
        raise HTTPException(status_code=404, detail=f"Asset with symbol '{symbol}' not found.")

    # 2. Fetch the trades using the asset's ID
    trades = await service.get_trades_by_asset_id(db, asset_id=db_asset.id)
    if not trades:
         raise HTTPException(status_code=404, detail=f"No trades found for symbol '{symbol}'.")

    # 3. Build the user-friendly response
    response_list = [
        TradeResponse(
            id=trade.id,
            symbol=db_asset.symbol, # Use the symbol we already have
            trade_type=trade.trade_type,
            trade_date=trade.trade_date,
            quantity=trade.quantity,
            price_per_unit=trade.price_per_unit
        ) for trade in trades
    ]
    return response_list

@router.post("/{symbol}", response_model=Trade, status_code=201)
async def create_new_trade_for_asset(
    symbol: str, 
    trade_in: TradeCreate, 
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new trade for an asset, specified by its symbol.
    """
    # First, find the asset in the database by its symbol
    db_asset = await service.get_asset_by_symbol(db, symbol=symbol.upper())
    if not db_asset:
        raise HTTPException(status_code=404, detail=f"Asset with symbol '{symbol}' not found.")
    
    # Now, call the CRUD function to create the trade in the database
    new_trade = await service.create_trade(
        db=db, 
        asset_id=db_asset.id, 
        trade_data=trade_in.model_dump()
    )
    return new_trade