from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from forex_python.converter import CurrencyRates, RatesNotAvailableError

from db.dependencies import get_db
from db import service

router = APIRouter(
    prefix="/reports",
    tags=["Reports"]
)

# Initialize the currency converter
c = CurrencyRates()

@router.get("/valuation/{symbol}/{target_currency}")
async def get_portfolio_valuation_by_symbol(
    symbol: str, 
    target_currency: str, 
    db: AsyncSession = Depends(get_db)
):
    """
    Calculates the valuation of a specific asset holding in a target currency.
    
    - `symbol`: The asset symbol (e.g., 'AAPL').
    - `target_currency`: The currency for the report (e.g., 'THB', 'EUR').
    """
    target_currency = target_currency.upper()
    
    # 1. Get the asset and its trades from the database
    asset = await service.get_asset_by_symbol(db, symbol=symbol.upper())
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
        
    trades = await service.get_trades_by_asset_id(db, asset_id=asset.id)
    if not trades:
        raise HTTPException(status_code=404, detail="No trades found for this asset")

    # 2. Calculate total holdings and cost basis in USD
    total_quantity = 0
    total_cost_usd = 0
    
    for trade in trades:
        if trade.trade_type == 'buy':
            total_quantity += trade.quantity
            total_cost_usd += trade.quantity * trade.price_per_unit
        elif trade.trade_type == 'sell':
            total_quantity -= trade.quantity
            total_cost_usd -= trade.quantity * trade.price_per_unit

    if total_quantity <= 0:
        return {"message": "No active holdings for this asset."}

    avg_cost_usd = total_cost_usd / total_quantity

    # 3. Get the CURRENT exchange rate for today's valuation
    try:
        current_rate = c.get_rate('USD', target_currency)
    except RatesNotAvailableError:
        raise HTTPException(status_code=503, detail=f"Exchange rates for {target_currency} are currently unavailable.")

    # 4. Calculate current values
    current_value_usd = total_quantity * asset.current_price
    current_value_target = current_value_usd * current_rate
    
    # 5. Calculate historical cost in target currency
    # This requires getting the exchange rate for the date of EACH trade
    total_cost_target_currency = 0
    for trade in trades:
        if trade.trade_type == 'buy':
            try:
                # Get the exchange rate for the specific day of the trade
                historical_rate = c.get_rate('USD', target_currency, trade.trade_date)
                total_cost_target_currency += (trade.quantity * trade.price_per_unit) * historical_rate
            except RatesNotAvailableError:
                # If a specific date fails, you might skip it or use an approximation
                continue 

    # 6. Calculate Profit/Loss in the target currency
    profit_loss_target = current_value_target - total_cost_target_currency
    
    return {
        "symbol": asset.symbol,
        "reporting_currency": target_currency,
        "holdings": {
            "quantity": total_quantity,
            "average_cost_usd": round(avg_cost_usd, 4),
        },
        "valuation": {
            "current_value_usd": round(current_value_usd, 4),
            "current_exchange_rate_to_target": round(current_rate, 4),
            "current_value_in_target_currency": round(current_value_target, 4)
        },
        "performance": {
            "total_cost_in_target_currency": round(total_cost_target_currency, 4),
            "profit_loss_in_target_currency": round(profit_loss_target, 4)
        }
    }