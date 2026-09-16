# Portfolio Performance Scoring — Feature Guide

## For Users

### What's New

When you run a portfolio performance report, you'll now see:

1. **Risk Score Badge** (top-right of summary card)
   - Single letter grade: A-F
   - Composite score: 0-100
   - Click to expand and see full metrics breakdown

2. **Holdings Risk Score Column** (new column in holdings table)
   - Grade + score for each asset
   - Click to expand and see metrics
   - "Not scored" if data unavailable

3. **Scoring Warnings Banner** (top of report, if issues occurred)
   - Informational alerts about missing data or scoring failures
   - Dismissible (✕ button)
   - Expandable to see details

4. **Lookback Period Selector** (above holdings table)
   - Choose how far back to look: 1mo, 3mo, 6mo, 1yr, 2yr
   - Instantly updates scores without re-running cost-basis calculations
   - Default: 1 year

### Understanding the Metrics

When you click a score badge to expand, you'll see:

**Performance Metrics:**
- **CAGR** — Compound annual growth rate (annualized return over the lookback period)
- **Volatility** — Annualized standard deviation of daily returns (how "bouncy" the price is)
- **Max Drawdown** — Largest peak-to-trough decline (how much you'd lose in worst case)

**Risk-Adjusted Metrics:**
- **Sharpe Ratio** — Return per unit of total risk taken
- **Sortino Ratio** — Like Sharpe, but only penalizes downside volatility
- **Beta** — Sensitivity to your benchmark (SPY). 1.0 = moves with market, >1.0 = more volatile
- **Alpha** — Excess return vs what the market model predicts

### Grade Scale

| Grade | Score | Interpretation |
|-------|-------|-----------------|
| **A** | ≥85 | Excellent risk-adjusted performance |
| **B** | 70–84 | Good |
| **C** | 55–69 | Average |
| **D** | 40–54 | Below average |
| **F** | <40 | Poor |

**⚠️ Important:** This is a subjective, model-based heuristic (fixed weights on 5 normalized metrics), not an objective financial standard or investment recommendation.

### Data Quality Flags

- **"(limited data)"** — Less than 60 trading days of history. Score is directionally useful but less statistically reliable.
- **"(insufficient data)"** — Less than 30 trading days. Volatility-based metrics (Sharpe, Sortino, volatility, beta, alpha) are not calculated.
- If both flags are absent, you have a full year of history → high confidence.

### What's NOT Changed

The existing columns remain untouched:
- Cost basis, current value, unrealized P&L
- Total return %, local return %, FX return %
- Portfolio weights, days held, annualized return
- Long-term / short-term indicator

These are based on your actual purchase dates and trade history, not the lookback period.

---

## For Developers

### Component API

#### **ScoreDisplay**

```tsx
<ScoreDisplay
  score={score}           // Score object or null
  compact={true}          // true = badge only, false = always expanded
  expandable={true}       // true = click to toggle
/>
```

- Handles `null` scores gracefully
- Keyboard accessible (Enter/Space to expand)
- CSS classes: `.score-display`, `.score-display--*`

#### **ScoringWarningsBanner**

```tsx
<ScoringWarningsBanner warnings={report.scoring_warnings} />
```

- Auto-hides if no warnings
- Dismissible (state managed internally)
- Groups portfolio vs ticker-specific warnings

#### **LookbackSelector**

```tsx
<LookbackSelector
  currentLookback={period}
  onLookbackChange={(newPeriod) => { /* handle change */ }}
  loading={isUpdating}
/>
```

- Disabled while loading
- Shows "Updating scores..." indicator
- Options: 1mo, 3mo, 6mo, 1y, 2y

### Type References

```ts
interface Score {
  ticker: string;                    // "AAPL" or "PORTFOLIO"
  metrics: {
    cagr: number | null;
    volatility: number | null;
    sharpe: number | null;
    sortino: number | null;
    max_drawdown: number | null;
    beta: number | null;
    alpha: number | null;
  };
  subscores: {                       // 0-100 for each metric
    cagr: number | null;
    sharpe: number | null;
    max_drawdown: number | null;
    alpha: number | null;
    sortino: number | null;
  };
  composite_score: number | null;    // 0-100 final score
  grade: "A" | "B" | "C" | "D" | "F" | null;
  weights_used: Record<string, number>; // Actual weights applied
  sample_days: number;               // Trading days used in calculation
  insufficient_history: boolean;     // < 30 days?
  short_history: boolean;            // < 60 days?
}

interface ScoringWarning {
  ticker: string | null;             // null = portfolio-level warning
  message: string;
}
```

### Integration Example

In `PerformancePage.tsx`:

```tsx
// 1. Add state
const [lookbackPeriod, setLookbackPeriod] = useState("1y");
const [scoringLoading, setScoringLoading] = useState(false);

// 2. Handle lookback changes
async function handleLookbackChange(period: string) {
  setScoringLoading(true);
  try {
    const data = await getPortfolioPerformance({
      base_currency: report.base_currency,
      benchmark_ticker: report.portfolio_summary.benchmark_ticker,
      lookback_period: period,
    });
    setReport(data);
  } finally {
    setScoringLoading(false);
  }
}

// 3. Render components
<ScoringWarningsBanner warnings={report.scoring_warnings} />
<ScoreDisplay score={report.portfolio_score} />
<LookbackSelector
  currentLookback={lookbackPeriod}
  onLookbackChange={handleLookbackChange}
  loading={scoringLoading}
/>
{report.holdings.map(h => (
  <ScoreDisplay score={h.score} />
))}
```

### Styling Customization

All score components use CSS custom properties from the design system:

```css
:root {
  --color-bg: #0f1216;
  --color-text: #e7ecf1;
  --color-text-muted: #9aa6b2;
  --color-primary: #4f86f7;
  --color-warn: #e0a02f;
}
```

Grade badge colors are hardcoded but can be customized in `.score-display__grade--*` classes.

### Error Handling

Scoring failures are **never** fatal:
- If a holding's score can't be computed → `score.composite_score === null`
- If portfolio score can't be computed → `portfolio_score === null`
- Failures are described in `scoring_warnings` array

Always check for `null` before rendering detailed metrics:

```tsx
if (score?.composite_score === null) {
  return <span>Not scored</span>;
}
// Safe to access metrics now
```

### Performance Notes

- Lookback changes trigger a **new API call**, not a local re-calculation
- FIFO calculations are expensive, so they're cached by default
- Switching lookback periods **does not** invalidate the FIFO data
- Expect 10–60+ seconds for initial report (same as before); lookback changes typically faster

### Testing

1. **No scores**: Portfolio with no trade history or recent trades → all holdings show "Not scored"
2. **Partial scores**: Some assets fail → portfolio score computed from successful ones, warnings banner appears
3. **Full scores**: All assets + portfolio scored → grades visible, expandable details available
4. **Limited data**: <60 days → "(limited data)" flag appears on scores
5. **Lookback change**: Select different period → scores update in-place, FIFO metrics unchanged

---

## Troubleshooting

### Score shows "Not scored"
- Asset may have been delisted or no price history for selected lookback period
- Check `scoring_warnings` for specific reason
- Try expanding lookback window (e.g., 1mo → 1y)

### Metrics show "—" (null) with `insufficient_history` flag
- <30 trading days of history
- Volatility-based metrics (Sharpe, Sortino, beta, alpha) can't be computed reliably
- CAGR and max drawdown are still available but should be treated with caution

### Lookback selector is disabled
- Likely loading new scores. Wait for "Updating scores..." indicator to disappear.

### Warnings banner is missing
- Only appears if `scoring_warnings` array is non-empty
- Dismissing it hides it for the current session (not persisted)

---

## Backend Assumptions

The frontend assumes the backend:
1. **Always includes scoring fields** (even if null)
   - `portfolio_score?: Score | null`
   - `holdings[].score?: Score`
   - `scoring_warnings?: ScoringWarning[]`

2. **Never drops holdings** due to scoring failures
   - All holdings in request appear in response, with score: null if it failed

3. **Supports new query params**:
   - `lookback_period` (1mo, 3mo, 6mo, 1y, 2y, etc.)
   - `risk_free_rate` (optional, decimal like 0.045)

4. **Returns consistent score objects** for both portfolio and holdings
   - Same `Score` shape, just different `ticker` values
   - `ticker: "PORTFOLIO"` for portfolio-level score

See `docs/portfolio_performance_scoring.md` in the backend repo for full spec.
