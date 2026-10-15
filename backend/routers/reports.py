import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException
from forex_python.converter import CurrencyRates
from sqlalchemy.ext.asyncio import AsyncSession

import models.users as user_schema
from db import service
from db.dependencies import get_current_active_user, get_db
from service.scoring import calculate_performance_scores

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Reports"])

# Initialize the currency converter
c = CurrencyRates()

# yfinance and forex-python are synchronous, so every call below is dispatched to
# a worker thread and never blocks the event loop. This caps how many run at once.
_MAX_CONCURRENT_FETCHES = 8


def _user_group_ids(current_user: user_schema.User) -> list[int]:
    """
    The group IDs the current user belongs to.

    Trades are owned by a group (see `Trade.group_id`), so every report must be
    restricted to these IDs. Admins get no special treatment here, matching the
    membership checks in the trades router.
    """
    return [group.id for group in current_user.groups]


async def _run_in_threads(calls: Sequence[tuple[Callable[..., Any], tuple[Any, ...]]]) -> list[Any]:
    """Run blocking callables in worker threads, `_MAX_CONCURRENT_FETCHES` at a time."""
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_FETCHES)

    async def run(fn: Callable[..., Any], args: tuple[Any, ...]) -> Any:
        async with semaphore:
            return await asyncio.to_thread(fn, *args)

    return list(await asyncio.gather(*(run(fn, args) for fn, args in calls)))


# =================================================================
# === BLOCKING LOOKUPS (always called via a worker thread) ===
# =================================================================


def _blocking_rate(from_currency: str, to_currency: str) -> float | None:
    """Current FX rate, or None if the upstream provider cannot supply it."""
    if from_currency == to_currency:
        return 1.0
    try:
        return float(c.get_rate(from_currency, to_currency))
    except Exception:
        logger.warning("FX rate %s->%s unavailable", from_currency, to_currency, exc_info=True)
        return None


def _nearest_row_label(index: pd.DatetimeIndex, date: datetime) -> Any:
    """
    Label of the last row at or before `date`, falling back to the first row.

    yfinance returns a tz-aware index while trade dates come out of MySQL naive;
    comparing the two raises TypeError, so align them before comparing.
    """
    target = pd.Timestamp(date)
    if index.tz is not None:
        target = (
            target.tz_localize(index.tz) if target.tzinfo is None else target.tz_convert(index.tz)
        )
    elif target.tzinfo is not None:
        target = target.tz_localize(None)

    earlier = index[index <= target]
    return earlier[-1] if len(earlier) else index[0]


def _history_rate(pair: str, date: datetime, invert: bool) -> tuple[float, datetime] | None:
    """Close price for `pair` at (or just before) `date`, with the date actually used."""
    # Fetch a week of data to handle weekends/holidays
    hist = yf.Ticker(pair).history(start=date - timedelta(days=7), end=date + timedelta(days=1))
    if hist.empty:
        return None

    label = _nearest_row_label(hist.index, date)
    close = float(hist.loc[label, "Close"])
    if close == 0:
        return None

    return (1.0 / close if invert else close), label.to_pydatetime()


def _blocking_historical_fx(
    from_currency: str, to_currency: str, date: datetime, now: datetime
) -> dict[str, Any]:
    """Historical FX rate at `date`, degrading to the current rate and then to 1.0."""
    if from_currency == to_currency:
        return {
            "rate": 1.0,
            "actual_date": date.strftime("%Y-%m-%d"),
            "source": "same_currency",
            "warning": None,
        }

    candidates = (
        # Direct pair (e.g., THBUSD=X), then the inverse
        (f"{from_currency}{to_currency}=X", False, "yfinance"),
        (f"{to_currency}{from_currency}=X", True, "yfinance_inverse"),
    )
    for pair, invert, source in candidates:
        try:
            found = _history_rate(pair, date, invert)
        except Exception:
            logger.warning("Failed to fetch %s history", pair, exc_info=True)
            continue

        if found is None:
            continue

        rate, actual_date = found
        return {
            "rate": rate,
            "actual_date": actual_date.strftime("%Y-%m-%d"),
            "source": source,
            "warning": None
            if actual_date.date() == date.date()
            else f"Used {actual_date.date()} (nearest to {date.date()})",
        }

    # Fallback to the current rate if the historical one is not available
    current_rate = _blocking_rate(from_currency, to_currency)
    if current_rate is not None:
        return {
            "rate": current_rate,
            "actual_date": now.strftime("%Y-%m-%d"),
            "source": "fallback_current",
            "warning": f"Historical FX rate unavailable for {date.date()}, using current rate",
        }

    return {
        "rate": 1.0,
        "actual_date": date.strftime("%Y-%m-%d"),
        "source": "fallback_default",
        "warning": "FX rate unavailable, using 1.0",
    }


def _blocking_current_price(symbol: str) -> float:
    """Latest price for `symbol`, or 0.0 if yfinance has nothing usable."""
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.info.get("regularMarketPrice") or 0
        if not price:
            hist = ticker.history(period="1d")
            price = hist["Close"].iloc[-1] if not hist.empty else 0
        return float(price or 0)
    except Exception:
        logger.warning("Failed to fetch current price for %s", symbol, exc_info=True)
        return 0.0


def _blocking_asset_currency(symbol: str) -> str | None:
    """The currency yfinance reports for `symbol`, or None when the lookup fails."""
    try:
        return str(yf.Ticker(symbol).info.get("currency", "USD")).upper()
    except Exception:
        logger.warning("Failed to fetch currency for %s", symbol, exc_info=True)
        return None


def _blocking_benchmark_return(symbol: str, start: str, end: datetime) -> float | None:
    """Percent return of `symbol` between `start` and `end`, or None on failure."""
    try:
        hist = yf.Ticker(symbol).history(start=start, end=end)
        if hist.empty:
            return None
        start_price = float(hist["Close"].iloc[0])
        end_price = float(hist["Close"].iloc[-1])
        if start_price == 0:
            return None
        return ((end_price / start_price) - 1) * 100
    except Exception:
        logger.warning("Failed to fetch benchmark data for %s", symbol, exc_info=True)
        return None


async def _rates_to_usd(currencies: Sequence[str]) -> dict[str, float]:
    """Current rates to USD for each currency, fetched concurrently. 503 if any is missing."""
    wanted = sorted({currency.upper() for currency in currencies} - {"USD"})
    results = await _run_in_threads([(_blocking_rate, (currency, "USD")) for currency in wanted])

    rates = {"USD": 1.0}
    for currency, rate in zip(wanted, results, strict=True):
        if rate is None:
            raise HTTPException(
                status_code=503,
                detail=f"Exchange rate from {currency} to USD is unavailable.",
            )
        rates[currency] = rate
    return rates


@router.get("/valuation/{symbol}/{target_currency}")
async def get_portfolio_valuation_by_symbol(
    symbol: str,
    target_currency: str,
    db: AsyncSession = Depends(get_db),
    current_user: user_schema.User = Depends(get_current_active_user),
):
    """
    Calculates the valuation of a specific asset holding in a target currency.

    Only trades belonging to the current user's groups are included.

    - `symbol`: The asset symbol (e.g., 'AAPL').
    - `target_currency`: The currency for the report (e.g., 'THB', 'EUR').
    """
    target_currency = target_currency.upper()

    # 1. Get the asset and the user's trades for it from the database
    asset = await service.get_asset_by_symbol(db, symbol=symbol.upper())
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    trades = await service.get_trades_by_asset_id_for_groups(
        db, asset_id=asset.id, group_ids=_user_group_ids(current_user)
    )
    if not trades:
        raise HTTPException(status_code=404, detail="No trades found for this asset")

    # 2. Calculate total holdings and cost basis in USD.
    # Each trade is priced in its own `currency`, so convert before summing —
    # `price_per_unit` is NOT USD unless the trade says so.
    total_quantity = 0
    total_cost_usd = 0
    trade_rates = await _rates_to_usd([trade.currency for trade in trades])

    for trade in trades:
        trade_value_usd = (
            trade.quantity * trade.price_per_unit * trade_rates[trade.currency.upper()]
        )
        if trade.trade_type == "buy":
            total_quantity += trade.quantity
            total_cost_usd += trade_value_usd
        elif trade.trade_type == "sell":
            total_quantity -= trade.quantity
            total_cost_usd -= trade_value_usd

    if total_quantity <= 0:
        return {"message": "No active holdings for this asset."}

    avg_cost_usd = total_cost_usd / total_quantity

    # 3. Determine the asset's currency
    # Since assets table doesn't have currency, we'll infer it from:
    # 1. yfinance data, or 2. market field, or 3. default to USD
    asset_currency = await asyncio.to_thread(_blocking_asset_currency, asset.symbol)
    if asset_currency is None:
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
    asset_rates = await _rates_to_usd([asset_currency])
    current_value_usd = current_value_native * asset_rates[asset_currency]

    # 6. Get the CURRENT exchange rate to convert from USD to the TARGET currency
    usd_to_target_rate = await asyncio.to_thread(_blocking_rate, "USD", target_currency)
    if usd_to_target_rate is None:
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
        "reporting_currency": target_currency,
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
    risk_free_rate: float | None = None,
    lookback_period: str = "1y",
    db: AsyncSession = Depends(get_db),
    current_user: user_schema.User = Depends(get_current_active_user),
):
    """
    Comprehensive portfolio performance analysis with multi-currency support.

    Only trades belonging to the current user's groups are included.

    Features:
    - Historical FX rates at trade date for accurate cost basis
    - Return attribution (local return vs FX return)
    - Benchmark comparison and alpha calculation
    - Grouping by currency and asset type
    - Top/bottom performers
    - Annualized returns
    - Risk-adjusted performance scoring (CAGR, Sharpe, Sortino, max drawdown,
      beta/alpha vs benchmark) computed over `lookback_period`, both per-holding
      and for the portfolio as a whole (value-weighted daily return series)

    Args:
        base_currency: Currency for reporting (default: USD)
        benchmark_ticker: Benchmark index (default: SPY)
        risk_free_rate: Annualized risk-free rate as a decimal (e.g. 0.045). If not
            provided, it is fetched from ^IRX with a static fallback.
        lookback_period: History window used for scoring metrics only (yfinance
            period string, e.g. "1y", "6mo", "2y"). Independent of the FIFO
            cost-basis calculations above, which always use full trade history.
    """

    # Naive UTC, to stay comparable with the naive `trade_date` column
    now = datetime.now(UTC).replace(tzinfo=None)
    report_date = now.strftime("%Y-%m-%d")

    fx_warnings: list[dict[str, str]] = []

    def fx_cache_key(from_currency: str, date: datetime) -> str:
        return f"{from_currency}{base_currency}_{date.strftime('%Y-%m-%d')}"

    logger.info(
        "[Portfolio Performance Analysis] Report Date: %s, Base Currency: %s",
        report_date,
        base_currency,
    )

    # Fetch the user's trades and all assets (set high limit to get all records)
    all_trades = await service.get_trades_by_group_ids(
        db, group_ids=_user_group_ids(current_user), skip=0, limit=10000
    )
    all_assets = await service.get_all_assets(db, skip=0, limit=10000)
    assets_dict = {asset.id: asset for asset in all_assets}

    # Group trades by asset to calculate holdings
    holdings_by_asset: defaultdict[int, dict[str, Any]] = defaultdict(
        lambda: {"buys": [], "sells": [], "quantity": 0}
    )

    for trade in all_trades:
        if trade.trade_type == "buy":
            holdings_by_asset[trade.asset_id]["buys"].append(trade)
            holdings_by_asset[trade.asset_id]["quantity"] += trade.quantity
        elif trade.trade_type == "sell":
            holdings_by_asset[trade.asset_id]["sells"].append(trade)
            holdings_by_asset[trade.asset_id]["quantity"] -= trade.quantity

    # Resolve each open position into FIFO lots first, so the FX prefetch below
    # only covers the buy trades that actually make up the remaining holding.
    lots_by_asset: dict[int, list[tuple[Any, float]]] = {}
    for asset_id, holding_data in holdings_by_asset.items():
        if holding_data["quantity"] <= 0:
            continue  # Skip sold or zero positions
        if asset_id not in assets_dict:
            continue

        # FIFO: sells consume the earliest buys first; what is left is the open lots.
        quantity_to_consume = sum(sell.quantity for sell in holding_data["sells"])
        lots: list[tuple[Any, float]] = []
        for buy_trade in sorted(holding_data["buys"], key=lambda x: x.trade_date):
            consumed = min(buy_trade.quantity, quantity_to_consume)
            quantity_to_consume -= consumed
            if buy_trade.quantity > consumed:
                lots.append((buy_trade, buy_trade.quantity - consumed))

        if lots:
            lots_by_asset[asset_id] = lots

    # --- Prefetch every blocking lookup concurrently -------------------------

    # Historical FX, one call per distinct (currency, date)
    fx_requests: dict[str, tuple[str, datetime]] = {}
    for lots in lots_by_asset.values():
        for buy_trade, _qty in lots:
            fx_requests.setdefault(
                fx_cache_key(buy_trade.currency, buy_trade.trade_date),
                (buy_trade.currency, buy_trade.trade_date),
            )

    fx_keys = list(fx_requests)
    fx_results = await _run_in_threads(
        [
            (
                _blocking_historical_fx,
                (fx_requests[key][0], base_currency, fx_requests[key][1], now),
            )
            for key in fx_keys
        ]
    )
    fx_cache: dict[str, dict[str, Any]] = dict(zip(fx_keys, fx_results, strict=True))

    # Current FX rates
    currencies_in_portfolio = set()
    for holding_data in holdings_by_asset.values():
        if holding_data["quantity"] > 0:
            for trade in holding_data["buys"]:
                currencies_in_portfolio.add(trade.currency)

    rate_currencies = sorted(
        currency for currency in currencies_in_portfolio if currency != base_currency
    )
    rate_results = await _run_in_threads(
        [(_blocking_rate, (currency, base_currency)) for currency in rate_currencies]
    )

    exchange_rates_current = {base_currency: 1.0}
    for currency, rate in zip(rate_currencies, rate_results, strict=True):
        if rate is None:
            # Don't fall back to 1.0 silently — the numbers would look plausible
            exchange_rates_current[currency] = 1.0
            fx_warnings.append(
                {
                    "ticker": currency,
                    "message": (
                        f"Current FX rate {currency}->{base_currency} unavailable, using 1.0"
                    ),
                }
            )
        else:
            exchange_rates_current[currency] = rate

    logger.info("Current exchange rates: %s", exchange_rates_current)

    # Current prices, only for assets with no stored price
    price_symbols = [
        assets_dict[asset_id].symbol
        for asset_id in lots_by_asset
        if not assets_dict[asset_id].current_price
    ]
    price_results = await _run_in_threads(
        [(_blocking_current_price, (symbol,)) for symbol in price_symbols]
    )
    fetched_prices = dict(zip(price_symbols, price_results, strict=True))

    # --- Analyze each holding ------------------------------------------------

    holdings_analysis = []
    total_cost_basis_base = 0.0
    total_current_value_base = 0.0
    total_dividends_base = 0.0  # TODO: dividends are not calculated yet (always 0)

    by_currency: defaultdict[str, dict[str, float]] = defaultdict(
        lambda: {"value_base": 0, "cost_basis_base": 0, "local_gain": 0, "fx_gain": 0}
    )
    by_asset_type: defaultdict[str, dict[str, float]] = defaultdict(
        lambda: {"value_base": 0, "cost_basis_base": 0}
    )

    for asset_id, lots in lots_by_asset.items():
        holding_data = holdings_by_asset[asset_id]
        asset = assets_dict[asset_id]

        # Calculate FIFO cost basis with historical FX rates
        cost_basis_base = 0
        weighted_fx_at_purchase = 0
        weighted_purchase_price = 0
        earliest_purchase_date = None
        total_quantity_for_weighting = 0.0

        for buy_trade, qty_from_this_trade in lots:
            fx_data = fx_cache[fx_cache_key(buy_trade.currency, buy_trade.trade_date)]
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

        if total_quantity_for_weighting == 0:
            continue

        avg_fx_at_purchase = weighted_fx_at_purchase / total_quantity_for_weighting
        avg_purchase_price = weighted_purchase_price / total_quantity_for_weighting
        trade_currency = holding_data["buys"][0].currency

        # Get current price
        current_price = asset.current_price or fetched_prices.get(asset.symbol, 0)
        if not current_price:
            continue

        # Current value using current FX rate
        fx_rate_current = exchange_rates_current.get(trade_currency, 1.0)
        current_value_original = current_price * holding_data["quantity"]
        current_value_base = current_value_original * fx_rate_current

        cost_basis_original = avg_purchase_price * holding_data["quantity"]

        # Return attribution
        local_return_pct = (
            ((current_price - avg_purchase_price) / avg_purchase_price) * 100
            if avg_purchase_price > 0
            else 0
        )
        fx_return_pct = (
            ((fx_rate_current - avg_fx_at_purchase) / avg_fx_at_purchase) * 100
            if avg_fx_at_purchase > 0
            else 0
        )
        total_return_pct = (
            ((current_value_base - cost_basis_base) / cost_basis_base) * 100
            if cost_basis_base > 0
            else 0
        )

        # Calculate gains in base currency
        local_gain_base = (
            (current_price - avg_purchase_price) * holding_data["quantity"] * avg_fx_at_purchase
        )
        fx_gain_base = cost_basis_original * (fx_rate_current - avg_fx_at_purchase)

        # Holding period
        holding_period_days = (now - earliest_purchase_date).days if earliest_purchase_date else 0
        is_long_term = holding_period_days >= 365

        # Annualized return
        if holding_period_days > 0:
            years = holding_period_days / 365.0
            annualized_return = (
                (((current_value_base / cost_basis_base) ** (1 / years)) - 1) * 100
                if cost_basis_base > 0
                else 0
            )
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
            "purchase_date": earliest_purchase_date.strftime("%Y-%m-%d")
            if earliest_purchase_date
            else None,
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
            "asset_type": asset.type,
        }
        holdings_analysis.append(holding_analysis)

    # Calculate weights
    for holding in holdings_analysis:
        holding["weight_pct"] = (
            round((holding["current_value_base"] / total_current_value_base) * 100, 2)
            if total_current_value_base > 0
            else 0
        )

    # Calculate portfolio-level metrics
    total_unrealized_gain_loss = total_current_value_base - total_cost_basis_base
    total_unrealized_gain_loss_pct = (
        (total_unrealized_gain_loss / total_cost_basis_base) * 100
        if total_cost_basis_base > 0
        else 0
    )

    # Calculate currency impact summary
    total_local_gain = sum(curr_data["local_gain"] for curr_data in by_currency.values())
    total_fx_gain = sum(curr_data["fx_gain"] for curr_data in by_currency.values())

    # Benchmark comparison
    benchmark_return = 0.0
    alpha = 0.0
    purchase_dates = [h["purchase_date"] for h in holdings_analysis if h["purchase_date"]]
    if purchase_dates:
        # Get benchmark data for the earliest holding
        fetched_return = await asyncio.to_thread(
            _blocking_benchmark_return, benchmark_ticker, min(purchase_dates), now
        )
        if fetched_return is not None:
            benchmark_return = fetched_return
            alpha = total_unrealized_gain_loss_pct - benchmark_return

    # Format by_currency for output
    by_currency_output = {}
    for currency, data in by_currency.items():
        local_return = (
            (data["local_gain"] / data["cost_basis_base"]) * 100
            if data["cost_basis_base"] > 0
            else 0
        )
        fx_return = (
            (data["fx_gain"] / data["cost_basis_base"]) * 100 if data["cost_basis_base"] > 0 else 0
        )
        total_return = (
            ((data["value_base"] - data["cost_basis_base"]) / data["cost_basis_base"]) * 100
            if data["cost_basis_base"] > 0
            else 0
        )

        by_currency_output[currency] = {
            "value_base": round(data["value_base"], 2),
            "cost_basis_base": round(data["cost_basis_base"], 2),
            "weight_pct": round((data["value_base"] / total_current_value_base) * 100, 2)
            if total_current_value_base > 0
            else 0,
            "local_return_pct": round(local_return, 2),
            "fx_return_pct": round(fx_return, 2),
            "total_return_pct": round(total_return, 2),
        }

    # Format by_asset_type for output
    by_asset_type_output = {}
    for asset_type, data in by_asset_type.items():
        by_asset_type_output[asset_type] = {
            "value_base": round(data["value_base"], 2),
            "cost_basis_base": round(data["cost_basis_base"], 2),
            "weight_pct": round((data["value_base"] / total_current_value_base) * 100, 2)
            if total_current_value_base > 0
            else 0,
        }

    # Top and bottom performers
    sorted_holdings = sorted(holdings_analysis, key=lambda x: x["total_return_pct"], reverse=True)
    top_performers = [
        {"ticker": h["ticker"], "total_return_pct": h["total_return_pct"]}
        for h in sorted_holdings[:5]
    ]
    bottom_sorted = sorted(holdings_analysis, key=lambda x: x["total_return_pct"])  # worst first
    bottom_performers = [
        {"ticker": h["ticker"], "total_return_pct": h["total_return_pct"]}
        for h in bottom_sorted[:5]
    ]

    # --- Risk-adjusted performance scoring (additive only) -------------------
    # Uses a separate return frame (fixed lookback_period) from the FIFO
    # cost-basis calculations above. Never raises: falls back to a null shape
    # with a warning. calculate_performance_scores is fully synchronous
    # (yfinance), so it runs in a worker thread like every other blocking call.
    scoring_input = [
        {
            "ticker": h["ticker"],
            "trade_currency": h["original_currency"],
            "weight_pct": h["weight_pct"],
        }
        for h in holdings_analysis
    ]
    try:
        scores_result = await asyncio.to_thread(
            calculate_performance_scores,
            scoring_input,
            base_currency,
            benchmark_ticker,
            risk_free_rate,
            lookback_period,
        )
    except Exception as e:
        logger.warning("Failed to compute performance scores", exc_info=True)
        scores_result = {
            "portfolio_score": None,
            "holdings_scores": [],
            "warnings": [{"ticker": None, "message": f"Scoring failed: {e}"}],
        }

    scores_by_ticker = {hs["ticker"]: hs for hs in scores_result["holdings_scores"]}
    for holding in holdings_analysis:
        # Adds a key; never overwrites existing keys
        holding["score"] = scores_by_ticker.get(holding["ticker"])

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
            "total_return_with_dividends": round(
                total_unrealized_gain_loss_pct, 2
            ),  # Same as unrealized for now
            "benchmark_ticker": benchmark_ticker,
            "benchmark_return": round(benchmark_return, 2),
            "alpha": round(alpha, 2),
            "currency_impact_summary": {
                "total_fx_gain_loss": round(total_fx_gain, 2),
                "total_fx_contribution_pct": round((total_fx_gain / total_cost_basis_base) * 100, 2)
                if total_cost_basis_base > 0
                else 0,
                "total_local_contribution_pct": round(
                    (total_local_gain / total_cost_basis_base) * 100, 2
                )
                if total_cost_basis_base > 0
                else 0,
            },
        },
        "holdings": holdings_analysis,
        "by_currency": by_currency_output,
        "by_asset_type": by_asset_type_output,
        "top_performers": top_performers,
        "bottom_performers": bottom_performers,
        "fx_warnings": fx_warnings[:10],  # Limit warnings
        "portfolio_score": scores_result["portfolio_score"],
        "scoring_warnings": scores_result["warnings"][:10],
    }
