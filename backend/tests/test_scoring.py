"""
Unit tests for the pure math functions in service/scoring.py.

These tests use synthetic pandas Series only — no network calls, no DB, no
mocking library required. They intentionally do NOT cover:
  - get_risk_free_rate's live ^IRX fetch branch (network-dependent)
  - fetch_price_series (network-dependent)
  - score_holding / calculate_performance_scores end-to-end (network-dependent
    orchestration of the above)
Those paths are verified manually against a running server (see the plan's
verification section) rather than via automated tests.
"""

import numpy as np
import pandas as pd
import pytest

from service import scoring


def _series(values, start="2023-01-02", freq="B"):
    """Build a pd.Series with a business-day DatetimeIndex from a list of values."""
    index = pd.bdate_range(start=start, periods=len(values), freq=freq)
    return pd.Series(values, index=index, dtype=float)


# --- compute_daily_returns -------------------------------------------------


def test_compute_daily_returns_basic():
    prices = _series([100, 110, 121])
    returns = scoring.compute_daily_returns(prices)
    assert len(returns) == 2
    assert returns.iloc[0] == pytest.approx(0.10)
    assert returns.iloc[1] == pytest.approx(0.10)


def test_compute_daily_returns_zero_price_does_not_produce_inf():
    """Regression test: a zero (stale/bad) price print must not produce an
    infinite pct_change return that .dropna() fails to catch (inf is not NaN).
    """
    prices = _series([100.0, 0.0, 110.0])
    returns = scoring.compute_daily_returns(prices)
    assert not np.isinf(returns).any()
    assert not returns.isna().any()


# --- compute_cagr ------------------------------------------------------


def test_compute_cagr_known_growth():
    index = pd.DatetimeIndex(["2023-01-01", "2024-01-01"])  # exactly 365 days apart
    prices = pd.Series([100.0, 200.0], index=index)
    cagr = scoring.compute_cagr(prices)
    assert cagr == pytest.approx(1.0, rel=1e-6)


def test_compute_cagr_flat_series():
    prices = _series([100.0] * 30)
    cagr = scoring.compute_cagr(prices)
    assert cagr == pytest.approx(0.0, abs=1e-9)


def test_compute_cagr_insufficient_data():
    prices = _series([100.0])
    assert scoring.compute_cagr(prices) is None


def test_compute_cagr_trailing_nan_does_not_produce_nan():
    """Regression test: a NaN in the most recent bar (e.g. yfinance returning
    a NaN for today's partial/incomplete trading day) must not leak into the
    CAGR result. Previously compute_cagr checked len(price_series.dropna())
    but then read .iloc[-1] off the ORIGINAL series, so a trailing NaN price
    silently produced a NaN CAGR that crashed JSON serialization downstream.
    """
    index = pd.DatetimeIndex(["2023-01-01", "2023-06-01", "2024-01-01"])
    prices = pd.Series([100.0, 150.0, np.nan], index=index)
    cagr = scoring.compute_cagr(prices)
    # Should fall back to using the last non-NaN value (150.0 on 2023-06-01),
    # not produce NaN.
    assert cagr is not None
    assert np.isfinite(cagr)


def test_compute_cagr_zero_days_span_is_none():
    """An extreme/degenerate exponent (near-zero day span) must never produce
    inf/OverflowError; it should safely resolve to None."""
    index = pd.DatetimeIndex(["2023-01-01", "2023-01-01"])
    prices = pd.Series([100.0, 100000.0], index=index)
    cagr = scoring.compute_cagr(prices)
    assert cagr is None


# --- compute_volatility --------------------------------------------------


def test_compute_volatility_known_std():
    values = [0.01, 0.02, -0.01, 0.015, -0.03, 0.005, -0.02, 0.01] * 5  # 40 values
    daily_returns = _series(values)
    expected_std = np.std(values, ddof=1)
    expected_vol = expected_std * np.sqrt(scoring.TRADING_DAYS_PER_YEAR)
    vol = scoring.compute_volatility(daily_returns)
    assert vol == pytest.approx(expected_vol, rel=1e-6)


def test_compute_volatility_insufficient_data():
    daily_returns = _series([0.01] * 10)
    assert scoring.compute_volatility(daily_returns) is None


# --- compute_sharpe --------------------------------------------------------


def test_compute_sharpe_zero_excess_return():
    rf = 0.05
    daily_rf = rf / scoring.TRADING_DAYS_PER_YEAR
    values = [daily_rf + 0.005, daily_rf - 0.005] * 20  # 40 values, mean == daily_rf
    daily_returns = _series(values)
    sharpe = scoring.compute_sharpe(daily_returns, rf)
    assert sharpe == pytest.approx(0.0, abs=1e-6)


def test_compute_sharpe_insufficient_data():
    daily_returns = _series([0.01] * 10)
    assert scoring.compute_sharpe(daily_returns, 0.05) is None


# --- compute_sortino -------------------------------------------------------


def test_compute_sortino_no_downside_returns_none():
    daily_returns = _series([0.01] * 40)
    assert scoring.compute_sortino(daily_returns, 0.05) is None


def test_compute_sortino_known_downside():
    values = [0.01, 0.02, -0.01, 0.015, -0.03, 0.005, -0.02, 0.01] * 5  # 40 values
    daily_returns = _series(values)
    rf = 0.05

    arr = np.array(values)
    downside = arr[arr < 0]
    expected_downside_dev = np.std(downside, ddof=1) * np.sqrt(scoring.TRADING_DAYS_PER_YEAR)
    expected_annualized_return = arr.mean() * scoring.TRADING_DAYS_PER_YEAR
    expected_sortino = (expected_annualized_return - rf) / expected_downside_dev

    sortino = scoring.compute_sortino(daily_returns, rf)
    assert sortino == pytest.approx(expected_sortino, rel=1e-6)


# --- compute_max_drawdown ---------------------------------------------------


def test_compute_max_drawdown_known_path():
    prices = _series([100, 120, 80, 90])
    dd = scoring.compute_max_drawdown(prices)
    assert dd == pytest.approx((80 - 120) / 120, rel=1e-6)


def test_compute_max_drawdown_monotonic_increase():
    prices = _series([100, 105, 110, 120])
    dd = scoring.compute_max_drawdown(prices)
    assert dd == pytest.approx(0.0, abs=1e-9)


def test_compute_max_drawdown_leading_zero_price_does_not_crash():
    """Regression test: a leading zero/bad price must not make running_max 0
    and produce a 0/0 NaN that leaks out of the function."""
    prices = _series([0.0, 100.0, 90.0, 110.0])
    dd = scoring.compute_max_drawdown(prices)
    assert dd is None or np.isfinite(dd)


def test_compute_max_drawdown_all_nan_returns_none():
    prices = pd.Series([np.nan, np.nan], index=pd.bdate_range("2023-01-02", periods=2))
    assert scoring.compute_max_drawdown(prices) is None


# --- compute_beta_alpha ------------------------------------------------


def test_compute_beta_alpha_identical_series():
    values = [0.01, 0.02, -0.01, 0.015, -0.03, 0.005, -0.02, 0.01] * 5  # 40 values
    asset_returns = _series(values)
    benchmark_returns = _series(values)
    beta, alpha = scoring.compute_beta_alpha(asset_returns, benchmark_returns, 0.05)
    assert beta == pytest.approx(1.0, rel=1e-6)
    assert alpha == pytest.approx(0.0, abs=1e-6)


def test_compute_beta_alpha_insufficient_data():
    values = [0.01, -0.01] * 5  # 10 values, below MIN_DAYS_BETA
    asset_returns = _series(values)
    benchmark_returns = _series(values)
    beta, alpha = scoring.compute_beta_alpha(asset_returns, benchmark_returns, 0.05)
    assert beta is None
    assert alpha is None


# --- normalize_to_subscore --------------------------------------------------


def test_normalize_to_subscore_clips_bounds():
    lo, hi = scoring.NORMALIZATION_BOUNDS["sharpe"]
    assert scoring.normalize_to_subscore(hi + 10, "sharpe") == pytest.approx(100.0)
    assert scoring.normalize_to_subscore(lo - 10, "sharpe") == pytest.approx(0.0)
    assert scoring.normalize_to_subscore(None, "sharpe") is None
    midpoint = (lo + hi) / 2.0
    assert scoring.normalize_to_subscore(midpoint, "sharpe") == pytest.approx(50.0)


# --- compute_composite_score -------------------------------------------


def test_compute_composite_score_all_present():
    subscores = {"cagr": 80.0, "sharpe": 60.0, "max_drawdown": 90.0, "alpha": 50.0, "sortino": 70.0}
    expected = sum(subscores[k] * scoring.SCORE_WEIGHTS[k] for k in subscores)
    score, weights_used = scoring.compute_composite_score(subscores)
    assert score == pytest.approx(round(expected, 2))
    assert weights_used == pytest.approx(scoring.SCORE_WEIGHTS)


def test_compute_composite_score_renormalizes_missing():
    subscores = {"cagr": 80.0, "sharpe": 60.0, "max_drawdown": 90.0, "alpha": None, "sortino": 70.0}
    available = {k: v for k, v in subscores.items() if v is not None}
    total_weight = sum(scoring.SCORE_WEIGHTS[k] for k in available)
    expected_weights = {k: scoring.SCORE_WEIGHTS[k] / total_weight for k in available}
    expected_score = sum(available[k] * expected_weights[k] for k in available)

    score, weights_used = scoring.compute_composite_score(subscores)
    assert sum(weights_used.values()) == pytest.approx(1.0)
    assert score == pytest.approx(round(expected_score, 2))
    for k in expected_weights:
        assert weights_used[k] == pytest.approx(expected_weights[k])


def test_compute_composite_score_all_none():
    subscores = {"cagr": None, "sharpe": None, "max_drawdown": None, "alpha": None, "sortino": None}
    score, weights_used = scoring.compute_composite_score(subscores)
    assert score is None
    assert weights_used == {}


# --- score_to_grade ----------------------------------------------------


@pytest.mark.parametrize(
    "score,expected_grade",
    [
        (100, "A"),
        (85, "A"),
        (84.9, "B"),
        (70, "B"),
        (69.9, "C"),
        (55, "C"),
        (54.9, "D"),
        (40, "D"),
        (39.9, "F"),
        (0, "F"),
        (None, None),
    ],
)
def test_score_to_grade_boundaries(score, expected_grade):
    assert scoring.score_to_grade(score) == expected_grade


# --- compute_metrics_and_score ------------------------------------------


def test_compute_metrics_and_score_insufficient_history_flag():
    prices = _series(
        [100, 102, 101, 103, 105, 104, 106, 108, 107, 109, 110]
    )  # 11 points -> 10 returns
    daily_returns = scoring.compute_daily_returns(prices)
    benchmark_returns = _series([0.001] * 10)

    result = scoring.compute_metrics_and_score(
        daily_returns, benchmark_returns, 0.05, price_series=prices
    )

    assert result["insufficient_history"] is True
    for key in ("sharpe", "sortino", "volatility", "beta", "alpha"):
        assert result["metrics"][key] is None
    assert result["metrics"]["cagr"] is not None
    assert result["metrics"]["max_drawdown"] is not None
    # composite score should still be computed from cagr + max_drawdown alone
    assert result["composite_score"] is not None
    assert set(result["weights_used"].keys()) <= {"cagr", "max_drawdown"}
    assert sum(result["weights_used"].values()) == pytest.approx(1.0)


# --- build_portfolio_return_series --------------------------------------


def test_build_portfolio_return_series_two_holdings_50_50():
    index = pd.bdate_range(start="2023-01-02", periods=30)
    a_returns = pd.Series([0.01] * 30, index=index)
    b_returns = pd.Series([-0.005] * 30, index=index)

    weighted, excluded, included_weight = scoring.build_portfolio_return_series(
        {"A": a_returns, "B": b_returns}, {"A": 0.5, "B": 0.5}
    )

    assert excluded == []
    assert included_weight == pytest.approx(1.0)
    assert len(weighted) == 30
    for value in weighted:
        assert value == pytest.approx(0.5 * 0.01 + 0.5 * (-0.005))


def test_build_portfolio_return_series_misaligned_dates():
    index_a = pd.bdate_range(start="2023-01-02", periods=35)  # extra trailing dates
    index_b = pd.bdate_range(start="2023-01-02", periods=30)
    a_returns = pd.Series([0.01] * 35, index=index_a)
    b_returns = pd.Series([-0.005] * 30, index=index_b)

    weighted, excluded, _included_weight = scoring.build_portfolio_return_series(
        {"A": a_returns, "B": b_returns}, {"A": 0.5, "B": 0.5}
    )

    assert excluded == []
    assert len(weighted) == 30  # only the intersection of dates
    assert weighted.index.max() == index_b.max()


def test_build_portfolio_return_series_excludes_empty_holding_and_renormalizes():
    index = pd.bdate_range(start="2023-01-02", periods=30)
    a_returns = pd.Series([0.01] * 30, index=index)
    b_returns = pd.Series([-0.005] * 30, index=index)
    c_returns = pd.Series(dtype=float)  # empty -> should be excluded

    weighted, excluded, included_weight = scoring.build_portfolio_return_series(
        {"A": a_returns, "B": b_returns, "C": c_returns}, {"A": 0.4, "B": 0.4, "C": 0.2}
    )

    assert excluded == ["C"]
    assert included_weight == pytest.approx(0.8)
    # renormalized weights among A/B should each be 0.5
    for value in weighted:
        assert value == pytest.approx(0.5 * 0.01 + 0.5 * (-0.005))


# --- get_risk_free_rate --------------------------------------------------


def test_get_risk_free_rate_returns_provided_value():
    assert scoring.get_risk_free_rate(0.0333) == pytest.approx(0.0333)


# --- _finite_or_none / non-finite value sanitization ----------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (1.2345, 1.2345),
        (0.0, 0.0),
        (float("inf"), None),
        (float("-inf"), None),
        (float("nan"), None),
    ],
)
def test_finite_or_none(value, expected):
    result = scoring._finite_or_none(value)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_compute_metrics_and_score_never_returns_non_finite_values():
    """Regression test for the production bug: a daily_returns series that
    would previously have driven a metric to inf/nan must instead resolve to
    None everywhere (metrics, subscores, composite_score), so the result is
    always JSON-serializable (json.dumps with allow_nan=False, matching
    Starlette's JSONResponse).
    """
    import json

    # A price series with a trailing NaN (simulates yfinance's partial/incomplete
    # latest bar) combined with a zero price mid-series (simulates a stale print).
    index = pd.bdate_range("2023-01-02", periods=40)
    values = [100.0 + i for i in range(38)] + [0.0, np.nan]
    price_series = pd.Series(values, index=index)
    daily_returns = scoring.compute_daily_returns(price_series)
    benchmark_returns = _series(
        [0.001] * len(daily_returns),
        start=daily_returns.index[0] if len(daily_returns) else "2023-01-02",
    )

    result = scoring.compute_metrics_and_score(
        daily_returns, benchmark_returns, risk_free_rate=0.04, price_series=price_series
    )

    for key, value in result["metrics"].items():
        if value is not None:
            assert np.isfinite(value), f"metrics[{key}] = {value} is not finite"
    for key, value in result["subscores"].items():
        if value is not None:
            assert np.isfinite(value), f"subscores[{key}] = {value} is not finite"
    if result["composite_score"] is not None:
        assert np.isfinite(result["composite_score"])

    # The whole thing must be JSON-serializable the same way Starlette's
    # JSONResponse serializes it (allow_nan=False).
    json.dumps(result, allow_nan=False)
