"""
FX helpers for scoring.

Only the *series* lookup lives here. Point-in-time FX (the rate at a single
trade date) is implemented in `routers/reports.py`, which owns the personal
FIFO cost-basis frame and runs every blocking lookup through a worker thread.
Keeping a second point-in-time implementation here would mean two FX code
paths that can drift apart.
"""

import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def _naive_index(series: pd.Series) -> pd.Series:
    """Strip any timezone from the index so it compares against naive datetimes."""
    if series.index.tz is not None:
        series.index = series.index.tz_localize(None)
    return series


def get_historical_fx_series(
    from_currency: str, to_currency: str, start_date: datetime, end_date: datetime
) -> pd.Series:
    """
    Fetch a continuous daily FX rate series over [start_date, end_date].

    Unlike a point-in-time lookup for a single date, this returns a full pandas
    Series indexed by date, intended for converting an asset's daily price series
    to base_currency day-by-day (e.g. for scoring/volatility use cases where a
    single spot rate would be misleading).

    Caller is responsible for skipping this call entirely when
    from_currency == to_currency. Never raises — returns an empty Series
    (dtype=float) if no data could be fetched from either the direct or inverse
    currency pair; callers should treat an empty result as "FX unavailable" and
    fall back to a rate of 1.0 with a warning.

    This is a blocking network call: dispatch it to a worker thread.
    """
    candidates = (
        # Direct pair (e.g., THBUSD=X), then the inverse
        (f"{from_currency}{to_currency}=X", False),
        (f"{to_currency}{from_currency}=X", True),
    )
    for pair, invert in candidates:
        try:
            hist = yf.Ticker(pair).history(
                start=start_date - timedelta(days=7), end=end_date + timedelta(days=1)
            )
        except Exception:
            logger.warning("Failed to fetch %s series", pair, exc_info=True)
            continue

        if hist.empty:
            continue

        close = hist["Close"].astype(float)
        return _naive_index(1.0 / close if invert else close)

    # Final fallback — empty series signals "unavailable" to the caller
    return pd.Series(dtype=float)
