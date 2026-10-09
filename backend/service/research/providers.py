"""Read-only market tools. Missing or stale observations are never invented."""

import asyncio
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlparse
from xml.etree import ElementTree

import httpx
import yfinance as yf

from models.research import MarketSnapshot

TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
)
TREASURY_DOC = "https://home.treasury.gov/treasury-daily-interest-rate-xml-feed"


def safe_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme in ("https", "http")
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        return False


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def stock_snapshot_sync(symbol: str) -> MarketSnapshot:
    if not re.fullmatch(r"[A-Za-z0-9.^=-]{1,20}", symbol):
        raise ValueError("Use a valid US stock or ETF ticker, for example AAPL or SPY")
    symbol = symbol.upper()
    ticker = yf.Ticker(symbol)
    info = ticker.get_info()
    now = datetime.now(UTC)
    timestamp = number(info.get("regularMarketTime"))
    observed = datetime.fromtimestamp(timestamp, UTC) if timestamp else None
    currency = str(info.get("currency") or "unknown")
    fields = {
        "price": "regularMarketPrice",
        "previous_close": "regularMarketPreviousClose",
        "market_cap": "marketCap",
        "trailing_pe": "trailingPE",
        "forward_pe": "forwardPE",
        "expense_ratio": "annualReportExpenseRatio",
        "free_cash_flow": "freeCashflow",
        "total_debt": "totalDebt",
        "total_cash": "totalCash",
        "revenue_growth": "revenueGrowth",
        "profit_margin": "profitMargins",
        "return_on_equity": "returnOnEquity",
    }
    values: dict[str, Any] = {key: number(info.get(source)) for key, source in fields.items()}
    values.update(
        name=info.get("shortName"), currency=currency, instrument_type=info.get("quoteType")
    )
    cap, fcf = values["market_cap"], values["free_cash_flow"]
    values["free_cash_flow_yield"] = (
        fcf / cap
        if cap and cap > 0 and fcf is not None and info.get("quoteType") == "EQUITY"
        else None
    )
    warnings = [
        "Public Yahoo data may be delayed. Fundamentals may refer to different reporting periods."
    ]
    if not observed or now - observed > timedelta(days=4):
        warnings.append("Price observation is stale or its timestamp is unavailable.")
    if values["price"] is None:
        warnings.append("No usable price returned for this ticker.")
    return MarketSnapshot(
        kind="stock_etf",
        symbol=symbol,
        observed_at=observed.isoformat() if observed else None,
        retrieved_at=now.isoformat(),
        source_url=f"https://finance.yahoo.com/quote/{quote(symbol, safe='')}/",
        values=values,
        units={
            "price": currency,
            "previous_close": currency,
            "market_cap": currency,
            "free_cash_flow": currency,
            "total_debt": currency,
            "total_cash": currency,
            "free_cash_flow_yield": "fraction",
            "revenue_growth": "fraction",
            "profit_margin": "fraction",
            "return_on_equity": "fraction",
            "trailing_pe": "ratio",
            "forward_pe": "ratio",
            "expense_ratio": "fraction",
        },
        definitions={
            "expense_ratio": "Annual expense ratio as reported by the provider; fraction, not percent",
            "free_cash_flow_yield": "Provider free cash flow divided by current market capitalization; reporting periods must be verified in filings.",
            "price": "Last regular-market price reported by Yahoo; not an executable quote",
        },
        warnings=warnings,
    )


async def stock_snapshot(symbol: str) -> MarketSnapshot:
    return await asyncio.wait_for(asyncio.to_thread(stock_snapshot_sync, symbol), timeout=25)


def parse_treasury(xml: bytes, kind: str, now: datetime) -> MarketSnapshot:
    # ElementTree does not resolve external entities. Reject DTDs and oversized responses.
    if len(xml) > 4_000_000 or b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise ValueError("Treasury returned an unsupported XML document")
    root = ElementTree.fromstring(xml)
    rows: list[tuple[str, dict[str, float | None]]] = []
    for entry in root.iter():
        if entry.tag.rsplit("}", 1)[-1] != "properties":
            continue
        fields = {node.tag.rsplit("}", 1)[-1]: node.text for node in entry}
        date = fields.get("NEW_DATE") or fields.get("INDEX_DATE")
        if not date:
            continue
        values = {
            key: number(value) for key, value in fields.items() if key.startswith(("BC_", "ROUND_"))
        }
        if values and date[:10] <= now.date().isoformat():
            rows.append((date[:10], values))
    if not rows:
        raise ValueError("Treasury returned no usable observations")
    observed, values = max(rows, key=lambda row: row[0])
    warnings = []
    if (now.date() - datetime.fromisoformat(observed).date()).days > 4:
        warnings.append("Treasury observation is more than four calendar days old.")
    feed = "daily_treasury_bill_rates" if kind == "bills" else "daily_treasury_yield_curve"
    return MarketSnapshot(
        kind=f"treasury_{kind}",
        observed_at=observed,
        retrieved_at=now.isoformat(),
        source_url=f"{TREASURY_URL}?data={feed}&field_tdr_date_value={observed[:4]}",
        values=values,
        units=dict.fromkeys(values, "percent per annum"),
        definitions={
            "par_yields": "BC_* fields are constant-maturity Treasury par yields, not individual bond prices or yields to maturity.",
            "bill_yields": "ROUND_B* fields are bank-discount rates; ROUND_CE* fields are coupon-equivalent yields. Compare like yield conventions only.",
        },
        warnings=warnings,
    )


async def treasury_snapshot(kind: str) -> MarketSnapshot:
    if kind not in ("curve", "bills"):
        raise ValueError("Treasury kind must be curve or bills")
    now = datetime.now(UTC)
    feed = "daily_treasury_bill_rates" if kind == "bills" else "daily_treasury_yield_curve"
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        # Include the previous year around New Year's Day when no new observation exists yet.
        for year in (now.year, now.year - 1):
            response = await client.get(
                TREASURY_URL, params={"data": feed, "field_tdr_date_value": year}
            )
            response.raise_for_status()
            try:
                return parse_treasury(response.content, kind, now)
            except ValueError:
                if year != now.year or now.month != 1:
                    raise
    raise ValueError("Treasury observations are unavailable")
