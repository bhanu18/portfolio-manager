from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
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

    # 3. Determine the asset's currency
    # Since assets table doesn't have currency, we'll infer it from:
    # 1. yfinance data, or 2. market field, or 3. default to USD
    asset_currency = "USD"  # Default

    try:
        import yfinance as yf
        ticker = yf.Ticker(asset.symbol)
        info = ticker.info
        asset_currency = info.get("currency", "USD").upper()
    except Exception:
        # If yfinance fails, infer from market
        market_currency_map = {
            "NASDAQ": "USD",
            "NYSE": "USD",
            "THAI": "THB",
            "SET": "THB",  # Stock Exchange of Thailand
            "TSE": "JPY",  # Tokyo Stock Exchange
            "LSE": "GBP",  # London Stock Exchange
            "NSE": "INR",  # National Stock Exchange of India
        }
        asset_currency = market_currency_map.get(asset.market.upper(), "USD")

    # 4. Calculate current value in the asset's NATIVE currency
    current_value_native = total_quantity * asset.current_price

    # 5. Convert the native value to our common base currency (USD)
    current_value_usd = 0
    if asset_currency == "USD":
        current_value_usd = current_value_native
    else:
        try:
            # Get rate to convert from the asset's currency TO USD
            rate_to_usd = c.get_rate(asset_currency, "USD")
            current_value_usd = current_value_native * rate_to_usd
        except RatesNotAvailableError:
            raise HTTPException(
                status_code=503,
                detail=f"Exchange rate from {asset_currency} to USD is unavailable.",
            )

    # 6. Get the CURRENT exchange rate to convert from USD to the TARGET currency
    try:
        usd_to_target_rate = c.get_rate("USD", target_currency.upper())
    except RatesNotAvailableError:
        raise HTTPException(
            status_code=503,
            detail=f"Exchange rates for {target_currency} are currently unavailable.",
        )

    # 7. Calculate final values
    current_value_target = current_value_usd * usd_to_target_rate

    # Convert the historical cost from USD to target currency
    total_cost_target_currency = total_cost_usd * usd_to_target_rate

    profit_loss_target = current_value_target - total_cost_target_currency

    return {
        "symbol": asset.symbol,
        "asset_native_currency": asset_currency,  # Currency determined from yfinance or market
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

@router.get("/portfolio-performance", summary="Get comprehensive portfolio performance analysis")
async def get_portfolio_performance(
    base_currency: str = "USD",
    benchmark_ticker: str = "SPY",
    db: AsyncSession = Depends(get_db)
):
    """
    Comprehensive portfolio performance analysis with multi-currency support.

    Features:
    - Historical FX rates at trade date for accurate cost basis
    - Return attribution (local return vs FX return)
    - Benchmark comparison and alpha calculation
    - Grouping by currency and asset type
    - Top/bottom performers
    - Annualized returns

    Args:
        base_currency: Currency for reporting (default: USD)
        benchmark_ticker: Benchmark index (default: SPY)
    """
    from datetime import datetime, timedelta
    from collections import defaultdict
    import yfinance as yf

    now = datetime.utcnow()
    report_date = now.strftime("%Y-%m-%d")

    # FX rate cache to avoid redundant API calls
    fx_cache = {}
    fx_warnings = []

    # Helper function to get historical FX rate
    def get_historical_fx_rate(from_currency: str, to_currency: str, date: datetime) -> dict:
        """Get historical FX rate at specific date"""
        if from_currency == to_currency:
            return {"rate": 1.0, "actual_date": date.strftime("%Y-%m-%d"), "source": "same_currency", "warning": None}

        cache_key = f"{from_currency}{to_currency}_{date.strftime('%Y-%m-%d')}"
        if cache_key in fx_cache:
            return fx_cache[cache_key]

        try:
            # Try direct pair (e.g., THBUSD=X)
            pair = f"{from_currency}{to_currency}=X"
            ticker = yf.Ticker(pair)
            # Fetch a week of data to handle weekends/holidays
            hist = ticker.history(start=date - timedelta(days=7), end=date + timedelta(days=1))

            if not hist.empty:
                # Get closest date
                closest_date = hist.index[hist.index <= date][-1] if any(hist.index <= date) else hist.index[0]
                rate = hist.loc[closest_date, 'Close']
                result = {
                    "rate": float(rate),
                    "actual_date": closest_date.strftime("%Y-%m-%d"),
                    "source": "yfinance",
                    "warning": None if closest_date.date() == date.date() else f"Used {closest_date.date()} (nearest to {date.date()})"
                }
                fx_cache[cache_key] = result
                return result
        except Exception as e:
            print(f"Failed to fetch {from_currency}/{to_currency} direct: {e}")

        # Try inverse pair
        try:
            pair = f"{to_currency}{from_currency}=X"
            ticker = yf.Ticker(pair)
            hist = ticker.history(start=date - timedelta(days=7), end=date + timedelta(days=1))

            if not hist.empty:
                closest_date = hist.index[hist.index <= date][-1] if any(hist.index <= date) else hist.index[0]
                rate = 1.0 / hist.loc[closest_date, 'Close']
                result = {
                    "rate": float(rate),
                    "actual_date": closest_date.strftime("%Y-%m-%d"),
                    "source": "yfinance_inverse",
                    "warning": None if closest_date.date() == date.date() else f"Used {closest_date.date()} (nearest to {date.date()})"
                }
                fx_cache[cache_key] = result
                return result
        except Exception as e:
            print(f"Failed to fetch {from_currency}/{to_currency} inverse: {e}")

        # Fallback to current rate if historical not available
        try:
            current_rate = c.get_rate(from_currency, to_currency)
            warning = f"Historical FX rate unavailable for {date.date()}, using current rate"
            result = {"rate": current_rate, "actual_date": now.strftime("%Y-%m-%d"), "source": "fallback_current", "warning": warning}
            fx_cache[cache_key] = result
            return result
        except:
            result = {"rate": 1.0, "actual_date": date.strftime("%Y-%m-%d"), "source": "fallback_default", "warning": f"FX rate unavailable, using 1.0"}
            return result

    # Helper function to get current FX rate
    def get_current_fx_rate(from_currency: str, to_currency: str) -> float:
        """Get current FX rate"""
        if from_currency == to_currency:
            return 1.0
        try:
            return c.get_rate(from_currency, to_currency)
        except:
            return 1.0

    print(f"\n[Portfolio Performance Analysis] Report Date: {report_date}, Base Currency: {base_currency}")

    # Fetch all trades and assets (set high limit to get all records)
    all_trades = await service.get_all_trades(db, skip=0, limit=10000)
    all_assets = await service.get_all_assets(db, skip=0, limit=10000)
    assets_dict = {asset.id: asset for asset in all_assets}

    # Group trades by asset to calculate holdings
    holdings_by_asset = defaultdict(lambda: {"buys": [], "sells": [], "quantity": 0})

    for trade in all_trades:
        if trade.trade_type == "buy":
            holdings_by_asset[trade.asset_id]["buys"].append(trade)
            holdings_by_asset[trade.asset_id]["quantity"] += trade.quantity
        elif trade.trade_type == "sell":
            holdings_by_asset[trade.asset_id]["sells"].append(trade)
            holdings_by_asset[trade.asset_id]["quantity"] -= trade.quantity

    # Calculate current exchange rates
    currencies_in_portfolio = set()
    for asset_id in holdings_by_asset.keys():
        if holdings_by_asset[asset_id]["quantity"] > 0:
            for trade in holdings_by_asset[asset_id]["buys"]:
                currencies_in_portfolio.add(trade.currency)

    exchange_rates_current = {base_currency: 1.0}
    for currency in currencies_in_portfolio:
        if currency != base_currency:
            exchange_rates_current[currency] = get_current_fx_rate(currency, base_currency)

    print(f"Current exchange rates: {exchange_rates_current}")

    # Analyze each holding
    holdings_analysis = []
    total_cost_basis_base = 0
    total_current_value_base = 0
    total_dividends_base = 0

    by_currency = defaultdict(lambda: {"value_base": 0, "cost_basis_base": 0, "local_gain": 0, "fx_gain": 0})
    by_asset_type = defaultdict(lambda: {"value_base": 0, "cost_basis_base": 0})

    for asset_id, holding_data in holdings_by_asset.items():
        if holding_data["quantity"] <= 0:
            continue  # Skip sold or zero positions

        asset = assets_dict.get(asset_id)
        if not asset:
            continue

        # Calculate FIFO cost basis with historical FX rates
        quantity_remaining = holding_data["quantity"]
        cost_basis_base = 0
        weighted_fx_at_purchase = 0
        weighted_purchase_price = 0
        earliest_purchase_date = None
        total_quantity_for_weighting = 0

        for buy_trade in sorted(holding_data["buys"], key=lambda x: x.trade_date):
            if quantity_remaining <= 0:
                break

            qty_from_this_trade = min(buy_trade.quantity, quantity_remaining)

            # Get historical FX rate at purchase date
            fx_data = get_historical_fx_rate(buy_trade.currency, base_currency, buy_trade.trade_date)
            fx_rate_at_purchase = fx_data["rate"]

            if fx_data["warning"]:
                fx_warnings.append({"ticker": asset.symbol, "message": fx_data["warning"]})

            # Cost basis in base currency using historical FX rate
            cost_in_base = (buy_trade.price_per_unit * qty_from_this_trade) * fx_rate_at_purchase
            cost_basis_base += cost_in_base

            # Track for weighted averages
            weighted_fx_at_purchase += fx_rate_at_purchase * qty_from_this_trade
            weighted_purchase_price += buy_trade.price_per_unit * qty_from_this_trade
            total_quantity_for_weighting += qty_from_this_trade

            if earliest_purchase_date is None or buy_trade.trade_date < earliest_purchase_date:
                earliest_purchase_date = buy_trade.trade_date

            quantity_remaining -= qty_from_this_trade

        if total_quantity_for_weighting == 0:
            continue

        avg_fx_at_purchase = weighted_fx_at_purchase / total_quantity_for_weighting
        avg_purchase_price = weighted_purchase_price / total_quantity_for_weighting
        trade_currency = holding_data["buys"][0].currency

        # Get current price
        try:
            ticker = yf.Ticker(asset.symbol)
            current_price = asset.current_price if asset.current_price else ticker.info.get("regularMarketPrice", 0)
            if not current_price:
                hist = ticker.history(period="1d")
                current_price = hist["Close"].iloc[-1] if not hist.empty else 0
        except:
            current_price = asset.current_price if asset.current_price else 0

        if current_price == 0:
            continue

        # Current value using current FX rate
        fx_rate_current = exchange_rates_current.get(trade_currency, 1.0)
        current_value_original = current_price * holding_data["quantity"]
        current_value_base = current_value_original * fx_rate_current

        cost_basis_original = avg_purchase_price * holding_data["quantity"]

        # Return attribution
        local_return_pct = ((current_price - avg_purchase_price) / avg_purchase_price) * 100 if avg_purchase_price > 0 else 0
        fx_return_pct = ((fx_rate_current - avg_fx_at_purchase) / avg_fx_at_purchase) * 100 if avg_fx_at_purchase > 0 else 0
        total_return_pct = ((current_value_base - cost_basis_base) / cost_basis_base) * 100 if cost_basis_base > 0 else 0

        # Calculate gains in base currency
        local_gain_base = (current_price - avg_purchase_price) * holding_data["quantity"] * avg_fx_at_purchase
        fx_gain_base = cost_basis_original * (fx_rate_current - avg_fx_at_purchase)

        # Holding period
        holding_period_days = (now - earliest_purchase_date).days if earliest_purchase_date else 0
        is_long_term = holding_period_days >= 365

        # Annualized return
        if holding_period_days > 0:
            years = holding_period_days / 365.0
            annualized_return = (((current_value_base / cost_basis_base) ** (1 / years)) - 1) * 100 if cost_basis_base > 0 else 0
        else:
            annualized_return = 0

        # Add to totals
        total_cost_basis_base += cost_basis_base
        total_current_value_base += current_value_base

        # By currency
        by_currency[trade_currency]["value_base"] += current_value_base
        by_currency[trade_currency]["cost_basis_base"] += cost_basis_base
        by_currency[trade_currency]["local_gain"] += local_gain_base
        by_currency[trade_currency]["fx_gain"] += fx_gain_base

        # By asset type
        by_asset_type[asset.type]["value_base"] += current_value_base
        by_asset_type[asset.type]["cost_basis_base"] += cost_basis_base

        # Create holding analysis
        holding_analysis = {
            "ticker": asset.symbol,
            "asset_name": asset.name,
            "purchase_date": earliest_purchase_date.strftime("%Y-%m-%d") if earliest_purchase_date else None,
            "original_currency": trade_currency,
            "purchase_price_original": round(avg_purchase_price, 2),
            "current_price_original": round(current_price, 2),
            "quantity": holding_data["quantity"],
            "fx_rate_at_purchase": round(avg_fx_at_purchase, 6),
            "fx_rate_current": round(fx_rate_current, 6),
            "cost_basis_original": round(cost_basis_original, 2),
            "cost_basis_base": round(cost_basis_base, 2),
            "current_value_original": round(current_value_original, 2),
            "current_value_base": round(current_value_base, 2),
            "unrealized_gain_loss_base": round(current_value_base - cost_basis_base, 2),
            "unrealized_gain_loss_pct": round(total_return_pct, 2),
            "local_return_pct": round(local_return_pct, 2),
            "fx_return_pct": round(fx_return_pct, 2),
            "total_return_pct": round(total_return_pct, 2),
            "holding_period_days": holding_period_days,
            "is_long_term": is_long_term,
            "annualized_return": round(annualized_return, 2),
            "weight_pct": 0,  # Will calculate after totals
            "asset_type": asset.type
        }
        holdings_analysis.append(holding_analysis)

    # Calculate weights
    for holding in holdings_analysis:
        holding["weight_pct"] = round((holding["current_value_base"] / total_current_value_base) * 100, 2) if total_current_value_base > 0 else 0

    # Calculate portfolio-level metrics
    total_unrealized_gain_loss = total_current_value_base - total_cost_basis_base
    total_unrealized_gain_loss_pct = (total_unrealized_gain_loss / total_cost_basis_base) * 100 if total_cost_basis_base > 0 else 0

    # Calculate currency impact summary
    total_local_gain = sum(curr_data["local_gain"] for curr_data in by_currency.values())
    total_fx_gain = sum(curr_data["fx_gain"] for curr_data in by_currency.values())

    # Benchmark comparison
    benchmark_return = 0
    alpha = 0
    try:
        bench_ticker = yf.Ticker(benchmark_ticker)
        # Get benchmark data for the earliest holding
        if holdings_analysis:
            earliest_date = min(h["purchase_date"] for h in holdings_analysis if h["purchase_date"])
            bench_hist = bench_ticker.history(start=earliest_date, end=now)
            if not bench_hist.empty:
                start_price = bench_hist["Close"].iloc[0]
                end_price = bench_hist["Close"].iloc[-1]
                benchmark_return = ((end_price / start_price) - 1) * 100
                alpha = total_unrealized_gain_loss_pct - benchmark_return
    except:
        print("Failed to fetch benchmark data")

    # Format by_currency for output
    by_currency_output = {}
    for currency, data in by_currency.items():
        local_return = (data["local_gain"] / data["cost_basis_base"]) * 100 if data["cost_basis_base"] > 0 else 0
        fx_return = (data["fx_gain"] / data["cost_basis_base"]) * 100 if data["cost_basis_base"] > 0 else 0
        total_return = ((data["value_base"] - data["cost_basis_base"]) / data["cost_basis_base"]) * 100 if data["cost_basis_base"] > 0 else 0

        by_currency_output[currency] = {
            "value_base": round(data["value_base"], 2),
            "cost_basis_base": round(data["cost_basis_base"], 2),
            "weight_pct": round((data["value_base"] / total_current_value_base) * 100, 2) if total_current_value_base > 0 else 0,
            "local_return_pct": round(local_return, 2),
            "fx_return_pct": round(fx_return, 2),
            "total_return_pct": round(total_return, 2)
        }

    # Format by_asset_type for output
    by_asset_type_output = {}
    for asset_type, data in by_asset_type.items():
        by_asset_type_output[asset_type] = {
            "value_base": round(data["value_base"], 2),
            "cost_basis_base": round(data["cost_basis_base"], 2),
            "weight_pct": round((data["value_base"] / total_current_value_base) * 100, 2) if total_current_value_base > 0 else 0
        }

    # Top and bottom performers
    sorted_holdings = sorted(holdings_analysis, key=lambda x: x["total_return_pct"], reverse=True)
    top_performers = [{"ticker": h["ticker"], "total_return_pct": h["total_return_pct"]} for h in sorted_holdings[:5]]
    bottom_performers = [{"ticker": h["ticker"], "total_return_pct": h["total_return_pct"]} for h in sorted_holdings[-5:]]

    return {
        "report_date": report_date,
        "base_currency": base_currency,
        "exchange_rates_current": {k: round(v, 6) for k, v in exchange_rates_current.items()},
        "portfolio_summary": {
            "total_cost_basis": round(total_cost_basis_base, 2),
            "total_current_value": round(total_current_value_base, 2),
            "total_unrealized_gain_loss": round(total_unrealized_gain_loss, 2),
            "total_unrealized_gain_loss_pct": round(total_unrealized_gain_loss_pct, 2),
            "total_dividends_received": round(total_dividends_base, 2),
            "total_return_with_dividends": round(total_unrealized_gain_loss_pct, 2),  # Same as unrealized for now
            "benchmark_ticker": benchmark_ticker,
            "benchmark_return": round(benchmark_return, 2),
            "alpha": round(alpha, 2),
            "currency_impact_summary": {
                "total_fx_gain_loss": round(total_fx_gain, 2),
                "total_fx_contribution_pct": round((total_fx_gain / total_cost_basis_base) * 100, 2) if total_cost_basis_base > 0 else 0,
                "total_local_contribution_pct": round((total_local_gain / total_cost_basis_base) * 100, 2) if total_cost_basis_base > 0 else 0
            }
        },
        "holdings": holdings_analysis,
        "by_currency": by_currency_output,
        "by_asset_type": by_asset_type_output,
        "top_performers": top_performers,
        "bottom_performers": bottom_performers,
        "fx_warnings": fx_warnings[:10]  # Limit warnings
    }