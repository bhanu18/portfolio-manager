"""Deterministic, long-only research simulations; no orders or model-generated math."""

import asyncio
import math
import re
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from statistics import stdev
from urllib.parse import quote

import yfinance as yf

from models.research import (
    BacktestCurvePoint,
    BacktestResult,
    InvestmentAnalysis,
    MarketSnapshot,
    TrendPoint,
)

COST = 0.001  # Combined fees/slippage: 10 basis points per entry or exit.
STRATEGIES = ("buy_hold", "price_above_sma200", "sma50_above_sma200")


def average(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = []
    total = 0.0
    for i, value in enumerate(values):
        total += value
        if i >= window:
            total -= values[i - window]
        result.append(total / window if i >= window - 1 else None)
    return result


def sample_indices(length: int, maximum: int = 160) -> list[int]:
    return (
        sorted(
            {
                round(i * (length - 1) / (min(length, maximum) - 1))
                for i in range(min(length, maximum))
            }
        )
        if length > 1
        else [0]
    )


def simulate(
    dates: list[str],
    closes: list[float],
    signals: list[bool],
    start: int,
    end: int,
    strategy: str,
    period: str,
) -> BacktestResult:
    """Signal at t close trades at t+1 close; earns returns only after that execution."""
    equity = peak = 100.0
    held = False
    trades = invested = 0
    daily: list[float] = []
    curve = [BacktestCurvePoint(date=dates[start - 1], equity=100, drawdown=0)]
    worst = 0.0
    for i in range(start, end):
        before = equity
        if held:
            equity *= closes[i] / closes[i - 1]
            invested += 1
        target = signals[i - 1]
        if held != target:
            equity *= 1 - COST
            trades += 1
            held = target
        daily.append(equity / before - 1)
        peak = max(peak, equity)
        drawdown = equity / peak - 1
        worst = min(worst, drawdown)
        curve.append(
            BacktestCurvePoint(date=dates[i], equity=round(equity, 4), drawdown=round(drawdown, 6))
        )
    years = (
        datetime.fromisoformat(dates[end - 1]) - datetime.fromisoformat(dates[start - 1])
    ).days / 365.25
    return BacktestResult(
        strategy=strategy,
        period=period,
        start=dates[start - 1],
        end=dates[end - 1],
        total_return=equity / 100 - 1,
        annualized_return=(equity / 100) ** (1 / years) - 1 if years >= 1 else None,
        max_drawdown=worst,
        annualized_volatility=stdev(daily) * math.sqrt(252) if len(daily) > 1 else None,
        trades=trades,
        time_invested=invested / len(daily),
        curve=[curve[i] for i in sample_indices(len(curve))] if period == "full" else [],
    )


def analyze(dates: list[str], closes: list[float]) -> InvestmentAnalysis:
    if len(dates) != len(closes) or len(closes) < 201:
        raise ValueError("At least 201 completed daily observations are required")
    if dates != sorted(set(dates)) or any(not math.isfinite(p) or p <= 0 for p in closes):
        raise ValueError("History must contain unique ascending dates and positive finite prices")
    sma50, sma200 = average(closes, 50), average(closes, 200)
    signals = {
        "buy_hold": [True] * len(closes),
        "price_above_sma200": [
            ma is not None and price > ma for price, ma in zip(closes, sma200, strict=True)
        ],
        "sma50_above_sma200": [
            a is not None and b is not None and a > b for a, b in zip(sma50, sma200, strict=True)
        ],
    }
    last_cross = None
    for i in range(200, len(closes)):
        if signals["sma50_above_sma200"][i] != signals["sma50_above_sma200"][i - 1]:
            last_cross = {
                "date": dates[i],
                "direction": "bullish" if signals["sma50_above_sma200"][i] else "bearish",
            }
    periods = [("full", 200, len(closes))]
    split = 200 + int((len(closes) - 200) * 0.7)
    if split - 200 >= 252 and len(closes) - split >= 252:
        periods += [("earlier_70_percent", 200, split), ("recent_30_percent", split, len(closes))]
    results = [
        simulate(dates, closes, signals[strategy], start, end, strategy, period)
        for period, start, end in periods
        for strategy in STRATEGIES
    ]
    current50, current200 = sma50[-1], sma200[-1]
    assert current50 is not None and current200 is not None

    def slope(series: list[float | None]) -> float | None:
        old = series[-21] if len(series) >= 21 else None
        latest = series[-1]
        return latest / old - 1 if old and latest is not None else None

    return InvestmentAnalysis(
        price=closes[-1],
        sma50=current50,
        sma200=current200,
        distance_sma50=closes[-1] / current50 - 1,
        distance_sma200=closes[-1] / current200 - 1,
        sma50_change_20_sessions=slope(sma50),
        sma200_change_20_sessions=slope(sma200),
        last_crossover=last_cross,
        trend=[
            TrendPoint(date=dates[i], price=closes[i], sma50=sma50[i], sma200=sma200[i])
            for i in sample_indices(len(closes))
        ],
        backtests=results,
        assumptions=[
            "Daily Yahoo close prices adjusted for splits and distributions; returns approximate dividend reinvestment.",
            "50/200 are trading-session simple moving averages. First 200 observations are warm-up.",
            "Signals at a completed close execute at the next session close; exposure starts after execution.",
            "Long-only, all-in or cash; no leverage. Cash earns 0%. Fees plus slippage: 0.10% per entry/exit.",
            "Trades counts one-way entries/exits. Open positions are marked to market without forced final liquidation.",
            "Each period starts with 100 cash. Buy-and-hold in the same instrument is the benchmark.",
            "Returns/drawdown/exposure are fractions; volatility uses 252 sessions/year; CAGR uses calendar time and is unavailable below one year.",
            "Earlier/recent periods use fixed rules without optimization; neither is an independently unseen validation dataset.",
            "Charts are sampled; all metrics use every available daily observation. Taxes and market impact excluded.",
        ],
    )


def investment_snapshot_sync(symbol: str) -> MarketSnapshot:
    if not re.fullmatch(r"[A-Za-z0-9.^=-]{1,20}", symbol):
        raise ValueError("Invalid ticker")
    symbol = symbol.upper()
    now = datetime.now(UTC)
    # Exclude today's bar even after market close to avoid incomplete bars in any US timezone.
    today = now.date()
    frame = yf.Ticker(symbol).history(
        start=(today - timedelta(days=3653 + 400)).isoformat(),
        end=today.isoformat(),
        interval="1d",
        auto_adjust=True,
        actions=False,
        timeout=20,
    )
    if frame.empty:
        raise ValueError("No price history available")
    dates = [index.date().isoformat() for index in frame.index]
    closes = [float(value) for value in frame["Close"]]
    # Keep up to ten years for evaluation plus 200 observations for warm-up.
    first = next(
        (i for i, day in enumerate(dates) if day >= (today - timedelta(days=3653)).isoformat()),
        len(dates),
    )
    offset = max(0, first - 200)
    dates, closes = dates[offset:], closes[offset:]
    if any(day >= today.isoformat() for day in dates):
        raise ValueError("Provider returned incomplete/future bars")
    analysis = analyze(dates, closes)
    warnings = [
        "Historical simulation, not a forecast. Selected surviving tickers introduce selection/survivorship bias.",
        "Adjusted history can be revised. Data is not a point-in-time institutional dataset.",
        "Zero cash yield can understate returns while out of the market; this is not a Treasury-cash strategy.",
    ]
    if (today - datetime.fromisoformat(dates[-1]).date()).days > 4:
        warnings.append("Latest historical close is more than four calendar days old.")
    if len(closes) < 200 + 252 * 5:
        warnings.append(
            "Less than five years of usable evaluation history; conclusions may be fragile."
        )
    if any(
        (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days > 7 for a, b in pairwise(dates)
    ):
        warnings.append(
            "History contains gaps longer than seven days; missing sessions were not filled."
        )
    return MarketSnapshot(
        kind="investment_analysis",
        symbol=symbol,
        observed_at=dates[-1],
        retrieved_at=now.isoformat(),
        source_url=f"https://finance.yahoo.com/quote/{quote(symbol, safe='')}/history/",
        values={"observations": len(closes), "history_start": dates[0]},
        definitions={
            "price": "Distribution- and split-adjusted close; may differ from the quoted market price."
        },
        warnings=warnings,
        analysis=analysis,
    )


async def investment_snapshot(symbol: str) -> MarketSnapshot:
    return await asyncio.wait_for(asyncio.to_thread(investment_snapshot_sync, symbol), timeout=30)
