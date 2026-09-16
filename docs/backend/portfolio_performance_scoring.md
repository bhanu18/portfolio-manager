# Portfolio Performance — Risk-Adjusted Scoring Update

This document specs a new, **fully additive** update to the existing endpoint:

```
GET /reports/portfolio-performance
```

Nothing about the existing response has changed — every field described in `docs/reports.md` §2 is still returned, unchanged, in the same place. This document only covers what's **new**. Read `docs/reports.md` first if you're not already familiar with the endpoint.

## What's new, in one sentence

Alongside the existing "how did my actual position do" numbers (FIFO cost basis, FX-adjusted return), the endpoint now also returns a "how good is this asset on a risk-adjusted basis" score — CAGR, Sharpe, Sortino, max drawdown, beta, alpha, volatility, rolled up into a single 0-100 composite score and an A-F letter grade — computed both **per holding** and for the **portfolio as a whole**.

These are two intentionally separate frames and should not be conflated in the UI:

| Frame | Existing fields | New fields |
|---|---|---|
| "How did *my* position do" | `holdings[].total_return_pct`, `annualized_return`, etc. | — |
| "Is this a good asset, risk-adjusted" | — | `holdings[].score`, `portfolio_score` |

The scoring frame uses a fixed lookback window (default 1 year of daily prices) and is independent of your actual purchase date/cost basis — it answers "how has this asset performed recently on a risk-adjusted basis," not "how has my money in it performed."

---

## New query parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `risk_free_rate` | float, optional | `null` | Annualized risk-free rate as a decimal (e.g. `0.045` for 4.5%). If omitted, the server fetches it from the 13-week T-bill (`^IRX`) and falls back to a static `4.25%` if that fetch fails. |
| `lookback_period` | string | `"1y"` | History window used **only** for the scoring metrics below (a yfinance period string: `"1mo"`, `"3mo"`, `"6mo"`, `"1y"`, `"2y"`, etc.). Does not affect any FIFO/cost-basis fields, which always use full trade history. |

Example:

```
GET /reports/portfolio-performance?base_currency=USD&benchmark_ticker=SPY&lookback_period=1y&risk_free_rate=0.045
```

---

## New response fields

### 1. `holdings[].score` (per holding)

Every object in the existing `holdings[]` array gets one new key, `score`. It is **always present** (1:1 with every holding — a holding is never dropped because scoring failed), but its value can be `null` if that specific asset couldn't be scored (e.g. delisted ticker, no price history).

### 2. `portfolio_score` (top-level, new key)

A single score object (or `null`) representing the **whole portfolio**, computed from a synthetic daily-return series built by combining each holding's daily returns weighted by its **current portfolio weight** (not by averaging each holding's individual score — this correctly captures diversification effects on volatility/beta/etc.).

### 3. `scoring_warnings` (top-level, new key)

An array (max 10) of warnings encountered while computing scores, in the same shape as the existing `fx_warnings`:

```json
{ "ticker": "XYZ", "message": "No price history available for lookback_period=1y" }
```

`ticker: null` indicates a portfolio-level warning, e.g.:

```json
{ "ticker": null, "message": "Portfolio score based on 82.3% of portfolio weight; excluded due to insufficient data: XYZ, ABC" }
```

---

## The "score object" shape

Both `holdings[].score` and `portfolio_score` use the identical shape below.

```json
{
  "ticker": "AAPL",
  "metrics": {
    "cagr": 0.6171,
    "volatility": 0.2205,
    "sharpe": 2.2196,
    "sortino": 3.8479,
    "max_drawdown": -0.1146,
    "beta": 0.9357,
    "alpha": 0.3271
  },
  "subscores": {
    "cagr": 100.0,
    "sharpe": 80.49,
    "max_drawdown": 80.91,
    "alpha": 100.0,
    "sortino": 96.96
  },
  "composite_score": 91.0,
  "weights_used": {
    "cagr": 0.3,
    "sharpe": 0.25,
    "max_drawdown": 0.2,
    "alpha": 0.15,
    "sortino": 0.1
  },
  "grade": "A",
  "sample_days": 251,
  "insufficient_history": false,
  "short_history": false
}
```

For `portfolio_score`, `ticker` is the literal string `"PORTFOLIO"`.

### Field reference

| Field | Type | Description |
|---|---|---|
| `metrics.cagr` | float \| null | Compound annual growth rate over the lookback window, as a decimal (`0.6171` = +61.71%/yr). |
| `metrics.volatility` | float \| null | Annualized standard deviation of daily returns (decimal). |
| `metrics.sharpe` | float \| null | Sharpe ratio (excess return over risk-free rate, per unit of total volatility). |
| `metrics.sortino` | float \| null | Sortino ratio (like Sharpe, but only penalizes downside volatility). |
| `metrics.max_drawdown` | float \| null | Largest peak-to-trough decline over the window, as a **negative** decimal (`-0.1146` = -11.46%). |
| `metrics.beta` | float \| null | Sensitivity to `benchmark_ticker`'s daily returns (CAPM beta). |
| `metrics.alpha` | float \| null | Annualized excess return vs. what CAPM would predict given beta (decimal). |
| `subscores.*` | float \| null | Each of the 5 scored metrics (cagr, sharpe, max_drawdown, alpha, sortino — note: **not** volatility or beta directly) normalized/clipped to a 0-100 scale. `null` if the underlying metric is `null`. |
| `composite_score` | float \| null | Weighted average of the available `subscores`, 0-100. `null` only if **every** subscore is `null`. |
| `weights_used` | object | The actual weights applied to compute `composite_score`. If some subscores are `null`, the remaining weights are proportionally renormalized to sum to 1.0, so `composite_score` always reflects a fair 0-100 scale regardless of missing metrics. Empty object `{}` if nothing could be scored. |
| `grade` | string \| null | Letter grade `"A"`–`"F"` derived from `composite_score` (see thresholds below). `null` iff `composite_score` is `null`. |
| `sample_days` | int | Number of daily-return observations actually used. |
| `insufficient_history` | bool | `true` when `sample_days < 30`. When `true`, `sharpe`, `sortino`, `volatility`, `beta`, and `alpha` are all forced to `null` (not statistically meaningful below 30 trading days). |
| `short_history` | bool | `true` when `sample_days < 60` (this includes the `insufficient_history` case). CAGR and max drawdown are still computed but should be flagged in the UI as based on limited history. |

### Grade thresholds

| Grade | `composite_score` range |
|---|---|
| A | ≥ 85 |
| B | ≥ 70 and < 85 |
| C | ≥ 55 and < 70 |
| D | ≥ 40 and < 55 |
| F | < 40 |

**Note for the UI:** this composite score is a subjective, model-based heuristic (fixed weights on 5 normalized metrics), not an objective financial standard or investment recommendation. Consider labeling it accordingly (e.g. a tooltip: "risk-adjusted quality score based on trailing {lookback_period} performance").

### Composite score weights (when all 5 metrics are available)

| Metric | Weight |
|---|---|
| CAGR | 30% |
| Sharpe | 25% |
| Max drawdown | 20% |
| Alpha | 15% |
| Sortino | 10% |

---

## Null / failure handling — what the frontend needs to handle

Scoring is designed to **never** cause the endpoint to fail or drop a holding. There are three "failure levels" to render:

1. **Fully scored** — `composite_score` and `grade` are non-null. Render normally.
2. **Partially scored** — some `metrics`/`subscores` are `null` (commonly because `insufficient_history` is `true`), but `composite_score`/`grade` are still non-null (computed from whichever subscores are available, reweighted). Render the score, but consider a subtle indicator (e.g. "based on limited data") when `short_history` is `true`.
3. **Not scored at all** — the entire score object has `composite_score: null`, `grade: null`, `weights_used: {}`, and `sample_days: 0`. This happens when price history couldn't be fetched at all (bad/delisted ticker, network issue). Render as "Not available" / "—" rather than a 0 or blank chart. Check `scoring_warnings` for a matching `ticker` entry to optionally show *why*.

`portfolio_score` can independently be `null` even when individual holdings have scores (e.g. if the combined weighted series couldn't be built), and vice versa. Handle it as its own independent nullable object — don't assume it mirrors the holdings.

---

## Full example response (new fields highlighted)

```json
{
  "report_date": "2026-07-01",
  "base_currency": "USD",
  "exchange_rates_current": { "USD": 1.0 },
  "portfolio_summary": { "...": "unchanged, see docs/reports.md" },
  "holdings": [
    {
      "ticker": "AAPL",
      "asset_name": "AAPL",
      "purchase_date": "2025-11-03",
      "...": "all existing fields unchanged, see docs/reports.md",
      "weight_pct": 40.0,
      "asset_type": "stock",

      "score": {
        "ticker": "AAPL",
        "metrics": {
          "cagr": 0.6171,
          "volatility": 0.2205,
          "sharpe": 2.2196,
          "sortino": 3.8479,
          "max_drawdown": -0.1146,
          "beta": 0.9357,
          "alpha": 0.3271
        },
        "subscores": {
          "cagr": 100.0,
          "sharpe": 80.49,
          "max_drawdown": 80.91,
          "alpha": 100.0,
          "sortino": 96.96
        },
        "composite_score": 91.0,
        "weights_used": { "cagr": 0.3, "sharpe": 0.25, "max_drawdown": 0.2, "alpha": 0.15, "sortino": 0.1 },
        "grade": "A",
        "sample_days": 251,
        "insufficient_history": false,
        "short_history": false
      }
    },
    {
      "ticker": "XYZ",
      "...": "unchanged fields",
      "score": {
        "ticker": "XYZ",
        "metrics": { "cagr": null, "volatility": null, "sharpe": null, "sortino": null, "max_drawdown": null, "beta": null, "alpha": null },
        "subscores": { "cagr": null, "sharpe": null, "max_drawdown": null, "alpha": null, "sortino": null },
        "composite_score": null,
        "weights_used": {},
        "grade": null,
        "sample_days": 0,
        "insufficient_history": true,
        "short_history": true
      }
    }
  ],
  "by_currency": { "...": "unchanged" },
  "by_asset_type": { "...": "unchanged" },
  "top_performers": [ "..." ],
  "bottom_performers": [ "..." ],
  "fx_warnings": [],

  "portfolio_score": {
    "ticker": "PORTFOLIO",
    "metrics": {
      "cagr": 0.42,
      "volatility": 0.185,
      "sharpe": 1.95,
      "sortino": 2.7,
      "max_drawdown": -0.09,
      "beta": 1.02,
      "alpha": 0.11
    },
    "subscores": { "cagr": 100.0, "sharpe": 73.75, "max_drawdown": 85.0, "alpha": 86.67, "sortino": 92.5 },
    "composite_score": 88.9,
    "weights_used": { "cagr": 0.3, "sharpe": 0.25, "max_drawdown": 0.2, "alpha": 0.15, "sortino": 0.1 },
    "grade": "A",
    "sample_days": 251,
    "insufficient_history": false,
    "short_history": false
  },
  "scoring_warnings": [
    { "ticker": "XYZ", "message": "No price history available for lookback_period=1y" },
    { "ticker": null, "message": "Portfolio score based on 91.2% of portfolio weight; excluded due to insufficient data: XYZ" }
  ]
}
```

---

## Suggested UI treatment

- **Holdings table**: add a "Score" or "Grade" column/badge (`A`/`B`/`C`/`D`/`F`, or the raw `composite_score` out of 100) next to (not replacing) the existing return % column. On hover/expand, show the individual `metrics` (CAGR, Sharpe, Sortino, Max Drawdown, Beta, Alpha, Volatility) with plain-language labels.
- **Portfolio summary card**: a single overall grade/score badge sourced from `portfolio_score`, separate from `total_unrealized_gain_loss_pct`.
- **Null state**: render `—` / "Not scored" (not `0` or a red flag) when `composite_score` is `null`.
- **Data-quality hint**: if `short_history` (and especially `insufficient_history`) is `true`, show a small "(limited data)" caption — the score is directionally useful but less statistically reliable.
- **Warnings**: `scoring_warnings` is good candidate for a dismissible info banner or a small "ⓘ" icon near the score, similar to how `fx_warnings` might already be surfaced.
- **Lookback control (optional)**: since `lookback_period` is a query param, you could expose a selector (1mo/3mo/6mo/1y/2y) that re-fetches the report and updates the scores — independent of the rest of the (cost-basis-based) report which won't change.

---

## Error handling

Scoring failures never produce an HTTP error — the endpoint still returns `200` with `portfolio_score: null`, every `holdings[].score: null`, and a descriptive entry in `scoring_warnings`. No new error status codes are introduced by this update.
