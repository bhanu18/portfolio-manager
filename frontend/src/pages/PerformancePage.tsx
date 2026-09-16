// ---------------------------------------------------------------------------
// Portfolio Performance report — /reports/performance
// Slow endpoint (10–60+ seconds). Uses AbortController + fake progress UX.
// Caches last result in component state so navigating away/back doesn't re-run.
// ---------------------------------------------------------------------------

import { useEffect, useRef, useState } from "react";
import { getPortfolioPerformance } from "../api/reports";
import { parseApiError } from "../lib/errors";
import { formatNumber, formatDate } from "../lib/format";
import type { HoldingAnalysis, PortfolioPerformanceReport } from "../types";
import { Spinner } from "../components/Spinner";
import { ScoreDisplay } from "../components/ScoreDisplay";
import { ScoringWarningsBanner } from "../components/ScoringWarningsBanner";
import { LookbackSelector } from "../components/LookbackSelector";

// ---------------------------------------------------------------------------
// Progress messaging
// ---------------------------------------------------------------------------

const STATUS_MESSAGES = [
  "Fetching trade history…",
  "Getting live prices from Yahoo Finance…",
  "Calculating historical FX rates…",
  "Computing return attribution…",
  "Comparing against benchmark…",
  "Almost there…",
];

const COMMON_CURRENCIES = ["USD", "EUR", "GBP", "THB", "JPY", "SGD"];

// ---------------------------------------------------------------------------
// Sorting helpers
// ---------------------------------------------------------------------------

type SortKey = keyof HoldingAnalysis;
type SortDir = "asc" | "desc";

function sortHoldings(holdings: HoldingAnalysis[], key: SortKey, dir: SortDir): HoldingAnalysis[] {
  return [...holdings].sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    const cmp =
      typeof av === "number" && typeof bv === "number"
        ? av - bv
        : String(av).localeCompare(String(bv));
    return dir === "asc" ? cmp : -cmp;
  });
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

type Phase = "input" | "running" | "results" | "error";

export function PerformancePage() {
  const [phase, setPhase] = useState<Phase>("input");
  const [baseCurrency, setBaseCurrency] = useState("USD");
  const [customCurrency, setCustomCurrency] = useState("");
  const [benchmarkTicker, setBenchmarkTicker] = useState("SPY");
  const [formError, setFormError] = useState<string | null>(null);

  // Progress UX
  const [statusIndex, setStatusIndex] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  // Results
  const [report, setReport] = useState<PortfolioPerformanceReport | null>(null);
  const [cachedAt, setCachedAt] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Sortable holdings table
  const [sortKey, setSortKey] = useState<SortKey>("weight_pct");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // FX warnings collapsed by default
  const [showFxWarnings, setShowFxWarnings] = useState(false);

  // Scoring
  const [lookbackPeriod, setLookbackPeriod] = useState("1y");
  const [scoringLoading, setScoringLoading] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const statusTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Clean up timers on unmount
  useEffect(() => {
    return () => {
      if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current);
      if (statusTimerRef.current) clearInterval(statusTimerRef.current);
    };
  }, []);

  const effectiveCurrency =
    baseCurrency === "__custom__" ? customCurrency.trim().toUpperCase() : baseCurrency;

  function startTimers() {
    setElapsed(0);
    setStatusIndex(0);

    elapsedTimerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
    statusTimerRef.current = setInterval(
      () => setStatusIndex((i) => (i + 1) % STATUS_MESSAGES.length),
      4000,
    );
  }

  function stopTimers() {
    if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current);
    if (statusTimerRef.current) clearInterval(statusTimerRef.current);
    elapsedTimerRef.current = null;
    statusTimerRef.current = null;
  }

  function validate(): boolean {
    if (!effectiveCurrency) {
      setFormError("Please enter a currency code.");
      return false;
    }
    if (!benchmarkTicker.trim()) {
      setFormError("Benchmark ticker is required.");
      return false;
    }
    setFormError(null);
    return true;
  }

  async function handleRun() {
    if (!validate()) return;

    abortRef.current = new AbortController();
    setPhase("running");
    startTimers();

    try {
      const data = await getPortfolioPerformance(
        {
          base_currency: effectiveCurrency,
          benchmark_ticker: benchmarkTicker.trim().toUpperCase(),
        },
        abortRef.current.signal,
      );
      stopTimers();
      setReport(data);
      setCachedAt(new Date().toLocaleString());
      setPhase("results");
    } catch (err) {
      stopTimers();
      // User-initiated cancel — return to input form silently.
      if (err instanceof Error && err.name === "AbortError") {
        setPhase("input");
        return;
      }
      setErrorMsg(parseApiError(err).message);
      setPhase("error");
    }
  }

  function handleCancel() {
    abortRef.current?.abort();
    stopTimers();
    setPhase("input");
  }

  function handleTryAgain() {
    setErrorMsg(null);
    setPhase("input");
  }

  function handleRunAgain() {
    setPhase("input");
  }

  function handleSortClick(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  async function handleLookbackChange(period: string) {
    if (!report) return;
    setLookbackPeriod(period);
    setScoringLoading(true);

    try {
      const data = await getPortfolioPerformance({
        base_currency: report.base_currency,
        benchmark_ticker: report.portfolio_summary.benchmark_ticker,
        lookback_period: period,
      });
      setReport(data);
    } catch (err) {
      console.error("Failed to update scores:", err);
      // Silently fail and keep old report
    } finally {
      setScoringLoading(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Render phases
  // ---------------------------------------------------------------------------

  if (phase === "running") {
    return (
      <div className="perf-progress">
        <Spinner block label={STATUS_MESSAGES[statusIndex]} />
        <p className="muted small" style={{ textAlign: "center" }}>
          Running… {elapsed}s
        </p>
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={handleCancel}
          style={{ marginTop: "0.5rem" }}
        >
          Cancel
        </button>
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div className="error-state" style={{ marginTop: "1rem" }}>
        <p className="error-state__message">{errorMsg}</p>
        <button type="button" className="btn btn--primary btn--sm" onClick={handleTryAgain}>
          Try Again
        </button>
      </div>
    );
  }

  if (phase === "results" && report) {
    return (
      <PerformanceResults
        report={report}
        cachedAt={cachedAt}
        sortKey={sortKey}
        sortDir={sortDir}
        showFxWarnings={showFxWarnings}
        lookbackPeriod={lookbackPeriod}
        scoringLoading={scoringLoading}
        onSortClick={handleSortClick}
        onRunAgain={handleRunAgain}
        onToggleFxWarnings={() => setShowFxWarnings((v) => !v)}
        onLookbackChange={handleLookbackChange}
      />
    );
  }

  // --- Input form (default / after cancel / after "run again") ---
  return (
    <div className="card" style={{ maxWidth: 520 }}>
      <h2 className="card__title">Portfolio Performance Report</h2>
      <p className="muted small" style={{ marginBottom: "1.25rem" }}>
        Fetches live prices + historical FX rates. This may take 10–60+ seconds depending on the
        size of your portfolio.
      </p>

      {/* Cached result banner */}
      {report && cachedAt && (
        <div className="alert alert--info" style={{ marginBottom: "1rem" }}>
          Showing report from {cachedAt}.{" "}
          <button type="button" className="link-button" onClick={() => setPhase("results")}>
            View it
          </button>
        </div>
      )}

      {formError && (
        <div className="alert alert--error" style={{ marginBottom: "1rem" }}>
          {formError}
        </div>
      )}

      {/* Base currency */}
      <div className="field">
        <label className="field__label" htmlFor="perf-currency">
          Base currency
        </label>
        <select
          id="perf-currency"
          className="field__input"
          value={baseCurrency}
          onChange={(e) => setBaseCurrency(e.target.value)}
        >
          {COMMON_CURRENCIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
          <option value="__custom__">Other…</option>
        </select>
      </div>

      {baseCurrency === "__custom__" && (
        <div className="field">
          <label className="field__label" htmlFor="perf-currency-custom">
            Currency code <span aria-hidden>*</span>
          </label>
          <input
            id="perf-currency-custom"
            className="field__input"
            value={customCurrency}
            onChange={(e) => setCustomCurrency(e.target.value)}
            placeholder="e.g. CHF"
            maxLength={8}
          />
        </div>
      )}

      {/* Benchmark ticker */}
      <div className="field">
        <label className="field__label" htmlFor="perf-benchmark">
          Benchmark ticker
        </label>
        <input
          id="perf-benchmark"
          className="field__input"
          value={benchmarkTicker}
          onChange={(e) => setBenchmarkTicker(e.target.value)}
          placeholder="e.g. SPY"
        />
        <span className="field__hint muted">
          Default: SPY. Any yfinance-resolvable ticker works.
        </span>
      </div>

      <button type="button" className="btn btn--primary btn--block" onClick={handleRun}>
        Run Report
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Results view
// ---------------------------------------------------------------------------

interface PerformanceResultsProps {
  report: PortfolioPerformanceReport;
  cachedAt: string | null;
  sortKey: SortKey;
  sortDir: SortDir;
  showFxWarnings: boolean;
  lookbackPeriod: string;
  scoringLoading: boolean;
  onSortClick: (key: SortKey) => void;
  onRunAgain: () => void;
  onToggleFxWarnings: () => void;
  onLookbackChange: (period: string) => void;
}

function PerformanceResults({
  report,
  cachedAt,
  sortKey,
  sortDir,
  showFxWarnings,
  lookbackPeriod,
  scoringLoading,
  onSortClick,
  onRunAgain,
  onToggleFxWarnings,
  onLookbackChange,
}: PerformanceResultsProps) {
  const s = report.portfolio_summary;
  const gainLoss = s.total_unrealized_gain_loss;
  const gainLossPct = s.total_unrealized_gain_loss_pct;
  const positive = gainLoss >= 0;
  const alpha = s.alpha;
  const alphaPositive = alpha >= 0;

  const sortedHoldings = sortHoldings(report.holdings, sortKey, sortDir);

  function sortIndicator(key: SortKey) {
    if (sortKey !== key) return " ↕";
    return sortDir === "asc" ? " ↑" : " ↓";
  }

  const thProps = (key: SortKey) => ({
    onClick: () => onSortClick(key),
    style: { cursor: "pointer", userSelect: "none" as const, whiteSpace: "nowrap" as const },
    title: `Sort by ${key}`,
  });

  return (
    <div className="page" style={{ gap: "1.5rem" }}>
      {/* Scoring warnings banner */}
      <ScoringWarningsBanner warnings={report.scoring_warnings} />

      {/* Cached result banner */}
      {cachedAt && (
        <div
          className="alert alert--info"
          style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
        >
          <span>Showing report from {cachedAt}.</span>
          <button type="button" className="btn btn--ghost btn--sm" onClick={onRunAgain}>
            Run Again
          </button>
        </div>
      )}

      {/* Summary card */}
      <div className="card">
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            flexWrap: "wrap",
            gap: "1rem",
          }}
        >
          <div>
            <h2 className="card__title">
              Summary — {report.base_currency}
              <span className="muted small" style={{ marginLeft: "0.5rem", fontWeight: 400 }}>
                {formatDate(report.report_date)}
              </span>
            </h2>
          </div>
          {report.portfolio_score && (
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <span className="muted small">Risk Score:</span>
              <ScoreDisplay score={report.portfolio_score} compact={true} expandable={true} />
            </div>
          )}
        </div>

        <div className="grid grid--2" style={{ marginTop: "1.25rem" }}>
          <dl className="detail-list">
            <div className="detail-list__row">
              <dt>Total cost basis</dt>
              <dd>{formatNumber(s.total_cost_basis)}</dd>
            </div>
            <div className="detail-list__row">
              <dt>Current value</dt>
              <dd>
                <strong>{formatNumber(s.total_current_value)}</strong>
              </dd>
            </div>
            <div className="detail-list__row">
              <dt>Unrealized P&amp;L</dt>
              <dd className={positive ? "pnl pnl--positive" : "pnl pnl--negative"}>
                {positive ? "+" : ""}
                {formatNumber(gainLoss)}{" "}
                <span className="small">
                  ({positive ? "+" : ""}
                  {gainLossPct.toFixed(2)}%)
                </span>
              </dd>
            </div>
            <div className="detail-list__row">
              <dt>Total return (incl. dividends)</dt>
              <dd>{formatNumber(s.total_return_with_dividends)}</dd>
            </div>
            <div className="detail-list__row">
              <dt>Total dividends received</dt>
              <dd>{formatNumber(s.total_dividends_received)}</dd>
            </div>
          </dl>

          <dl className="detail-list">
            <div className="detail-list__row">
              <dt>Benchmark ({s.benchmark_ticker})</dt>
              <dd>{(s.benchmark_return * 100).toFixed(2)}%</dd>
            </div>
            <div className="detail-list__row">
              <dt>Alpha</dt>
              <dd className={alphaPositive ? "pnl pnl--positive" : "pnl pnl--negative"}>
                {alphaPositive ? "+" : ""}
                {(alpha * 100).toFixed(2)}%
              </dd>
            </div>
            <div className="detail-list__row">
              <dt>FX gain / loss</dt>
              <dd>{formatNumber(s.currency_impact_summary.total_fx_gain_loss)}</dd>
            </div>
            <div className="detail-list__row">
              <dt>FX contribution</dt>
              <dd>{s.currency_impact_summary.total_fx_contribution_pct.toFixed(2)}%</dd>
            </div>
            <div className="detail-list__row">
              <dt>Local contribution</dt>
              <dd>{s.currency_impact_summary.total_local_contribution_pct.toFixed(2)}%</dd>
            </div>
          </dl>
        </div>
      </div>

      {/* Top / Bottom performers */}
      <div className="grid grid--2">
        <div className="card">
          <h2 className="card__title">🏆 Top Performers</h2>
          <div className="table-wrap" style={{ marginTop: "0.75rem" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th className="num">Total Return</th>
                </tr>
              </thead>
              <tbody>
                {report.top_performers.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="muted">
                      No data
                    </td>
                  </tr>
                ) : (
                  report.top_performers.map((p) => (
                    <tr key={p.ticker}>
                      <td>{p.ticker}</td>
                      <td
                        className={`num pnl ${p.total_return_pct >= 0 ? "pnl--positive" : "pnl--negative"}`}
                      >
                        {p.total_return_pct >= 0 ? "+" : ""}
                        {p.total_return_pct.toFixed(2)}%
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <h2 className="card__title">📉 Bottom Performers</h2>
          <div className="table-wrap" style={{ marginTop: "0.75rem" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th className="num">Total Return</th>
                </tr>
              </thead>
              <tbody>
                {report.bottom_performers.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="muted">
                      No data
                    </td>
                  </tr>
                ) : (
                  report.bottom_performers.map((p) => (
                    <tr key={p.ticker}>
                      <td>{p.ticker}</td>
                      <td
                        className={`num pnl ${p.total_return_pct >= 0 ? "pnl--positive" : "pnl--negative"}`}
                      >
                        {p.total_return_pct >= 0 ? "+" : ""}
                        {p.total_return_pct.toFixed(2)}%
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Lookback selector (for scoring) */}
      {report.portfolio_score && (
        <div className="card" style={{ paddingTop: "1rem", paddingBottom: "1rem" }}>
          <LookbackSelector
            currentLookback={lookbackPeriod}
            onLookbackChange={onLookbackChange}
            loading={scoringLoading}
          />
        </div>
      )}

      {/* Holdings table */}
      <div className="card">
        <h2 className="card__title">Holdings ({report.holdings.length})</h2>
        <p className="muted small">Click column headers to sort.</p>
        <div className="table-wrap" style={{ marginTop: "0.75rem" }}>
          <table className="table">
            <thead>
              <tr>
                <th {...thProps("ticker")}>Ticker{sortIndicator("ticker")}</th>
                <th {...thProps("asset_name")}>Name{sortIndicator("asset_name")}</th>
                <th className="num" {...thProps("quantity")}>
                  Qty{sortIndicator("quantity")}
                </th>
                <th className="num" {...thProps("cost_basis_base")}>
                  Cost Basis{sortIndicator("cost_basis_base")}
                </th>
                <th className="num" {...thProps("current_value_base")}>
                  Curr. Value{sortIndicator("current_value_base")}
                </th>
                <th className="num" {...thProps("unrealized_gain_loss_base")}>
                  P&amp;L{sortIndicator("unrealized_gain_loss_base")}
                </th>
                <th className="num" {...thProps("total_return_pct")}>
                  Total Ret%{sortIndicator("total_return_pct")}
                </th>
                <th className="num" {...thProps("local_return_pct")}>
                  Local Ret%{sortIndicator("local_return_pct")}
                </th>
                <th className="num" {...thProps("fx_return_pct")}>
                  FX Ret%{sortIndicator("fx_return_pct")}
                </th>
                <th className="num" {...thProps("weight_pct")}>
                  Weight%{sortIndicator("weight_pct")}
                </th>
                <th className="num" {...thProps("holding_period_days")}>
                  Days Held{sortIndicator("holding_period_days")}
                </th>
                <th className="num" {...thProps("annualized_return")}>
                  Ann. Ret%{sortIndicator("annualized_return")}
                </th>
                <th>LT?</th>
                <th>Risk Score</th>
              </tr>
            </thead>
            <tbody>
              {sortedHoldings.map((h) => {
                const gl = h.unrealized_gain_loss_base;
                return (
                  <tr key={h.ticker}>
                    <td>
                      <strong>{h.ticker}</strong>
                    </td>
                    <td
                      className="muted"
                      style={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis" }}
                    >
                      {h.asset_name}
                    </td>
                    <td className="num">{formatNumber(h.quantity)}</td>
                    <td className="num">{formatNumber(h.cost_basis_base)}</td>
                    <td className="num">{formatNumber(h.current_value_base)}</td>
                    <td className={`num pnl ${gl >= 0 ? "pnl--positive" : "pnl--negative"}`}>
                      {gl >= 0 ? "+" : ""}
                      {formatNumber(gl)}
                    </td>
                    <td
                      className={`num pnl ${h.total_return_pct >= 0 ? "pnl--positive" : "pnl--negative"}`}
                    >
                      {h.total_return_pct >= 0 ? "+" : ""}
                      {h.total_return_pct.toFixed(2)}%
                    </td>
                    <td className="num">{h.local_return_pct.toFixed(2)}%</td>
                    <td className="num">{h.fx_return_pct.toFixed(2)}%</td>
                    <td className="num">{h.weight_pct.toFixed(2)}%</td>
                    <td className="num">{h.holding_period_days}</td>
                    <td className="num">{(h.annualized_return * 100).toFixed(2)}%</td>
                    <td>
                      {h.is_long_term ? (
                        <span className="badge badge--buy">LT</span>
                      ) : (
                        <span className="badge badge--muted">ST</span>
                      )}
                    </td>
                    <td>
                      <ScoreDisplay score={h.score} compact={true} expandable={true} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* By currency breakdown */}
      {Object.keys(report.by_currency).length > 0 && (
        <div className="card">
          <h2 className="card__title">By Currency</h2>
          <div className="table-wrap" style={{ marginTop: "0.75rem" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Currency</th>
                  <th className="num">Value</th>
                  <th className="num">Cost Basis</th>
                  <th className="num">Weight%</th>
                  <th className="num">Local Ret%</th>
                  <th className="num">FX Ret%</th>
                  <th className="num">Total Ret%</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(report.by_currency).map(([cur, b]) => (
                  <tr key={cur}>
                    <td>
                      <strong>{cur}</strong>
                    </td>
                    <td className="num">{formatNumber(b.value_base)}</td>
                    <td className="num">{formatNumber(b.cost_basis_base)}</td>
                    <td className="num">{b.weight_pct.toFixed(2)}%</td>
                    <td className="num">{b.local_return_pct.toFixed(2)}%</td>
                    <td className="num">{b.fx_return_pct.toFixed(2)}%</td>
                    <td
                      className={`num pnl ${b.total_return_pct >= 0 ? "pnl--positive" : "pnl--negative"}`}
                    >
                      {b.total_return_pct >= 0 ? "+" : ""}
                      {b.total_return_pct.toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* By asset type breakdown */}
      {Object.keys(report.by_asset_type).length > 0 && (
        <div className="card">
          <h2 className="card__title">By Asset Type</h2>
          <div className="table-wrap" style={{ marginTop: "0.75rem" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Type</th>
                  <th className="num">Value</th>
                  <th className="num">Cost Basis</th>
                  <th className="num">Weight%</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(report.by_asset_type).map(([type, b]) => (
                  <tr key={type}>
                    <td>
                      <strong>{type}</strong>
                    </td>
                    <td className="num">{formatNumber(b.value_base)}</td>
                    <td className="num">{formatNumber(b.cost_basis_base)}</td>
                    <td className="num">{b.weight_pct.toFixed(2)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* FX Warnings (collapsed by default) */}
      {report.fx_warnings.length > 0 && (
        <div className="card">
          <button
            type="button"
            className="link-button"
            onClick={onToggleFxWarnings}
            style={{ fontSize: "1rem", fontWeight: 600, color: "var(--color-warn)" }}
          >
            ⚠️ FX Warnings ({report.fx_warnings.length}) {showFxWarnings ? "▲ Hide" : "▼ Show"}
          </button>
          {showFxWarnings && (
            <div style={{ marginTop: "0.75rem" }}>
              <p className="muted small" style={{ marginBottom: "0.5rem" }}>
                Historical FX rates fell back to current-day rates for the tickers below. Cost basis
                calculations may be slightly inaccurate.
              </p>
              <ul style={{ margin: 0, padding: "0 0 0 1.25rem", fontSize: "0.9rem" }}>
                {report.fx_warnings.map((w, i) => (
                  <li key={i} style={{ marginBottom: "0.25rem" }}>
                    <strong>{w.ticker}</strong>: {w.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
