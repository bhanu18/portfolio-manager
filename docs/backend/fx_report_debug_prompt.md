# Claude Code Prompt — Debug `/reports/portfolio-performance` Output

A live run of the `GET /reports/portfolio-performance` endpoint (base_currency `THB`) produced a report with several bugs. Investigate and fix them in priority order. **Diagnose before changing code** — for each bug, first show me the offending code and your root-cause explanation, then propose the fix. Do not restructure the response schema or touch unrelated logic.

Context: this app deliberately uses **historical trade-date FX rates** for cost basis. The whole point is to separate asset performance (local return) from currency movement (FX return). The bugs below break that guarantee.

---

## Bug 1 (CRITICAL) — Historical FX lookup always falls back to 1.0

### Evidence from the live response
- Every USD-native holding reported `fx_rate_at_purchase: 1.0` while `fx_rate_current: 33.139999`.
- `cost_basis_base` equals `cost_basis_original` for USD holdings (e.g. NVDA `2204.6` in both), i.e. a USD cost basis was written into a THB field **with no conversion**. It should be roughly `2204.6 × ~34 ≈ ~73,000 THB`.
- `fx_warnings` contains 10 entries, all of the form:
  `"FX rate unavailable for USD/THB on <date>, using 1.0"`
- Downstream poison: `fx_return_pct: 3214.0` (= (33.14 − 1.0)/1.0), `total_unrealized_gain_loss_pct: 645.57`, `alpha: 555.52`, and `currency_impact_summary` (FX contributing 528%) are all artifacts of comparing a cost at rate 1.0 against value at rate 33.14. `annualized_return` values (NVDA 885%, NFLX 112,771%, ADBE 10,289%) are nonsense for the same reason.

### What is NOT broken (use as a control)
- `local_return_pct` is currency-independent and correct: NVDA +38.1%, NFLX −10.55%, ADBE −37.69%, KTC.BK −34.89%.
- KTC.BK is THB-native, so its `fx_rate 1.0` is legitimately correct and its `*_base` figures are right. Use it to confirm you didn't break the same-currency path while fixing the cross-currency one.

### Investigate (root cause is in the historical-FX helper, not the report logic)
Work out *why* every historical lookup returns nothing and silently defaults to 1.0. Check, in order:
1. **Ticker/pair format**: is it requesting `USDTHB=X`, `THBUSD=X`, `THB=X`, or something yfinance doesn't recognize? Confirm the exact symbol string sent and that it returns data in a manual yfinance call for one of the failing dates (e.g. 2024-10-30).
2. **Date window**: is it requesting a single-day history (`start=date, end=date`) which yfinance returns empty for? It typically needs `end = date + 1 day`, and a widened window for weekends/holidays.
3. **Empty-response handling**: when the fetch returns an empty frame, does the code fall through to `1.0` instead of retrying the nearest previous trading day or raising? A fallback of **1.0 is dangerous** — it's a plausible-looking number that silently corrupts every cross-currency figure.

### Required fix
- Make the historical-FX helper actually resolve trade-date rates. Weekend/holiday dates fall back to the **nearest previous trading day**, not to 1.0.
- If a rate genuinely cannot be found, the fallback must **not** be 1.0 for a cross-currency pair. Prefer (in order): nearest available historical rate, then current spot rate *with a loud warning*, and only as a last resort skip/flag the holding. Never let same-currency logic (rate 1.0) leak into a cross-currency path.
- Keep emitting `fx_warnings`, but the message should reflect what fallback was actually used (e.g. "used nearest trading day 2024-10-29" rather than "using 1.0").

After the fix, re-run and confirm NVDA's `cost_basis_base` is ~73k THB, `fx_return_pct` is a sane single/double-digit number, and the portfolio total return is no longer ~645%.

---

## Bug 2 — Fully-sold "zombie" positions leak through the net-quantity filter

`ADBE` appears with `quantity: 8.326672684688674e-17` — floating-point dust from buys and sells cancelling. It's a closed position that should have been excluded, but the filter uses a strict `quantity > 0` test and `8.3e-17 > 0` is `True`. It then divides tiny-by-tiny and emits garbage (`unrealized_gain_loss_pct: 1965.08`).

**Fix:** replace the `> 0` net-quantity check with an epsilon threshold, e.g. skip the holding when `abs(net_quantity) < 1e-9` (define the epsilon as a named constant). Apply the same threshold consistently everywhere net quantity gates inclusion (holdings loop, scoring, by_currency, by_asset_type, performer rankings).

---

## Bug 3 — `top_performers` and `bottom_performers` are identical

Both arrays are ordered NVDA → NFLX → ADBE → KTC.BK. `bottom_performers` is a copy of `top_performers` instead of an ascending sort. It should be the lowest `total_return_pct` first (KTC.BK, then the losers).

**Fix:** sort descending for `top_performers`, ascending for `bottom_performers`, each capped at 5. Confirm they differ after the fix. (Note the current ordering is also FX-poisoned by Bug 1 — re-verify only after Bug 1 is fixed, since `total_return_pct` will change.)

---

## Bug 4 (VERIFY, may be a spec deviation) — Are scores actually in base currency?

The scoring spec requires the daily price series to be converted to `base_currency` using the daily FX series before computing CAGR/volatility/Sharpe/etc. But in this run:
- `scoring_warnings` is **empty** while `fx_warnings` has 10 failures — the score path apparently didn't hit the same broken FX lookups.
- NVDA `score.metrics.cagr` of 0.2731 (27.3%) reads like a clean **native-USD** market series with no THB conversion applied.

This strongly suggests the scoring path is computing in native currency and skipping FX conversion entirely. Ironically that insulated the scores from Bug 1 — but it's likely a spec violation and makes cross-currency score comparison not apples-to-apples.

**Investigate and report back before changing:** trace whether the scoring series is converted to base currency. If it is *not*, tell me — I want to decide whether to (a) apply base-currency conversion per spec, or (b) intentionally keep scores in native currency and document that choice. Do not silently pick one.

---

## What is already correct — do NOT "fix" these

- **Composite score math is verified sound.** NVDA: `94.61×0.3 + 44.16×0.25 + 67.12×0.2 + 39.09×0.15 + 44.1×0.1 = 63.12` ✓ (grade C ✓). KTC.BK 78.42 ✓ (B), portfolio 46.27 ✓ (D). Grade bands, `is_long_term`, and holding-period days are consistent. Leave the scoring formula alone.
- **KTC.BK scoring B while the position is down 35% is correct by design**, not a bug. The score rates the asset over the trailing ~1y window (`sample_days: 245`), during which it rebounded; the holding return runs from the 2023 entry. This is the intended separation of "asset quality (last 1y)" vs "my position's return." Do not attempt to reconcile them in the backend — instead, leave a code comment noting the two are different frames, and flag to the frontend that these must be labelled distinctly in the UI so a −35% row showing a "B" doesn't read as a bug.

---

## Deliverable
For each of Bugs 1–3: root-cause explanation + before/after code diff. For Bug 4: a diagnosis write-up and a recommendation, but no code change until I confirm the direction. Then a single re-run of the endpoint (base_currency `THB`) showing the corrected NVDA cost basis, FX return, portfolio total return, the removed ADBE position, and the now-distinct performer lists.
