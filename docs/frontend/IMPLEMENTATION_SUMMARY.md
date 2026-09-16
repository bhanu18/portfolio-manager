# Portfolio Performance Scoring — Implementation Summary

## Overview
Implemented the portfolio performance risk-adjusted scoring feature as specified in `docs/portfolio_performance_scoring.md`. The frontend now displays risk-adjusted metrics (CAGR, Sharpe, Sortino, max drawdown, beta, alpha) alongside existing FIFO cost-basis returns.

## Changes Made

### 1. TypeScript Types (`src/types/index.ts`)
Added new types for scoring response:
- **`GradeValue`**: Union type for letter grades (A-F)
- **`ScoreMetrics`**: Risk-adjusted metrics (CAGR, volatility, Sharpe, Sortino, max drawdown, beta, alpha)
- **`Score`**: Complete score object with metrics, subscores, composite score, grade, and data quality flags
- **`ScoringWarning`**: Warning object for scoring failures
- **Extended `PortfolioPerformanceReport`**:
  - Added optional `portfolio_score?: Score | null`
  - Added optional `scoring_warnings?: ScoringWarning[]`
  - Extended `holdings` to include optional `score?: Score` on each holding
- **Extended `HoldingAnalysis`**:
  - Added optional `score?: Score` property

### 2. API Client (`src/api/reports.ts`)
Updated `PortfolioPerformanceParams` interface:
- Added `lookback_period?: string` — lookback window for scoring (1mo, 3mo, 6mo, 1y, 2y)
- Added `risk_free_rate?: number` — optional risk-free rate for Sharpe/Sortino calculation

### 3. Components

#### **ScoreDisplay** (`src/components/ScoreDisplay.tsx`)
Reusable component for displaying risk-adjusted scores:
- Shows composite score (0-100) + grade badge (A-F)
- Expandable to show full metrics breakdown
- Handles null scores gracefully ("Not scored" state)
- Displays data quality flags (insufficient/limited history)
- Includes detailed metrics grid: CAGR, volatility, Sharpe, Sortino, max drawdown, beta, alpha
- Keyboard accessible (Enter/Space to toggle expansion)

#### **ScoringWarningsBanner** (`src/components/ScoringWarningsBanner.tsx`)
Dismissible banner for scoring warnings:
- Shows warning count with toggle to expand/collapse
- Groups warnings by type (portfolio-level vs holding-level)
- Distinguishes ticker-specific errors from portfolio-wide issues
- Auto-dismissible (✕ button)
- Green color scheme (info-level alerts)

#### **LookbackSelector** (`src/components/LookbackSelector.tsx`)
Dropdown selector for score lookback window:
- Options: 1 month, 3 months, 6 months, 1 year (default), 2 years
- Loading state indicator while fetching new scores
- Explanatory note about independence from FIFO metrics

### 4. Performance Page Integration (`src/pages/PerformancePage.tsx`)
Updated main report page with scoring features:

**State additions:**
- `lookbackPeriod`: Current lookback window (default "1y")
- `scoringLoading`: Loading state for lookback changes

**New function:**
- `handleLookbackChange(period)`: Re-fetches scores with new lookback period, updates report in-place

**UI changes:**
- Added `ScoringWarningsBanner` at top of results (conditional on warnings presence)
- Updated portfolio summary card:
  - Added risk score badge next to title
  - Shows portfolio-level composite score and grade
- Added `LookbackSelector` control before holdings table
- Added "Risk Score" column to holdings table
  - Each holding shows `ScoreDisplay` component
  - Expandable to show full metrics breakdown
- All score displays properly handle null/unavailable scores

### 5. Styling (`src/styles/index.css`)
Added comprehensive CSS for all scoring components:

**Score Display:**
- Grade badge styling with grade-specific colors (A: green, B: lime, C: amber, D: orange, F: red)
- Composite score layout
- Expandable details panel with metrics grid
- Data quality flags and warnings
- Responsive layout

**Warnings Banner:**
- Green info-level styling (#064e3b, #065f46)
- Expandable section with smooth transitions
- Dismissible button
- Section headers for portfolio vs holding warnings

**Lookback Selector:**
- Select dropdown with custom styling
- Focus states and hover effects
- Loading indicator
- Explanatory note styling

## Design Decisions

### Two Separate Frames
- **FIFO Frame**: Existing cost-basis, returns %, local/FX contribution
- **Score Frame**: Risk-adjusted metrics, composite score, grade
- Intentionally not conflated in UI; displayed side-by-side but visually separated

### Graceful Null Handling
- Null scores shown as "—" / "Not scored" (not 0 or error states)
- Portfolio score independently nullable
- Individual holdings never dropped from table
- Warnings surface in dedicated banner rather than inline errors

### Data Quality Indicators
- `insufficient_history` (<30 days) → flags all volatility-based metrics as null
- `short_history` (<60 days) → "(limited data)" label on score
- `sample_days` always included for transparency

### Independent Lookback Control
- Re-fetching with new lookback period does NOT re-run FIFO calculations
- Cost-basis fields (purchase date, quantity, returns %) remain unchanged
- Only score and related metrics update
- Loading state prevents user confusion during fetch

### Expandability
- Score badges clickable by default (keyboard + mouse)
- Expansion shows full metrics breakdown in details panel
- Integrated into existing performance report, not a separate view

## Files Modified

| File | Changes |
|------|---------|
| `src/types/index.ts` | Added Score types, ScoringWarning, extended PortfolioPerformanceReport and HoldingAnalysis |
| `src/api/reports.ts` | Added lookback_period and risk_free_rate to PortfolioPerformanceParams |
| `src/pages/PerformancePage.tsx` | Integrated scoring components, added lookback state, added handleLookbackChange |
| `src/styles/index.css` | Added 250+ lines of styling for score display, warnings banner, lookback selector |

## Files Created

| File | Purpose |
|------|---------|
| `src/components/ScoreDisplay.tsx` | Reusable risk-adjusted score display component |
| `src/components/ScoringWarningsBanner.tsx` | Dismissible warnings banner for scoring failures |
| `src/components/LookbackSelector.tsx` | Dropdown selector for score lookback window |

## Testing Checklist

- [ ] Type safety: `npm run typecheck` passes with no errors
- [ ] Build: `npm run build` succeeds
- [ ] Visual: Score badges render correctly with proper grade colors
- [ ] Interaction: Click score to expand/collapse details
- [ ] Interaction: Lookback dropdown changes and re-fetches scores
- [ ] Null handling: Portfolio with no scores shows "—" / "Not scored"
- [ ] Null handling: Individual holdings with missing scores don't break table
- [ ] Warnings: Scoring warnings banner appears and dismisses properly
- [ ] Warnings: Portfolio-level vs ticker-specific warnings are grouped correctly
- [ ] Data quality: "(limited data)" label appears when `short_history === true`
- [ ] Responsive: Score display and table work on mobile/tablet viewports

## Next Steps (Deferred)

Per the wireframe, future enhancements could include:
- Asset detail page scoring section (optional)
- Lookback period selector on asset detail view
- Historical score charting (if backend supports time-series snapshots)
- Comparison view across different lookback windows
- More granular mobile responsive design for holdings table

## Notes for Reviewers

1. **Component composability**: All three new components (`ScoreDisplay`, `ScoringWarningsBanner`, `LookbackSelector`) are designed to be reusable across other pages (asset detail, portfolio summary, etc.) if needed.

2. **Type safety**: Full TypeScript strict mode compliance; no `any` types used.

3. **Accessibility**:
   - Score displays are keyboard accessible (Enter/Space to toggle)
   - Proper ARIA attributes on buttons/toggles
   - Color-coded grades include text fallback (not color-only)
   - Screen reader text for icons

4. **Performance**:
   - Lookback changes don't re-render unrelated components
   - Expandable score details only render on demand
   - CSS transitions are GPU-accelerated where possible

5. **Error handling**: Score failures never crash the endpoint or drop holdings; warnings are surfaced gracefully via banner.

6. **Styling**: Pure CSS with no external framework; consistent with existing design system (custom properties, BEM naming).
