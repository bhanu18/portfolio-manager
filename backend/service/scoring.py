"""
Risk-adjusted performance scoring for holdings and the overall portfolio.

This module answers a different question than the personal FIFO performance
report in routers/reports.py. That report answers "how has MY position done"
(actual cost basis, actual holding period, historical FX at trade date). This
module answers "how good is this ASSET on a risk-adjusted basis over a
standard lookback window" (CAGR, Sharpe, Sortino, max drawdown, beta, alpha,
volatility, all computed from the asset's own daily price series over
`lookback_period`, independent of when the user personally bought it).

The two frames are intentionally kept separate: Sharpe/Sortino/beta/alpha are
only coherent when their return numerator and their volatility/covariance
denominator come from the same daily series. Mixing a personal FIFO
holding-period return with market-based volatility would produce a
meaningless ratio.

Scoring methodology (weights, normalization bands, grade cutoffs) is a
subjective first-draft judgment call, not a derived financial standard. It is
defined entirely via the top-level constants below so it can be re-tuned
without touching calculation logic. The resulting grade should not be
presented as an objective rating.
"""

import logging

import numpy as np
import pandas as pd
import yfinance as yf

from service.currency import get_historical_fx_series

logger = logging.getLogger(__name__)

# --- Tunable constants -------------------------------------------------

DEFAULT_RISK_FREE_RATE = 0.0425
RISK_FREE_RATE_TICKER = "^IRX"  # 13-week T-bill yield, quoted in percent
TRADING_DAYS_PER_YEAR = 252

MIN_DAYS_BETA = 30  # hard floor: below this, sharpe/sortino/volatility/beta/alpha -> None
MIN_DAYS_RELIABLE_CAGR = 60  # soft floor: below this, CAGR/max_drawdown still computed but flagged

SCORE_WEIGHTS = {
    "cagr": 0.30,
    "sharpe": 0.25,
    "max_drawdown": 0.20,
    "alpha": 0.15,
    "sortino": 0.10,
}

# raw-metric -> (worst_case, best_case) used to linearly clip+scale to 0-100
NORMALIZATION_BOUNDS = {
    "cagr": (-0.20, 0.30),  # -20% to +30% annualized
    "sharpe": (-1.0, 3.0),
    "sortino": (-1.0, 4.0),
    "max_drawdown": (-0.60, 0.0),  # -60% drawdown -> 0, 0% drawdown -> 100
    "alpha": (-0.15, 0.15),
}

GRADE_BANDS = [(85, "A"), (70, "B"), (55, "C"), (40, "D"), (0, "F")]


# --- Pure math functions (no I/O; fully unit-testable) ------------------


def compute_daily_returns(price_series: pd.Series) -> pd.Series:
    """Percent change day-over-day, with the leading NaN dropped.

    Guards against a zero/NaN price (e.g. a stale or missing print from the
    data source) producing +/-inf via pct_change's division: inf values are
    treated the same as NaN and dropped, since they are not valid returns and
    would otherwise silently corrupt every downstream statistic.
    """
    if price_series is None or len(price_series) == 0:
        return pd.Series(dtype=float)
    clean = price_series.replace([np.inf, -np.inf], np.nan)
    returns = clean.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    return returns.dropna()


def returns_to_cumulative_index(daily_returns: pd.Series, start_value: float = 1.0) -> pd.Series:
    """Reconstruct a synthetic price path from a returns series (1+r).cumprod()."""
    if daily_returns is None or len(daily_returns) == 0:
        return pd.Series(dtype=float)
    return (1.0 + daily_returns).cumprod() * start_value


def compute_cagr(price_series: pd.Series) -> float | None:
    """(end/start)^(365/calendar_days) - 1. None if <2 points or start<=0.

    Uses the NaN-dropped series throughout (not just for the length check),
    since data sources commonly return a NaN for the most recent/partial bar
    and reading .iloc[0]/.iloc[-1] off the original series would silently
    compute with that NaN. Also guards against OverflowError/ValueError from
    an extreme exponent (e.g. a very short window with a large price jump)
    and against a non-finite result.
    """
    if price_series is None:
        return None
    clean = price_series.dropna()
    if len(clean) < 2:
        return None
    start = float(clean.iloc[0])
    end = float(clean.iloc[-1])
    if start <= 0 or end <= 0:
        return None
    days = (clean.index[-1] - clean.index[0]).days
    if days <= 0:
        return None
    try:
        result = (end / start) ** (365.0 / days) - 1.0
    except (OverflowError, ValueError):
        return None
    if not np.isfinite(result):
        return None
    return result


def compute_volatility(daily_returns: pd.Series) -> float | None:
    """Annualized standard deviation of daily returns. None if insufficient data."""
    if daily_returns is None or len(daily_returns) < MIN_DAYS_BETA:
        return None
    std = daily_returns.std(ddof=1)
    if std is None or pd.isna(std):
        return None
    return float(std * np.sqrt(TRADING_DAYS_PER_YEAR))


def compute_sharpe(daily_returns: pd.Series, risk_free_rate: float) -> float | None:
    """(annualized_mean_return - risk_free_rate) / annualized_volatility."""
    if daily_returns is None or len(daily_returns) < MIN_DAYS_BETA:
        return None
    volatility = compute_volatility(daily_returns)
    if volatility is None or volatility == 0:
        return None
    annualized_return = float(daily_returns.mean()) * TRADING_DAYS_PER_YEAR
    return (annualized_return - risk_free_rate) / volatility


def compute_sortino(daily_returns: pd.Series, risk_free_rate: float) -> float | None:
    """Same numerator as Sharpe; denominator is annualized downside deviation."""
    if daily_returns is None or len(daily_returns) < MIN_DAYS_BETA:
        return None
    downside = daily_returns[daily_returns < 0]
    if len(downside) == 0:
        return None
    downside_deviation = downside.std(ddof=1)
    if downside_deviation is None or pd.isna(downside_deviation) or downside_deviation == 0:
        return None
    downside_deviation_annualized = float(downside_deviation) * np.sqrt(TRADING_DAYS_PER_YEAR)
    annualized_return = float(daily_returns.mean()) * TRADING_DAYS_PER_YEAR
    return (annualized_return - risk_free_rate) / downside_deviation_annualized


def compute_max_drawdown(price_series: pd.Series) -> float | None:
    """Minimum (price - running_max) / running_max over the period. Negative fraction.

    Drops NaNs and non-positive prices first (a zero/negative print would make
    running_max 0 and produce a 0/0 division) so the result can never be NaN/inf.
    """
    if price_series is None:
        return None
    clean = price_series.dropna()
    clean = clean[clean > 0]
    if len(clean) == 0:
        return None
    running_max = clean.cummax()
    drawdown = (clean - running_max) / running_max
    result = drawdown.min()
    if result is None or pd.isna(result) or not np.isfinite(result):
        return None
    return float(result)


def compute_beta_alpha(
    asset_returns: pd.Series, benchmark_returns: pd.Series, risk_free_rate: float
) -> tuple[float | None, float | None]:
    """CAPM beta/alpha vs benchmark, aligned on the common date intersection."""
    if (
        asset_returns is None
        or benchmark_returns is None
        or len(asset_returns) == 0
        or len(benchmark_returns) == 0
    ):
        return None, None

    aligned = pd.concat(
        [asset_returns.rename("asset"), benchmark_returns.rename("bench")], axis=1, join="inner"
    ).dropna()
    if len(aligned) < MIN_DAYS_BETA:
        return None, None

    variance = aligned["bench"].var(ddof=1)
    if variance is None or pd.isna(variance) or variance == 0:
        return None, None

    covariance = aligned["asset"].cov(aligned["bench"])
    beta = covariance / variance

    annualized_asset_return = float(aligned["asset"].mean()) * TRADING_DAYS_PER_YEAR
    annualized_bench_return = float(aligned["bench"].mean()) * TRADING_DAYS_PER_YEAR
    alpha = annualized_asset_return - (
        risk_free_rate + beta * (annualized_bench_return - risk_free_rate)
    )

    return float(beta), float(alpha)


def _finite_or_none(value: float | None) -> float | None:
    """Sanitize a metric value: None passes through unchanged; any non-finite
    float (inf, -inf, nan) becomes None.

    This is a defense-in-depth guard applied at the point every metric is
    assembled, on top of the per-metric guards already inside each compute_*
    function. It exists because Starlette's JSONResponse uses allow_nan=False,
    so a stray inf/nan anywhere in the response crashes the endpoint. NaN in
    particular is dangerous because `nan is not None` is True, so it silently
    slips past every `is None` check and can corrupt normalize_to_subscore's
    min/max clipping and compute_composite_score's weighted sum.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def normalize_to_subscore(value: float | None, metric_name: str) -> float | None:
    """Clip value to NORMALIZATION_BOUNDS[metric_name] and scale linearly to 0-100."""
    if value is None:
        return None
    bounds = NORMALIZATION_BOUNDS.get(metric_name)
    if not bounds:
        return None
    lo, hi = bounds
    clipped = min(max(value, lo), hi)
    return round((clipped - lo) / (hi - lo) * 100.0, 2)


def compute_composite_score(subscores: dict) -> tuple[float | None, dict]:
    """Weighted average of available subscores, renormalizing weights over what's present."""
    available = {k: v for k, v in subscores.items() if v is not None}
    if not available:
        return None, {}

    total_weight = sum(SCORE_WEIGHTS[k] for k in available)
    if total_weight == 0:
        return None, {}

    weights_used = {k: SCORE_WEIGHTS[k] / total_weight for k in available}
    score = sum(available[k] * weights_used[k] for k in available)
    return round(score, 2), weights_used


def score_to_grade(score: float | None) -> str | None:
    """Map a 0-100 composite score to a letter grade using GRADE_BANDS."""
    if score is None:
        return None
    for threshold, grade in GRADE_BANDS:
        if score >= threshold:
            return grade
    return "F"


def _null_score() -> dict:
    """Shared null-out shape used whenever a holding/portfolio can't be scored at all."""
    return {
        "metrics": {
            "cagr": None,
            "volatility": None,
            "sharpe": None,
            "sortino": None,
            "max_drawdown": None,
            "beta": None,
            "alpha": None,
        },
        "subscores": {
            "cagr": None,
            "sharpe": None,
            "max_drawdown": None,
            "alpha": None,
            "sortino": None,
        },
        "composite_score": None,
        "weights_used": {},
        "grade": None,
        "sample_days": 0,
        "insufficient_history": True,
        "short_history": True,
    }


def compute_metrics_and_score(
    daily_returns: pd.Series,
    benchmark_returns: pd.Series,
    risk_free_rate: float,
    price_series: pd.Series | None = None,
) -> dict:
    """
    Core reusable scoring routine, used identically for a single holding and for the
    synthetic portfolio return series. Zero network/DB calls.

    If price_series is provided, it's used directly for CAGR/max_drawdown (real price
    path). If None, a synthetic index is built from daily_returns via
    returns_to_cumulative_index (the portfolio case, where no single price series exists).
    """
    if daily_returns is None:
        daily_returns = pd.Series(dtype=float)
    sample_days = len(daily_returns)

    if price_series is None:
        price_series = (
            returns_to_cumulative_index(daily_returns)
            if sample_days > 0
            else pd.Series(dtype=float)
        )

    cagr = compute_cagr(price_series)
    max_drawdown = compute_max_drawdown(price_series)
    volatility = compute_volatility(daily_returns)
    sharpe = compute_sharpe(daily_returns, risk_free_rate)
    sortino = compute_sortino(daily_returns, risk_free_rate)
    beta, alpha = compute_beta_alpha(daily_returns, benchmark_returns, risk_free_rate)

    # Sanitize every raw metric before it's used for anything else, so a stray
    # inf/nan (from any source, expected or not) can never reach the subscore
    # normalization, the composite score, or the JSON response.
    metrics = {
        "cagr": _finite_or_none(cagr),
        "volatility": _finite_or_none(volatility),
        "sharpe": _finite_or_none(sharpe),
        "sortino": _finite_or_none(sortino),
        "max_drawdown": _finite_or_none(max_drawdown),
        "beta": _finite_or_none(beta),
        "alpha": _finite_or_none(alpha),
    }
    rounded_metrics = {k: (round(v, 4) if v is not None else None) for k, v in metrics.items()}

    subscores = {
        "cagr": normalize_to_subscore(metrics["cagr"], "cagr"),
        "sharpe": normalize_to_subscore(metrics["sharpe"], "sharpe"),
        "max_drawdown": normalize_to_subscore(metrics["max_drawdown"], "max_drawdown"),
        "alpha": normalize_to_subscore(metrics["alpha"], "alpha"),
        "sortino": normalize_to_subscore(metrics["sortino"], "sortino"),
    }
    composite_score, weights_used = compute_composite_score(subscores)
    grade = score_to_grade(composite_score)

    return {
        "metrics": rounded_metrics,
        "subscores": subscores,
        "composite_score": composite_score,
        "weights_used": {k: round(v, 4) for k, v in weights_used.items()},
        "grade": grade,
        "sample_days": sample_days,
        "insufficient_history": sample_days < MIN_DAYS_BETA,
        "short_history": sample_days < MIN_DAYS_RELIABLE_CAGR,
    }


def build_portfolio_return_series(
    holding_returns: dict, weights: dict
) -> tuple[pd.Series, list, float]:
    """
    Combine each holding's daily returns series into one value-weighted portfolio
    daily-return series, using current position weights (fraction 0.0-1.0).

    Holdings with a missing/empty returns series are excluded (collected as
    excluded_tickers) and the remaining weights are renormalized to sum to 1.0
    among included tickers, so the portfolio score reflects what could actually
    be measured.

    Returns (weighted_daily_return_series, excluded_tickers, included_weight_fraction).
    included_weight_fraction is the total ORIGINAL weight covered by included tickers
    (before renormalization) — callers use it to flag coverage gaps.
    """
    included = {t: s for t, s in holding_returns.items() if s is not None and len(s) > 0}
    excluded = [t for t in weights if t not in included]

    if not included:
        return pd.Series(dtype=float), list(weights.keys()), 0.0

    total_weight = sum(weights.get(t, 0.0) for t in included)
    if total_weight <= 0:
        return pd.Series(dtype=float), list(weights.keys()), 0.0

    df = pd.concat(included, axis=1, join="inner").dropna()
    if df.empty:
        return pd.Series(dtype=float), list(weights.keys()), 0.0

    renormalized_weights = {t: weights.get(t, 0.0) / total_weight for t in included}
    weighted_series = sum(df[t] * renormalized_weights[t] for t in included)

    return weighted_series, excluded, total_weight


# --- I/O functions (network calls; not unit tested) ----------------------


def get_risk_free_rate(risk_free_rate: float | None = None) -> float:
    """
    If risk_free_rate is provided, return it unchanged (no network call).
    Otherwise fetch the latest ^IRX close and divide by 100 (^IRX is quoted in
    percent). Falls back to DEFAULT_RISK_FREE_RATE on any failure.
    """
    if risk_free_rate is not None:
        return float(risk_free_rate)
    try:
        ticker = yf.Ticker(RISK_FREE_RATE_TICKER)
        hist = ticker.history(period="5d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1]) / 100.0
    except Exception:
        logger.warning(
            "Failed to fetch risk-free rate from %s", RISK_FREE_RATE_TICKER, exc_info=True
        )
    return DEFAULT_RISK_FREE_RATE


def fetch_price_series(ticker: str, lookback_period: str) -> pd.Series:
    """Fetch a daily close price series for `ticker` over `lookback_period`.
    Never raises — returns an empty Series on any failure."""
    try:
        yf_ticker = yf.Ticker(ticker)
        hist = yf_ticker.history(period=lookback_period)
        if not hist.empty:
            series = hist["Close"].astype(float)
            series.index = series.index.tz_localize(None)
            return series
    except Exception:
        logger.warning("Failed to fetch price series for %s", ticker, exc_info=True)
    return pd.Series(dtype=float)


def score_holding(
    ticker: str,
    trade_currency: str,
    base_currency: str,
    lookback_period: str,
    benchmark_returns: pd.Series,
    risk_free_rate: float,
) -> tuple[dict, pd.Series | None, list]:
    """
    Fetch a holding's price series over lookback_period, convert to base_currency
    using a daily FX series (not a spot rate), and compute its score.

    Verified (not just read) to actually apply: a differential test comparing
    scores computed with this FX conversion on vs. off showed (a) a small but
    non-zero CAGR shift matching (1+native_cagr)*(fx_end/fx_start)^(365/days)-1
    over a flat-FX window, and (b) large, unambiguous divergence in CAGR/Sharpe/
    Sortino/alpha over a window with a sharp USD/THB move. See
    docs/scoring_fx_verify_and_consolidate_prompt.md for the methodology. Do not
    re-derive this from the code alone if it's ever questioned again — rerun the
    differential test, since code that "reads correct" was also how Bug 1 (see
    docs/fx_report_debug_prompt.md) silently returned 1.0 for months.

    Never raises — any failure degrades to a null-out score + warning so a holding
    is never dropped from the response.
    """
    warnings: list = []
    try:
        price_series = fetch_price_series(ticker, lookback_period)
        if price_series is None or len(price_series) < 2:
            warnings.append(
                {
                    "ticker": ticker,
                    "message": f"No sufficient price history available for lookback_period={lookback_period}",
                }
            )
            return {"ticker": ticker, **_null_score()}, None, warnings

        if trade_currency != base_currency:
            start_date = price_series.index.min()
            end_date = price_series.index.max()
            fx_series = get_historical_fx_series(
                trade_currency, base_currency, start_date, end_date
            )
            if fx_series is None or fx_series.empty:
                warnings.append(
                    {
                        "ticker": ticker,
                        "message": f"FX series unavailable for {trade_currency}->{base_currency}, using 1.0",
                    }
                )
                fx_aligned = pd.Series(1.0, index=price_series.index)
            else:
                fx_aligned = fx_series.reindex(price_series.index, method="ffill").bfill()
                if fx_aligned.isna().any():
                    warnings.append(
                        {
                            "ticker": ticker,
                            "message": f"Partial FX data for {trade_currency}->{base_currency}; missing values filled with 1.0",
                        }
                    )
                    fx_aligned = fx_aligned.fillna(1.0)
            price_series_base = price_series * fx_aligned
        else:
            price_series_base = price_series

        daily_returns = compute_daily_returns(price_series_base)
        result = compute_metrics_and_score(
            daily_returns, benchmark_returns, risk_free_rate, price_series=price_series_base
        )

        if result["insufficient_history"]:
            warnings.append(
                {
                    "ticker": ticker,
                    "message": f"Insufficient price history (<{MIN_DAYS_BETA} trading days): sharpe/sortino/volatility/beta/alpha set to null",
                }
            )
        elif result["short_history"]:
            warnings.append(
                {
                    "ticker": ticker,
                    "message": f"Short price history (<{MIN_DAYS_RELIABLE_CAGR} trading days): CAGR/max_drawdown may be unreliable",
                }
            )

        return {"ticker": ticker, **result}, daily_returns, warnings
    except Exception as e:
        warnings.append({"ticker": ticker, "message": f"Scoring failed: {e}"})
        return {"ticker": ticker, **_null_score()}, None, warnings


def calculate_performance_scores(
    holdings: list,
    base_currency: str = "USD",
    benchmark_ticker: str = "SPY",
    risk_free_rate: float | None = None,
    lookback_period: str = "1y",
) -> dict:
    """
    Compute risk-adjusted performance scores per holding and for the overall portfolio.

    Args:
        holdings: list of {"ticker": str, "trade_currency": str, "weight_pct": float}.
        base_currency: currency all scoring metrics are computed in.
        benchmark_ticker: ticker used for beta/alpha comparison.
        risk_free_rate: if None, fetched from ^IRX (see get_risk_free_rate).
        lookback_period: yfinance period string (e.g. "1y") governing ONLY these
            asset-quality risk/scoring metrics. It never affects personal FIFO
            holding-period returns computed elsewhere in the app.

    Returns:
        {"portfolio_score": {...}, "holdings_scores": [...], "warnings": [...]}
        holdings_scores contains exactly one entry per input holding (1:1 coverage,
        in input order); entries that couldn't be scored use the null-out shape.
    """
    risk_free = get_risk_free_rate(risk_free_rate)

    benchmark_prices = fetch_price_series(benchmark_ticker, lookback_period)
    benchmark_returns = (
        compute_daily_returns(benchmark_prices)
        if len(benchmark_prices) > 0
        else pd.Series(dtype=float)
    )

    holdings_scores = []
    holding_returns_map: dict = {}
    all_warnings: list = []
    weights: dict = {}

    for holding in holdings:
        ticker = holding["ticker"]
        trade_currency = holding.get("trade_currency", base_currency)
        weight_pct = holding.get("weight_pct", 0.0) or 0.0
        weights[ticker] = weight_pct / 100.0

        score_dict, returns_series, warnings = score_holding(
            ticker, trade_currency, base_currency, lookback_period, benchmark_returns, risk_free
        )
        holdings_scores.append(score_dict)
        if returns_series is not None and len(returns_series) > 0:
            holding_returns_map[ticker] = returns_series
        all_warnings.extend(warnings)

    portfolio_returns, excluded, included_weight = build_portfolio_return_series(
        holding_returns_map, weights
    )
    if excluded:
        all_warnings.append(
            {
                "ticker": None,
                "message": (
                    f"Portfolio score based on {included_weight * 100:.1f}% of portfolio weight; "
                    f"excluded due to insufficient data: {', '.join(excluded)}"
                ),
            }
        )

    if portfolio_returns is None or portfolio_returns.empty:
        portfolio_score = {"ticker": "PORTFOLIO", **_null_score()}
    else:
        portfolio_result = compute_metrics_and_score(
            portfolio_returns, benchmark_returns, risk_free, price_series=None
        )
        portfolio_score = {"ticker": "PORTFOLIO", **portfolio_result}

    return {
        "portfolio_score": portfolio_score,
        "holdings_scores": holdings_scores,
        "warnings": all_warnings,
    }
