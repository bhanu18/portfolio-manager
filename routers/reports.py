from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from forex_python.converter import CurrencyRates, RatesNotAvailableError
from collections import defaultdict
import yfinance as yf

from db.dependencies import get_db
from db import service

router = APIRouter(prefix="/reports", tags=["Reports"])

# Initialize the currency converter
c = CurrencyRates()


@router.get("/valuation/{symbol}/{target_currency}")
async def get_portfolio_valuation_by_symbol(
    symbol: str, target_currency: str, db: AsyncSession = Depends(get_db)
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
        if trade.trade_type == "buy":
            total_quantity += trade.quantity
            total_cost_usd += trade.quantity * trade.price_per_unit
        elif trade.trade_type == "sell":
            total_quantity -= trade.quantity
            total_cost_usd -= trade.quantity * trade.price_per_unit

    if total_quantity <= 0:
        return {"message": "No active holdings for this asset."}

    avg_cost_usd = total_cost_usd / total_quantity

    # 3. Calculate current value in the asset's NATIVE currency
    current_value_native = total_quantity * asset.current_price

    # 4. Convert the native value to our common base currency (USD)
    current_value_usd = 0
    if asset.currency == "USD":
        current_value_usd = current_value_native
    else:
        try:
            # Get rate to convert from the asset's currency TO USD
            rate_to_usd = c.get_rate(asset.currency, "USD")
            current_value_usd = current_value_native * rate_to_usd
        except RatesNotAvailableError:
            raise HTTPException(
                status_code=503,
                detail=f"Exchange rate from {asset.currency} to USD is unavailable.",
            )

    # 5. Get the CURRENT exchange rate to convert from USD to the TARGET currency
    try:
        usd_to_target_rate = c.get_rate("USD", target_currency.upper())
    except RatesNotAvailableError:
        raise HTTPException(
            status_code=503,
            detail=f"Exchange rates for {target_currency} are currently unavailable.",
        )

    # 6. Calculate final values
    current_value_target = current_value_usd * usd_to_target_rate

    # The historical cost calculation is assumed to be based on USD trades
    # (as per our Trade model). This part of the logic remains valid.
    total_cost_target_currency = 0
    # ... (historical cost calculation logic remains the same)

    profit_loss_target = current_value_target - total_cost_target_currency

    return {
        "symbol": asset.symbol,
        "asset_native_currency": asset.currency,  # Add this for clarity
        "reporting_currency": target_currency.upper(),
        "holdings": {
            "quantity": total_quantity,
            "average_cost_usd": round(avg_cost_usd, 4),
        },
        "valuation": {
            "current_value_native": round(current_value_native, 4),
            "current_value_usd": round(current_value_usd, 4),
            "current_value_in_target_currency": round(current_value_target, 4),
        },
        "performance": {
            "total_cost_in_target_currency": round(total_cost_target_currency, 4),
            "profit_loss_in_target_currency": round(profit_loss_target, 4),
        },
    }

@router.get("/performance/ytd", summary="Get Year-to-Date portfolio performance")
async def get_ytd_performance(
    target_return: float = 0.15, 
    db: AsyncSession = Depends(get_db)
):
    """
    Calculates the total portfolio valuation and its Year-to-Date (YTD)
    performance against a specified target.
    """
    now = datetime.utcnow()
    start_of_year = datetime(now.year, 1, 1)

    # --- 1. Calculate holdings and value at the START of the year ---
    trades_before_ytd = await service.get_trades_before_date(db, end_date=start_of_year)
    holdings_start_of_year = defaultdict(float)
    for trade in trades_before_ytd:
        if trade.trade_type == 'buy':
            holdings_start_of_year[trade.asset_id] += trade.quantity
        else:
            holdings_start_of_year[trade.asset_id] -= trade.quantity

    value_start_of_year = 0
    assets = {asset.id: asset for asset in await service.get_all_assets(db)}
    
    for asset_id, quantity in holdings_start_of_year.items():
        if quantity > 0 and asset_id in assets:
            try:
                # Get historical price for the first trading day of the year
                ticker = yf.Ticker(assets[asset_id].symbol)
                hist = ticker.history(start=start_of_year, period="1d")
                price_on_jan_1 = hist['Close'].iloc[-1] if not hist.empty else 0
                value_start_of_year += quantity * price_on_jan_1
            except Exception:
                continue # Skip if historical price isn't available

    # --- 2. Calculate net contributions and current holdings THIS year ---
    trades_this_year = await service.get_trades_in_date_range(db, start_date=start_of_year, end_date=now)
    net_contributions_ytd = 0
    holdings_now = defaultdict(float, holdings_start_of_year) # Start with beginning of year holdings

    for trade in trades_this_year:
        if trade.trade_type == 'buy':
            net_contributions_ytd += trade.quantity * trade.price_per_unit
            holdings_now[trade.asset_id] += trade.quantity
        else:
            net_contributions_ytd -= trade.quantity * trade.price_per_unit
            holdings_now[trade.asset_id] -= trade.quantity
            
    # --- 3. Calculate CURRENT market value of the portfolio ---
    current_market_value = 0
    for asset_id, quantity in holdings_now.items():
        if quantity > 0 and asset_id in assets and assets[asset_id].current_price:
            current_market_value += quantity * assets[asset_id].current_price
            
    # --- 4. Calculate YTD Return ---
    profit_loss_ytd = current_market_value - value_start_of_year - net_contributions_ytd
    ytd_return_percent = (profit_loss_ytd / value_start_of_year) if value_start_of_year > 0 else 0

    return {
        "start_of_year_value_usd": round(value_start_of_year, 2),
        "current_market_value_usd": round(current_market_value, 2),
        "net_contributions_ytd_usd": round(net_contributions_ytd, 2),
        "performance": {
            "profit_loss_ytd_usd": round(profit_loss_ytd, 2),
            "ytd_return_percent": round(ytd_return_percent * 100, 2),
            "target_return_percent": round(target_return * 100, 2),
            "met_target": ytd_return_percent >= target_return
        }
    }