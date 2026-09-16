# Claude Code Prompt — Confirm Scoring FX Conversion + Consolidate FX Helpers

Two related follow-ups from the Bug 4 diagnosis on `/reports/portfolio-performance`. Task 1 is a verification (prove the scoring path really converts to base currency; the report-level numbers alone are inconclusive). Task 2 is a maintainability cleanup (there are two separate FX-fetching code paths and only one was fixed in the Bug 1 work).

Do the verification in Task 1 **first** and report results before touching anything in Task 2.

---

## Task 1 — Differential test: confirm scoring is actually in base currency

### Why this is needed
The Bug 4 diagnosis concluded scoring already converts to base currency via:
```python
fx_series      = get_historical_fx_series(trade_currency, base_currency, start_date, end_date)
fx_aligned     = fx_series.reindex(price_series.index, method="ffill").bfill()
price_series_base = price_series * fx_aligned
```
That code reads correctly — but **the live report numbers cannot confirm it**. NVDA's score CAGR (~26.5%) and volatility (~0.347) look native-USD, but that's equally consistent with *conversion happening* when USD/THB was roughly flat over the lookback window. The value proves nothing either way. Bug 1 was also code that "looked correct" while silently returning 1.0, so confirm this by execution, not by reading.

### The test — do BOTH checks

**Check A — force-off differential (deterministic, preferred).**
For a single USD-native holding (use NVDA), compute the score metrics twice over the *same* lookback window:
1. Normal path (conversion on).
2. A control path with FX conversion disabled — i.e. skip the `price_series * fx_aligned` step and score the raw native series.

Then diff the two metric sets. Expected result **if conversion is genuinely happening**:
- CAGR should differ by approximately the USD/THB drift over the window: `(1 + native_cagr) * (fx_end / fx_start)^(365/days) - 1`. If USD/THB barely moved, this difference will be *small but non-zero* — verify it is not exactly zero.
- Volatility of the converted series should be `>=` native volatility (the daily FX path adds variance unless fully damped by ffill).
- If the two metric sets are **bit-identical**, conversion is NOT being applied — that's the bug, report it.

Print both metric sets side by side plus the computed differences. Do not assert pass/fail silently — show the numbers.

**Check B — sharp-FX-window sanity check.**
Re-run the NVDA score over a lookback window where USD/THB moved materially (pick a period with a visible baht move; confirm the move first with a manual `get_historical_fx_series` call). Over that window the converted CAGR/volatility should visibly diverge from the native figures. If they don't diverge when FX genuinely moved, conversion is not wired in.

### Report back
- The side-by-side metrics from Check A and the divergence from Check B.
- A one-line verdict: "conversion confirmed" or "conversion NOT applied."
- **Do not change scoring behavior as part of this task.** If the test confirms conversion, the current base-currency scoring is spec-compliant — keep it and just add a short docstring/code comment noting scores are computed in `base_currency` (converted via the daily FX series), so this doesn't get re-questioned later. If the test shows conversion is missing, stop and report; I'll decide the fix direction separately.

---

## Task 2 — Consolidate the two FX-fetching code paths (maintainability)

### The problem
The Bug 1 fix corrected the **cost-basis / report** FX lookup, but the **scoring** path uses a *different* helper (`get_historical_fx_series`) that was never buggy and never touched by that fix. So there are now (at least) two independent historical-FX fetchers in the codebase:
- the one used for per-lot cost-basis conversion in the report path (recently fixed), and
- `get_historical_fx_series` used by scoring.

Two paths that fetch the same conceptual data (historical FX for a currency pair) can drift — a future fix or yfinance-format change applied to one won't reach the other. That's the same class of latent risk that produced Bug 1.

### What to do — inspect and propose, do NOT refactor yet
1. **Inventory:** find every place historical FX is fetched (grep for `=X`, `get_historical_fx`, yfinance history calls on currency pairs). List each call site, its signature, what it returns (single rate vs series, tz-aware vs naive index), and its weekend/holiday-gap handling.
2. **Compare behavior:** specifically confirm whether the report-path helper and `get_historical_fx_series` now handle these identically: (a) nearest-previous-trading-day fallback for weekends/holidays, (b) the tz-localize(None) normalization, (c) the never-fall-back-to-1.0-for-cross-currency rule from the Bug 1 fix. Flag any divergence.
3. **Propose (no code change):** recommend a single shared helper both paths call — e.g. a `get_historical_fx_series(...)` as the canonical primitive, with the single-date lookup implemented as "fetch a small series and take the nearest prior day" on top of it. Describe the minimal refactor to route the report path through it, what the shared contract should be, and the regression risk.
4. **Verify-first guard:** note that after any future consolidation, the KTC.BK same-currency control (rate 1.0, `cost_basis_base == cost_basis_original`) and the NVDA cross-currency cost basis (~74k THB) must both still hold. These are the two regression checks.

### Deliverable for Task 2
A short write-up: the call-site inventory, the behavior-divergence table, and the proposed consolidation plan with its regression risks. **No refactor until I approve the plan** — this is backlog scoping, not implementation.

---

## Overall
Task 1 is safe to execute now (it only reads/compares, doesn't mutate scoring). Task 2 is inspection-and-propose only. Report Task 1's verdict and Task 2's plan; wait for my go-ahead before any consolidation refactor.
