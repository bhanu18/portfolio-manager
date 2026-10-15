"""Deterministic market data for offline evals: same numbers every run, no Yahoo/Treasury calls.

Model calls stay real; only the market-data tools are replaced, so score changes come from
the models and orchestration, not from moving prices.
"""

import math
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta

from models.research import MarketSnapshot
from service.research import agent as agent_module
from service.research import orchestrator as orchestrator_module
from service.research.investment import analyze

AS_OF = date(2026, 10, 14)
RETRIEVED_AT = "2026-10-15T00:00:00+00:00"
# Symbols the fixtures know; anything else behaves like an unknown ticker.
KNOWN = {
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "JPM", "KO", "BRK.B",
    "SPY", "QQQ", "VTI", "VOO", "SCHD", "TLT", "BND", "SGOV",
}  # fmt: skip
ETFS = {"SPY", "QQQ", "VTI", "VOO", "SCHD", "TLT", "BND", "SGOV"}


def seed(symbol: str) -> int:
    return zlib.crc32(symbol.encode())


def base_price(symbol: str) -> float:
    return round(20 + seed(symbol) % 480 + (seed(symbol) % 100) / 100, 2)


def history(symbol: str, sessions: int = 1460) -> tuple[list[str], list[float]]:
    """Weekday closes ending AS_OF: drift plus two cycles, so MAs cross and backtests differ."""
    dates: list[str] = []
    day = AS_OF
    while len(dates) < sessions:
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day -= timedelta(days=1)
    dates.reverse()
    phase = seed(symbol) % 360
    drift = 0.0002 + (seed(symbol) % 7) / 10000
    end = base_price(symbol)
    raw = [
        math.exp(drift * i + 0.08 * math.sin((i + phase) / 45) + 0.03 * math.sin(i / 9))
        for i in range(sessions)
    ]
    return dates, [round(end * value / raw[-1], 4) for value in raw]


def stock(symbol: str) -> MarketSnapshot:
    symbol = symbol.strip().upper()
    if symbol not in KNOWN:
        raise ValueError("Instrument not found")
    price = base_price(symbol)
    s = seed(symbol)
    etf = symbol in ETFS
    values = {
        "price": price,
        "previous_close": round(price * (1 - ((s % 21) - 10) / 1000), 2),
        "market_cap": None if etf else float(50_000_000_000 + (s % 3000) * 1_000_000_000),
        "trailing_pe": None if etf else round(12 + (s % 300) / 10, 2),
        "forward_pe": None if etf else round(10 + (s % 250) / 10, 2),
        "expense_ratio": round(0.0003 + (s % 50) / 10000, 4) if etf else None,
        "revenue_growth": None if etf else round(((s % 40) - 5) / 100, 4),
        "profit_margin": None if etf else round((s % 35) / 100, 4),
        "return_on_equity": None if etf else round((s % 60) / 100, 4),
    }
    return MarketSnapshot(
        kind="stock_etf",
        symbol=symbol,
        observed_at=AS_OF.isoformat(),
        retrieved_at=RETRIEVED_AT,
        source_url=f"https://finance.yahoo.com/quote/{symbol}/",
        values=values,
        units={"price": "USD", "previous_close": "USD", "market_cap": "USD"},
        warnings=["Offline eval fixture: synthetic values, not market data."],
    )


def investment(symbol: str) -> MarketSnapshot:
    symbol = symbol.strip().upper()
    if symbol not in KNOWN:
        raise ValueError("Instrument not found")
    dates, closes = history(symbol)
    return MarketSnapshot(
        kind="investment_analysis",
        symbol=symbol,
        observed_at=dates[-1],
        retrieved_at=RETRIEVED_AT,
        source_url=f"https://finance.yahoo.com/quote/{symbol}/history/",
        values={"observations": len(closes), "history_start": dates[0]},
        warnings=["Offline eval fixture: synthetic price history."],
        analysis=analyze(dates, closes),
    )


def treasury(kind: str) -> MarketSnapshot:
    if kind == "bills":
        values = {"ROUND_B1_CLOSE_4WK_2": 4.05, "ROUND_B1_YIELD_4WK_2": 4.13}
        values |= {"ROUND_B1_CLOSE_13WK_2": 3.98, "ROUND_B1_YIELD_13WK_2": 4.08}
        values |= {"ROUND_B1_CLOSE_26WK_2": 3.86, "ROUND_B1_YIELD_26WK_2": 3.99}
    elif kind == "curve":
        tenors = ["1MONTH", "3MONTH", "6MONTH", "1YEAR", "2YEAR", "5YEAR", "10YEAR", "30YEAR"]
        rates = [4.14, 4.06, 3.95, 3.78, 3.55, 3.61, 4.02, 4.58]
        values = {f"BC_{tenor}": rate for tenor, rate in zip(tenors, rates, strict=True)}
    else:
        raise ValueError("Treasury kind must be curve or bills")
    return MarketSnapshot(
        kind=f"treasury_{kind}",
        observed_at=AS_OF.isoformat(),
        retrieved_at=RETRIEVED_AT,
        source_url="https://home.treasury.gov/resource-center/data-chart-center/interest-rates",
        values=values,
        units=dict.fromkeys(values, "percent per annum"),
        warnings=["Offline eval fixture: synthetic rates."],
    )


async def stock_snapshot(symbol: str) -> MarketSnapshot:
    return stock(symbol)


async def investment_snapshot(symbol: str) -> MarketSnapshot:
    return investment(symbol)


async def treasury_snapshot(kind: str) -> MarketSnapshot:
    return treasury(kind)


@contextmanager
def offline_market_data() -> Iterator[None]:
    """Swap the data tools in both the orchestrator (Auto prefetch) and agents (tool calls)."""
    fakes = {
        "stock_snapshot": stock_snapshot,
        "investment_snapshot": investment_snapshot,
        "treasury_snapshot": treasury_snapshot,
    }
    modules = (orchestrator_module, agent_module)
    saved = [(module, name, getattr(module, name)) for module in modules for name in fakes]
    try:
        for module in modules:
            for name, fake in fakes.items():
                setattr(module, name, fake)
        yield
    finally:
        for module, name, original in saved:
            setattr(module, name, original)
