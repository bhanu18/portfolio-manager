# Claude Code Prompt — Add Performance Scoring Function

Add a stock scoring/rating function to the existing portfolio app. It should compute risk-adjusted performance scores per holding and for the overall portfolio, and return a JSON response.

## Function Signature
```python
def calculate_performance_scores(
    holdings: list[dict],
    base_currency: str = "USD",
    benchmark_ticker: str = "SPY",
    risk_free_rate: float = None,  # if None, fetch from ^IRX (13-week T-bill)
    lookback_period: str = "1y"     # period for volatility/beta calcs
) -> dict:
```

## Scope of `lookback_period` — resolve this explicitly

There are **two different return concepts** in this app; keep them separate and do NOT let `lookback_period` bleed across them:

1. **Personal holding performance** (already produced by `/reports/portfolio-performance`): actual FIFO cost basis with historical trade-date FX, real holding period from earliest purchase to today, `total_return_pct`, `annualized_return`, unrealized gain/loss. This answers *"how has my position done."* **`lookback_period` does NOT touch this.** It is never used to truncate the FIFO cost-basis window or the holding-period return. Those always reflect the full actual holding period from the trades.

2. **Asset-quality risk/scoring metrics** (new, this function): CAGR, volatility, Sharpe, Sortino, beta, CAPM alpha, and max drawdown are **all** computed from the asset's daily price series over `lookback_period`, in `base_currency`. This answers *"how good is this asset on a risk-adjusted basis over a standard window."* **`lookback_period` governs all of these, and only these.**

**Why they must stay separate:** Sharpe/Sortino/beta/alpha are only coherent when their return numerator and their volatility/covariance denominator come from the *same* daily series. Feeding a personal FIFO holding-period return into a Sharpe built on the asset's market volatility mixes two frames and produces a meaningless ratio. So the **composite score is built entirely from the `lookback_period` market series** (concept 2), not from the personal return (concept 1).

**Consequences of this decision:**
- The score rates the *asset over a fixed window*, so two portfolios holding the same ticker get the same score for it regardless of entry timing. That is intended.
- If a holding's actual holding period is shorter than `lookback_period` (e.g. bought 30 days ago, lookback `1y`), the risk metrics still use the asset's full `lookback_period` of market history — the asset existed before you bought it — giving a stable beta/vol. Do not shorten the window to the holding period.
- Only fall back / warn when the **asset itself** has insufficient total price history for the window (< 30 trading days available): flag in `warnings` and skip beta/Sharpe/Sortino for that ticker rather than crashing.
- Convert the daily price series to `base_currency` using the **daily FX series over the lookback window** (not a single spot rate), so volatility and Sharpe reflect the base-currency experience and stay consistent across currencies.
- Return both frames in the response: keep the existing personal-performance fields intact, and add the score block computed from concept 2 alongside them.

Default `lookback_period` = `"1y"`. (Optional: you may support a special value like `"holding"` that aligns the risk window to each holding's actual period, but this reduces cross-asset comparability — do not make it the default, and if you add it, document the trade-off.)

## Metrics to Compute (per holding AND portfolio-level)

Compute these from the asset's daily price series over `lookback_period`, in `base_currency` (this is concept 2 above — the scoring/risk window, independent of the personal holding period):

### 1. CAGR (Compound Annual Growth Rate)
```
CAGR = (end_value / start_value)^(365/days) - 1
```
Here `start_value` / `end_value` are the asset's base-currency prices at the **first and last day of the `lookback_period` window** (not personal cost basis), and `days` is the number of calendar days in that window. This is the market CAGR that feeds the score's return sub-score — keep it distinct from the personal `annualized_return` in the performance report.

### 2. Sharpe Ratio
```
Sharpe = (annualized_return - risk_free_rate) / annualized_volatility
```
- annualized_volatility = daily_returns.std() * sqrt(252)
- Fetch risk_free_rate from ^IRX if not provided

### 3. Sortino Ratio
```
Sortino = (annualized_return - risk_free_rate) / downside_deviation
```
- downside_deviation only considers negative daily returns

### 4. Max Drawdown
```
max_drawdown = min((price - running_max) / running_max) over the period
```
Express as a negative percentage (e.g., -18.5%)

### 5. Beta (vs benchmark)
```
beta = covariance(stock_returns, benchmark_returns) / variance(benchmark_returns)
```

### 6. Alpha (vs benchmark, CAPM)
```
alpha = stock_return - (risk_free_rate + beta * (benchmark_return - risk_free_rate))
```

### 7. Volatility
```
volatility = daily_returns.std() * sqrt(252) * 100  # annualized %
```

## Composite Score (0–100)
Combine the metrics into a single letter grade + numeric score. Suggested weighting:
- CAGR / return: 30%
- Sharpe ratio: 25%
- Max drawdown (inverted — smaller is better): 20%
- Alpha: 15%
- Sortino ratio: 10%

Normalize each metric to a 0–100 sub-score (define reasonable min/max bands, e.g. Sharpe 0→2 maps to 0→100, capped), then apply weights. Map final score to a letter grade:
- A: 85–100
- B: 70–84
- C: 55–69
- D: 40–54
- F: below 40

Make the weights and grade bands easy to adjust (define as constants at the top).

> **Note — this scoring model is subjective, not a derived financial standard.** The 30/25/20/15/10 weighting, the normalization bands (e.g. Sharpe 0→2 → 0→100), and the A–F cutoffs are a reasonable **first-draft** judgment call, not an industry-standard formula. Treat them as tunable defaults. Because they are all defined as top-level constants, they can be re-weighted or re-banded later without touching the calculation logic. Do not present the resulting grade as an objective rating — it reflects these chosen weights.

## Output JSON Structure
```json
{
  "report_date": "2025-01-12",
  "benchmark": "SPY",
  "risk_free_rate": 0.0425,
  "lookback_period": "1y",
  "portfolio_score": {
    "composite_score": 78.5,
    "grade": "B",
    "cagr": 18.5,
    "sharpe_ratio": 1.42,
    "sortino_ratio": 1.85,
    "max_drawdown": -12.3,
    "beta": 1.05,
    "alpha": 3.2,
    "volatility": 14.8
  },
  "holdings_scores": [
    {
      "ticker": "AAPL",
      "composite_score": 82.0,
      "grade": "B",
      "sub_scores": {
        "return_score": 88,
        "sharpe_score": 75,
        "drawdown_score": 80,
        "alpha_score": 78,
        "sortino_score": 85
      },
      "metrics": {
        "cagr": 22.1,
        "sharpe_ratio": 1.55,
        "sortino_ratio": 2.10,
        "max_drawdown": -15.2,
        "beta": 1.20,
        "alpha": 4.5,
        "volatility": 18.3
      },
      "interpretation": "Strong risk-adjusted returns, moderate volatility"
    }
  ],
  "rankings": {
    "best_risk_adjusted": ["NVDA", "AAPL"],
    "highest_return": ["NVDA", "GOOGL"],
    "lowest_risk": ["KO", "JNJ"],
    "worst_performers": ["INTC"]
  },
  "warnings": [
    {"ticker": "XYZ", "message": "Insufficient price history for reliable beta calculation"}
  ]
}
```

### Output completeness — cover every holding

`holdings_scores` must contain **one entry per active holding passed in**, not only the ones that clear the data-sufficiency bar. Do not silently drop holdings.

For a holding that fails the sufficiency threshold for some metrics:
- Include its entry with the metrics it *could* compute filled in, and set the skipped metrics (and their corresponding `sub_scores`) to `null`.
- Set `composite_score` to `null` and `grade` to `"N/A"` (or compute a partial score only from available sub-scores if you prefer — but if so, say so in the `interpretation` string and never fabricate a metric to fill a gap).
- Add a matching `warnings` entry (same `{ticker, message}` shape) naming what was skipped.

This keeps the response shape predictable for the frontend: it can always map holdings 1:1 and render `N/A` / `null` rather than having to reconcile a missing row. Fully sold positions (net quantity ≤ 0) are the only holdings excluded — consistent with `portfolio-performance`, which already skips them.

## Technical Requirements
- Reuse existing yfinance price-fetching and currency/FX-conversion logic where it already exists — don't duplicate it.
- **Risk-free rate is NOT existing reuse — it's a new fetch.** The app does not currently pull `^IRX` anywhere, so add a small new helper (e.g. `get_risk_free_rate()`) that fetches the latest `^IRX` close, divides by 100 to get a decimal (^IRX is quoted in percent), and returns it. Cache it for the call. If `risk_free_rate` is passed in, use that and skip the fetch. If the fetch fails, fall back to a sensible constant default (define at top, e.g. `0.0425`) and add a warning rather than crashing.
- Compute all returns in base_currency (apply the existing historical FX conversion) so scores are consistent across currencies.
- Use pandas/numpy for statistical calculations.
- **Insufficient-history handling — mirror the existing `get_historical_fx_rate` warning-based degradation pattern**, don't invent a new one:
  - Degrade gracefully per-metric instead of failing the whole call. If an asset has fewer than the minimum trading days available for a given metric, skip *that metric* (set it to `null`), not the entire holding.
  - Thresholds (define as top-level constants): `MIN_DAYS_BETA = 30` (beta, CAPM alpha, and anything derived from the benchmark covariance), and the same 30-day floor for Sharpe/Sortino/volatility since they need a stable daily-return series. CAGR/max-drawdown can still compute on shorter series but flag if the window is very short.
  - Emit warnings using the **same `{"ticker": ..., "message": ...}` shape** the FX layer already uses, appended to the `warnings` array — one entry per skipped metric/ticker, with a message naming what was skipped and why.
- Annualize using 252 trading days for volatility, 365 calendar days for CAGR.
- All scores rounded to 1 decimal, ratios to 2 decimals.
- Return valid JSON.

## Notes
- Do NOT fetch fundamental data (P/E, ROE, etc.) for now — keep this purely price/return-based so it works with the data already in the app
- Add a short docstring explaining each metric and the scoring methodology
## Deployment / Endpoint Integration

- **Surface portfolio-level scores through the existing `GET /reports/portfolio-performance` endpoint**, not a new route. That endpoint already fetches trades, applies FIFO cost basis with **historical FX rates at each trade date**, converts to `base_currency`, and computes benchmark/alpha — which is exactly the data the scores depend on. Reuse it rather than re-deriving returns.
- Before wiring in, inspect the endpoint and confirm which parameters it already accepts (`base_currency`, `benchmark_ticker`) and which the scoring needs added (`risk_free_rate`, `lookback_period`). If the current parameters can't accommodate the scoring inputs, flag the gap and propose the **minimal** additions — do not change the endpoint contract without confirming first.
- Add the scores as **new fields in the existing response** (e.g. a `portfolio_score` object and per-holding `score` blocks alongside the current `holdings[]` entries), rather than replacing or restructuring the current payload. Keep all existing fields intact.
- Keep the scoring logic in its own module/function so it stays testable in isolation; the endpoint should just call it and merge its output into the response.

### ⚠️ Prerequisite — do NOT attach scores to the by-symbol valuation endpoint yet

- The `GET /reports/valuation/{symbol}/{target_currency}` endpoint currently converts **cost basis at the current FX rate, not the historical trade-date rate**. (Confirmed from a live NVDA→THB response: both cost basis and current value resolve to the same ~33.28 USD/THB rate, so cost is being converted at today's rate.)
- This conflates currency movement with asset performance and is **inconsistent** with `/reports/portfolio-performance`, which uses historical FX. Per-symbol scores computed on top of this endpoint would inherit the same distortion.
- **Therefore:** compute scores only against `portfolio-performance` for now. Do not add scoring to the by-symbol valuation endpoint until its cost-basis conversion is fixed to use historical trade-date FX rates (matching the FIFO/historical-FX logic already in `portfolio-performance`). Flag this fix as a separate task; do not attempt it as part of the scoring work unless explicitly asked.
