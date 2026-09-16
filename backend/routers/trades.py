
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

import models.users as user_schema
from db import service
from db.dependencies import get_current_active_user, get_db
from models.responses import TradeResponse

# Import the Trade model
from models.trade import Trade, TradeCreate, TradeUpdate

# Create a new router object for trades
router = APIRouter(prefix="/trades", tags=["Trades"])


@router.get("/in-group/{group_id}", response_model=list[Trade])
async def read_trades_for_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: user_schema.User = Depends(get_current_active_user),
):
    """
    Retrieve all trades for a specific group.
    The user must be a member of the group to view its trades.
    """
    group = await service.get_group_by_id(db, group_id=group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # AUTHORIZATION CHECK
    if not any(member.id == current_user.id for member in group.members):
        raise HTTPException(status_code=403, detail="Not authorized to view this group's trades")

    # The service function would need to be `get_trades_by_group_id`
    return await service.get_trades_by_group_id(db, group_id=group_id)


@router.get("/symbol/{symbol}", response_model=list[TradeResponse])
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
            symbol=db_asset.symbol,  # Use the symbol we already have
            trade_type=trade.trade_type,
            trade_date=trade.trade_date,
            quantity=trade.quantity,
            price_per_unit=trade.price_per_unit,
        )
        for trade in trades
    ]
    return response_list


@router.post("/", response_model=Trade, status_code=201)
async def create_new_trade_for_asset(
    symbol: str,
    trade_in: TradeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: user_schema.User = Depends(get_current_active_user),
):
    """
    Create a new trade for an asset, specified by its symbol.
    """
    # 1. Fetch the group the user wants to trade in
    group = await service.get_group_by_id(db, group_id=trade_in.group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # 2. AUTHORIZATION: Check if the current user is a member of that group
    if not any(member.id == current_user.id for member in group.members):
        raise HTTPException(
            status_code=403, detail="Not authorized to create a trade in this group"
        )

    # First, find the asset in the database by its symbol
    db_asset = await service.get_asset_by_symbol(db, symbol=symbol.upper())
    if not db_asset:
        raise HTTPException(status_code=404, detail=f"Asset with symbol '{symbol}' not found.")

    # Now, call the CRUD function to create the trade in the database
    new_trade = await service.create_trade(
        db=db, asset_id=db_asset.id, trade_data=trade_in.model_dump()
    )
    return new_trade


@router.patch("/{trade_id}", response_model=Trade)
async def update_a_trade(
    trade_id: int,
    trade_in: TradeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: user_schema.User = Depends(get_current_active_user),
):
    """
    Update a trade. A user must be a member of the group the trade belongs to.
    """
    db_trade = await service.get_trade_by_id(db, trade_id=trade_id)
    if not db_trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    # AUTHORIZATION: Check if the current user is a member of the trade's group
    if not any(member.id == current_user.id for member in db_trade.group.members):
        raise HTTPException(status_code=403, detail="Not authorized to update this trade")

    return await service.update_trade(db, db_trade=db_trade, trade_in=trade_in)


@router.delete("/{trade_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_a_trade(
    trade_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: user_schema.User = Depends(get_current_active_user),
):
    """
    Delete a trade. A user must be a member of the group the trade belongs to.
    """
    db_trade = await service.get_trade_by_id(db, trade_id=trade_id)
    if not db_trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    # AUTHORIZATION: Check if the current user is a member of the trade's group
    if not any(member.id == current_user.id for member in db_trade.group.members):
        raise HTTPException(status_code=403, detail="Not authorized to delete this trade")

    return await service.delete_trade(db, db_trade=db_trade)
