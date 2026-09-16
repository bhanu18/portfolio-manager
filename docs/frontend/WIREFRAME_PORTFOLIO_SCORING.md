# Portfolio Performance Scoring — Frontend Wireframe

This document outlines the UI design for the new risk-adjusted scoring feature added to the `/reports/portfolio-performance` endpoint.

## Overview

The scoring update introduces two separate but complementary frames:
1. **"How did *my* position do"** — existing FIFO cost-basis return metrics
2. **"How good is this asset, risk-adjusted"** — new composite score (A-F grade, 0-100) based on CAGR, Sharpe, Sortino, max drawdown, and alpha

## Key Design Principles

- **Two frames, not conflated** — score and return % are independent metrics, displayed side-by-side but visually separated
- **Graceful null handling** — if scoring fails, show "—" / "Not scored" rather than 0 or error states
- **Data-quality indicators** — flag scores based on <60 days of history with "(limited data)" caption
- **Warnings surface prominently** — banner for portfolio-level warnings, tooltip icon for holding-level warnings
- **Optional lookback control** — allow re-fetching with different lookback windows (1mo–2y)

---

## 1. Portfolio Summary Card (Dashboard/Overview)

### Current State
```
┌─────────────────────────────────────┐
│ Portfolio Summary                   │
├─────────────────────────────────────┤
│ Total Value:     $125,432.10        │
│ Total Gain/Loss: +$12,345.67 (+10.9%)
│                                     │
│ YTD Return:      +8.3%              │
│ Cash Balance:    $8,234.56          │
└─────────────────────────────────────┘
```

### Updated State
```
┌──────────────────────────────────────────────┐
│ Portfolio Summary                            │
├──────────────────────────────────────────────┤
│ Total Value:     $125,432.10                 │
│ Total Gain/Loss: +$12,345.67 (+10.9%)        │
│                                              │
│ YTD Return:      +8.3%   │  Risk Score: [A] │
│ Cash Balance:    $8,234.56                   │
│                                              │
│ ─────────────────────────────────────────── │
│ Risk-Adjusted Score: 88.9 / 100              │
│                                              │
│ CAGR 61.7%  │  Sharpe 1.95  │  Beta 1.02   │
│ Max DD -9%  │  Sortino 2.7  │  Alpha +0.11 │
└──────────────────────────────────────────────┘
```

### Interactions
- Click on score badge → expand to show full metrics breakdown
- Hover over grade (A-F) → tooltip: "Risk-adjusted quality score based on trailing {lookback_period} performance"
- "(limited data)" label if `short_history === true`

---

## 2. Holdings Table (Assets List / Dashboard Detail)

### Current State
```
┌──────────────────────────────────────────────────────────────────┐
│ Holdings                                                         │
├──────┬────────┬────────────┬──────────┬───────────┬────────────┤
│ Sym  │ Name   │ Qty        │ Avg Cost │ Unrealized│ Return %   │
├──────┼────────┼────────────┼──────────┼───────────┼────────────┤
│ AAPL │ Apple  │ 50.00      │ $145.20  │ +$5,234   │ +7.2%      │
│ TSLA │ Tesla  │ 20.00      │ $242.10  │ +$2,890   │ +5.9%      │
│ BTC  │ Bitcoin│ 0.15       │ $42,100  │ +$4,000   │ +15.2%     │
└──────┴────────┴────────────┴──────────┴───────────┴────────────┘
```

### Updated State
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Holdings                                                                    │
├──────┬────────┬────────┬───────────┬────────────┬──────────┬──────────────┤
│ Sym  │ Name   │ Qty    │ Unrealized│ Return %   │ Score    │ Grade / Data │
├──────┼────────┼────────┼───────────┼────────────┼──────────┼──────────────┤
│ AAPL │ Apple  │ 50.00  │ +$5,234   │ +7.2%      │ 91 / 100 │ A            │
│      │        │        │           │            │          │ (full data)  │
├──────┼────────┼────────┼───────────┼────────────┼──────────┼──────────────┤
│ TSLA │ Tesla  │ 20.00  │ +$2,890   │ +5.9%      │ 72 / 100 │ B            │
│      │        │        │           │            │          │ (limited)    │
├──────┼────────┼────────┼───────────┼────────────┼──────────┼──────────────┤
│ XYZ  │ Delisted?│0.50  │ +$100     │ +2.1%      │ —        │ Not scored   │
│      │        │        │           │            │          │              │
└──────┴────────┴────────┴───────────┴────────────┴──────────┴──────────────┘

[ⓘ] Scoring based on trailing 1 year. [1m] [3m] [6m] [1y] [2y]
```

### Interactions
- Click score row → expand to show breakdown:
  ```
  AAPL Risk-Adjusted Metrics (1-year lookback)
  ────────────────────────────────────
  Composite Score:   91.0 / 100
  Grade:             A (≥85)

  Performance Metrics:
    • CAGR:          +61.71%
    • Volatility:    22.05%
    • Max Drawdown:  -11.46%

  Risk-Adjusted Metrics:
    • Sharpe Ratio:  2.22
    • Sortino Ratio: 3.85
    • Beta (vs SPY): 0.936
    • Alpha:         +32.71%

  Data Quality:
    • Sample Days:   251
    • Status:        Full data available
  ```
- Hover on "(limited data)" badge → tooltip: "Based on <60 trading days of history. Results are directionally useful but less statistically reliable."
- Hover on "Not scored" → tooltip: "Price history unavailable (delisted ticker, no data for selected period)"
- Lookback selector (1m/3m/6mo/1y/2y) re-fetches scores independently

---

## 3. Warnings Banner (Top of Report, Conditional)

**Shown only if `scoring_warnings.length > 0`**

### Single warning
```
┌─────────────────────────────────────────────────────────────┐
│ ⓘ 1 scoring warning                                   [✕]  │
│                                                             │
│ "Ticker XYZ": No price history available for 1-year period │
└─────────────────────────────────────────────────────────────┘
```

### Multiple warnings
```
┌──────────────────────────────────────────────────────────┐
│ ⓘ 3 scoring warnings                            [✕]      │
├──────────────────────────────────────────────────────────┤
│ • "Ticker XYZ": No price history available for 1y       │
│ • Portfolio: Scored on 82.3% of weight; excluded: ABC   │
│ • "Ticker DEF": Insufficient data (<30 days)            │
└──────────────────────────────────────────────────────────┘
```

### Styling
- Light blue/info background (similar to `fx_warnings` if already styled)
- Dismissible (✕ button closes, doesn't persist on reload)
- Auto-collapse if >3 warnings (expandable with "Show all")

---

## 4. Asset Detail Page (Single Asset View)

### Current State
```
┌─────────────────────────────────────┐
│ AAPL — Apple Inc.                   │
├─────────────────────────────────────┤
│ Ticker:          AAPL               │
│ Type:            Stock              │
│ Market:          NASDAQ             │
│ Current Price:   $189.45            │
│ Last Updated:    2 hours ago        │
│                                     │
│ [Edit] [Delete] [View Trades]       │
└─────────────────────────────────────┘
```

### Updated State (Optional – can defer if only portfolio summary is priority)
```
┌──────────────────────────────────────────────────┐
│ AAPL — Apple Inc.                                │
├──────────────────────────────────────────────────┤
│ Ticker:    AAPL   │   Type:  Stock               │
│ Market:    NASDAQ │   Grade: A (91/100)          │
│                                                  │
│ Current Price:  $189.45   Last Updated: 2h ago  │
│                                                  │
│ ─────────────────────────────────────────────── │
│ 1-Year Risk-Adjusted Metrics:                    │
│                                                  │
│ CAGR:        +61.71%    Sharpe:    2.22          │
│ Volatility:  22.05%     Sortino:   3.85          │
│ Max DD:      -11.46%    Beta:      0.936         │
│ Alpha:       +32.71%    Sample:    251 days      │
│                                                  │
│ [Edit] [Delete] [View Trades]                    │
└──────────────────────────────────────────────────┘
```

---

## 5. Trades List (Scoped by Group)

### Current State
```
┌────────────────────────────────────────────────────────┐
│ Trades — [Group: "Main Portfolio" ▼]                  │
├────────┬────────┬──────────┬──────┬────────┬──────────┤
│ Date   │ Symbol │ Type     │ Qty  │ Price  │ Amount   │
├────────┼────────┼──────────┼──────┼────────┼──────────┤
│ Nov 3  │ AAPL   │ BUY      │ 50   │ $145.2 │ $7,260   │
│ Dec 15 │ TSLA   │ BUY      │ 20   │ $242.1 │ $4,842   │
└────────┴────────┴──────────┴──────┴────────┴──────────┘
```

### Updated State (Add Score Column — Optional)
```
┌────────────────────────────────────────────────────────────────┐
│ Trades — [Group: "Main Portfolio" ▼]                          │
├────────┬────────┬──────────┬──────┬────────┬────────┬──────────┤
│ Date   │ Symbol │ Type     │ Qty  │ Price  │ Score* │ Amount   │
├────────┼────────┼──────────┼──────┼────────┼────────┼──────────┤
│ Nov 3  │ AAPL   │ BUY      │ 50   │ $145.2 │ A (91) │ $7,260   │
│ Dec 15 │ TSLA   │ BUY      │ 20   │ $242.1 │ B (72) │ $4,842   │
└────────┴────────┴──────────┴──────┴────────┴────────┴──────────┘

* Score is for the underlying asset, not the trade itself.
```

---

## 6. Lookback Period Selector (Floating Control or Card)

### Design Option A: Inline Controls
```
Lookback Period: [1 month] [3 months] [6 months] [1 year] [2 years]
                                            ↑ active
```

### Design Option B: Dropdown + Label
```
────────────────────────────────────────────────────────
Risk-Adjusted Metrics Lookback: [1 year ▼]
────────────────────────────────────────────────────────
(Re-fetches and updates scores; existing FIFO metrics unchanged)
```

### Behavior
- Clicking a new lookback period triggers a re-fetch of `GET /reports/portfolio-performance?lookback_period={period}`
- Portfolio summary, holdings scores, and `portfolio_score` update in-place
- Existing cost-basis fields (return %, FIFO totals) remain unchanged
- Show a brief loading state ("Updating scores...")

---

## 7. Null States & Edge Cases

### Holding with No Score (Delisted / No History)
```
┌────────────────────────────────────────┐
│ XYZ  │ Mystery Corp   │ —              │
│      │                │ Not scored     │
│      │                │                │
│      │ Reason: No price history found  │
└────────────────────────────────────────┘
```

### Portfolio with No Score (All Holdings Fail)
```
┌──────────────────────────────────────────────┐
│ Portfolio Summary                            │
├──────────────────────────────────────────────┤
│ Total Value:     $125,432.10                 │
│ Total Gain/Loss: +$12,345.67 (+10.9%)        │
│                                              │
│ YTD Return:      +8.3%   │  Risk Score: —   │
│                                              │
│ Portfolio score not available at this time   │
└──────────────────────────────────────────────┘
```

### Insufficient History (30–60 Days)
```
┌──────────────────────────────────────────────┐
│ TSLA │ Tesla │ Score: 72 / 100                │
│      │       │ Grade: B (limited data)        │
│      │       │                                │
│ Sample Days: 45 — results based on <60 days  │
│ of history. Directionally useful, less       │
│ statistically reliable.                      │
└──────────────────────────────────────────────┘
```

---

## 8. Color & Typography Reference

### Grade Badge Colors
- **A** — Green (#10b981 or similar)
- **B** — Light Green (#84cc16 or similar)
- **C** — Yellow (#f59e0b or similar)
- **D** — Orange (#f97316 or similar)
- **F** — Red (#ef4444 or similar)

### Score Display
- **Composite Score** — Large number (18–24px), bold
- **Grade** — Large letter (20–28px), centered in circular/square badge
- **Metrics** — Smaller labels + values (12–14px), monospace for numbers
- **Warnings** — Info blue, light background

### Typography
- Headers: 16–20px, semi-bold
- Section labels: 14px, medium weight
- Data values: 14–16px, vary by importance
- Help text / tooltips: 12px, gray secondary

---

## 9. Interaction Patterns

### Expand / Collapse Score Details
```
Click score number → show metrics breakdown
Collapse automatically on blur or when switching views
```

### Hover States
- Score badge: subtle highlight, "click to expand" cursor
- "Limited data" label: show tooltip with explanation
- Grade letter: show tooltip explaining A-F scale

### Loading States
- Lookback change: "Updating scores..." spinner overlay on holdings table
- Price refresh: existing pattern (if already implemented)

### Error Handling
- If re-fetch fails, show a toast: "Failed to update scores. Please try again."
- Preserve the old scores in-place (don't blank them out)

---

## 10. Implementation Priority

### Phase 1 (MVP)
- ✅ Portfolio summary card: add grade + composite score
- ✅ Holdings table: add Score / Grade column
- ✅ Expand score row to show metrics breakdown
- ✅ Warnings banner (if warnings exist)
- ✅ Basic null-state handling ("Not scored" / "—")

### Phase 2 (Polish)
- ✅ Lookback period selector
- ✅ Limited data warnings / tooltips
- ✅ Asset detail page scoring section (optional if not a priority)
- ✅ Responsive table design for mobile

### Phase 3 (Enhancement)
- ✅ Animated transitions on expand/collapse
- ✅ Comparison view (e.g. side-by-side scores for different lookback periods)
- ✅ Historical score charting (if backend supports time-series snapshots)

---

## 10. Notes for Developer

1. **Type Safety**: Add TypeScript interfaces for the new response shape:
   ```ts
   interface ScoreMetrics {
     cagr: number | null;
     volatility: number | null;
     sharpe: number | null;
     sortino: number | null;
     max_drawdown: number | null;
     beta: number | null;
     alpha: number | null;
   }

   interface Score {
     ticker: string;
     metrics: ScoreMetrics;
     subscores: Record<string, number | null>;
     composite_score: number | null;
     weights_used: Record<string, number>;
     grade: "A" | "B" | "C" | "D" | "F" | null;
     sample_days: number;
     insufficient_history: boolean;
     short_history: boolean;
   }

   interface PortfolioPerformanceResponse {
     // ... existing fields
     holdings: (Holding & { score: Score })[];
     portfolio_score: Score | null;
     scoring_warnings: Array<{ ticker: string | null; message: string }>;
   }
   ```

2. **API Client**: Update the `assets` or `reports` service to accept `lookback_period` query param.

3. **State Management**: Consider whether to cache scores per lookback window, or always re-fetch (likely safer for accuracy).

4. **Accessibility**: Ensure grade badges have text labels, not just colors. ARIA labels for tooltips.

---

## References

- Backend spec: `/docs/portfolio_performance_scoring.md`
- Grade thresholds: A ≥85, B ≥70, C ≥55, D ≥40, F <40
- Default lookback: `"1y"` (1 year of daily prices)
- Composite weights: CAGR 30% | Sharpe 25% | Max DD 20% | Alpha 15% | Sortino 10%
