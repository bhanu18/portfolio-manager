// ---------------------------------------------------------------------------
// Overview — Modernist dashboard.
//
// Implements option 1a of docs/frontend/Portfolio Dashboard (Modernist).dc.html
// ("Overview · top nav, numbers-first"), with the loading and empty treatments
// from options 2a and 2b.
//
// The page owns its own top nav rather than rendering inside the app's dark
// Layout: the design's nav carries the base-currency / benchmark tags and the
// Refresh prices action, and stacking it under a second nav would put
// two navs on one screen. Its links route into the rest of the app.
//
// The performance report is the slow endpoint (10–60+s). It starts on mount and
// is cancellable, matching state 2a: positions and the headline figure come
// from the report's fast half, the analysis fills in behind a skeleton.
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import * as assetsApi from "../api/assets";
import * as tradesApi from "../api/trades";
import { getPortfolioPerformance } from "../api/reports";
import { useAuth } from "../context/AuthContext";
import { parseApiError } from "../lib/errors";
import {
  buildActivity,
  buildAllocation,
  buildHoldingRows,
  buildKpis,
  buildMovers,
  money,
  signedMoney,
  signedPct,
} from "../lib/overview";
import type { PortfolioPerformanceReport, Trade } from "../types";
import { ModernistNav } from "../components/ModernistNav";
import "../styles/modernist.css";

const BASE_CURRENCY = "USD";
const BENCHMARK = "SPY";

const STATUS_MESSAGES = [
  "Fetching trade history…",
  "Getting live prices from Yahoo Finance…",
  "Calculating historical FX rates…",
  "Computing return attribution…",
  "Comparing against benchmark…",
  "Almost there…",
];

/** One-line reading of the portfolio grade, from whichever metrics exist. */
function gradeBlurb(report: PortfolioPerformanceReport): string {
  const s = report.portfolio_summary;
  const m = report.portfolio_score?.metrics;
  const beatBenchmark = s.alpha > 0;
  const lead = beatBenchmark ? `Ahead of ${s.benchmark_ticker}` : `Behind ${s.benchmark_ticker}`;

  if (m?.volatility != null && m?.max_drawdown != null) {
    return `${lead} on return, with volatility at ${m.volatility.toFixed(
      1,
    )}% and a ${Math.abs(m.max_drawdown).toFixed(1)}% worst drawdown.`;
  }
  return `${lead} on return. Risk metrics arrive with the scoring run.`;
}

export function OverviewPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const groups = useMemo(() => user?.groups ?? [], [user]);

  // --- Recent activity: fan out across every group the user belongs to. -----
  const { data: trades = [] } = useQuery<Trade[]>({
    queryKey: ["overview", "trades", groups.map((g) => g.id).join(",")],
    queryFn: async () => {
      if (groups.length === 0) return [];
      const perGroup = await Promise.all(
        groups.map((g) => tradesApi.listTradesInGroup(g.id).catch(() => [] as Trade[])),
      );
      return perGroup.flat();
    },
  });

  // --- Performance report ---------------------------------------------------
  const [report, setReport] = useState<PortfolioPerformanceReport | null>(null);
  const [running, setRunning] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [statusIndex, setStatusIndex] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  // Fires the request and settles state in its callbacks only — the initial
  // state above is already the "running" state, so mounting doesn't have to
  // set anything synchronously.
  const startRequest = useCallback(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    getPortfolioPerformance(
      {
        base_currency: BASE_CURRENCY,
        benchmark_ticker: BENCHMARK,
      },
      controller.signal,
    )
      .then((data) => {
        if (controller.signal.aborted) return;
        setReport(data);
        setRunning(false);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(parseApiError(err).message);
        setRunning(false);
      });
  }, []);

  /** Re-run from a user action (retry, refresh prices): reset, then fire. */
  const run = useCallback(() => {
    setRunning(true);
    setError(null);
    setElapsed(0);
    setStatusIndex(0);
    startRequest();
  }, [startRequest]);

  useEffect(() => {
    startRequest();
    return () => abortRef.current?.abort();
  }, [startRequest]);

  // Elapsed counter + rotating status line, only while the run is in flight.
  useEffect(() => {
    if (!running) return;
    const tick = window.setInterval(() => setElapsed((e) => e + 1), 1000);
    const rotate = window.setInterval(
      () => setStatusIndex((i) => Math.min(i + 1, STATUS_MESSAGES.length - 1)),
      8000,
    );
    return () => {
      window.clearInterval(tick);
      window.clearInterval(rotate);
    };
  }, [running]);

  const cancel = () => {
    abortRef.current?.abort();
    setRunning(false);
  };

  // --- Refresh prices -------------------------------------------------------
  const [refreshing, setRefreshing] = useState(false);
  const refreshPrices = async () => {
    setRefreshing(true);
    try {
      await assetsApi.updateAllPrices();
      run();
    } catch (err: unknown) {
      setError(parseApiError(err).message);
    } finally {
      setRefreshing(false);
    }
  };

  // --- Derived view models --------------------------------------------------
  const summary = report?.portfolio_summary;
  const holdingRows = useMemo(
    () => (report ? buildHoldingRows(report.holdings, report.base_currency) : []),
    [report],
  );
  const kpis = useMemo(() => (report ? buildKpis(report) : []), [report]);
  const allocation = useMemo(
    () => (report ? buildAllocation(report.by_asset_type, report.base_currency) : []),
    [report],
  );
  const movers = useMemo(() => (report ? buildMovers(report) : []), [report]);
  const activity = useMemo(() => buildActivity(trades), [trades]);

  const isEmpty = !running && !error && report != null && report.holdings.length === 0;
  const scoring = report?.portfolio_score;

  return (
    <div className="mod" style={{ minHeight: "100%" }}>
      <ModernistNav onRecorded={run}>
        <span className="tag tag-neutral fig" style={{ marginLeft: "var(--space-4)" }}>
          {BASE_CURRENCY}
        </span>
        <span className="tag tag-neutral fig">{BENCHMARK}</span>
        {!running && (
          <button
            className="btn btn-secondary"
            type="button"
            onClick={refreshPrices}
            disabled={refreshing}
          >
            {refreshing ? "Refreshing…" : "Refresh prices"}
          </button>
        )}
      </ModernistNav>

      {running && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--space-3)",
            padding: "var(--space-3) var(--space-8)",
            borderBottom: "2px solid var(--color-divider)",
            background: "var(--color-accent-100)",
          }}
        >
          <span className="spinner" aria-hidden="true" />
          <span style={{ flex: 1, fontSize: 13, fontWeight: 600 }} role="status">
            {STATUS_MESSAGES[statusIndex]}
          </span>
          <span className="fig" style={{ fontSize: 12, color: "var(--color-accent-800)" }}>
            {elapsed}s elapsed · usually 10–60s
          </span>
          <button className="btn btn-secondary" type="button" onClick={cancel}>
            Cancel
          </button>
        </div>
      )}

      {error && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--space-3)",
            padding: "var(--space-3) var(--space-8)",
            borderBottom: "2px solid var(--color-accent)",
            background: "var(--color-accent-100)",
          }}
        >
          <span style={{ flex: 1, fontSize: 13, fontWeight: 600 }}>{error}</span>
          <button className="btn btn-secondary" type="button" onClick={run}>
            Try again
          </button>
        </div>
      )}

      <div
        style={{
          padding: "var(--space-8)",
          display: "flex",
          flexDirection: "column",
          gap: "var(--space-8)",
        }}
      >
        {isEmpty ? (
          <EmptyOverview
            groupName={groups[0]?.name}
            onNewTrade={() => navigate("/overview?recordTrade=1")}
            onBrowseAssets={() => navigate("/research")}
          />
        ) : (
          <>
            {/* --- Headline figure + portfolio grade ------------------------ */}
            <div
              style={{
                display: "flex",
                alignItems: "flex-end",
                justifyContent: "space-between",
                gap: "var(--space-8)",
              }}
            >
              <div>
                <h6 style={{ margin: "0 0 var(--space-2)", color: "var(--color-neutral-700)" }}>
                  Total portfolio value
                </h6>
                <div style={{ display: "flex", alignItems: "baseline", gap: "var(--space-4)" }}>
                  {summary ? (
                    <span
                      className="fig"
                      style={{
                        fontSize: 60,
                        fontWeight: 800,
                        lineHeight: 1,
                        letterSpacing: "-.025em",
                      }}
                    >
                      {money(summary.total_current_value, BASE_CURRENCY)}
                    </span>
                  ) : (
                    <span className="sk" style={{ width: 380, height: 54 }} />
                  )}
                  {summary ? (
                    <span
                      className="fig"
                      style={{
                        fontSize: 22,
                        fontWeight: 800,
                        lineHeight: 1,
                        color:
                          summary.total_unrealized_gain_loss_pct < 0
                            ? "var(--color-accent)"
                            : "var(--color-text)",
                      }}
                    >
                      {signedPct(summary.total_unrealized_gain_loss_pct)}
                      <span className="metric-caption">Unrealized return</span>
                    </span>
                  ) : (
                    <span className="sk" style={{ width: 112, height: 26 }} />
                  )}
                </div>
                <div
                  className="fig"
                  style={{
                    marginTop: "var(--space-3)",
                    fontSize: 13.5,
                    color: "var(--color-neutral-700)",
                  }}
                >
                  {summary ? (
                    <>
                      {signedMoney(summary.total_unrealized_gain_loss, BASE_CURRENCY)} unrealized ·{" "}
                      {money(summary.total_cost_basis, BASE_CURRENCY)} invested ·{" "}
                      {money(summary.total_dividends_received, BASE_CURRENCY)} dividends
                    </>
                  ) : (
                    <span className="sk" style={{ width: 300, height: 12 }} />
                  )}
                </div>
              </div>

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "var(--space-4)",
                  padding: "var(--space-4)",
                  border: "2px solid var(--color-divider)",
                }}
              >
                {scoring?.grade && report ? (
                  <>
                    <div className="fig" style={{ fontSize: 44, fontWeight: 800, lineHeight: 0.9 }}>
                      {scoring.grade}
                    </div>
                    <div
                      style={{
                        borderLeft: "2px solid var(--color-divider)",
                        paddingLeft: "var(--space-4)",
                      }}
                    >
                      <div style={{ fontWeight: 800, fontSize: 14 }}>
                        Portfolio grade ·{" "}
                        <span className="fig">
                          {scoring.composite_score != null
                            ? `${Math.round(scoring.composite_score)}/100`
                            : "—"}
                        </span>
                      </div>
                      <div
                        style={{
                          fontSize: 12.5,
                          color: "var(--color-neutral-800)",
                          maxWidth: 240,
                          textWrap: "pretty",
                        }}
                      >
                        {gradeBlurb(report)}
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <span className="sk" style={{ width: 48, height: 48 }} />
                    <div
                      style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}
                    >
                      <span className="sk" style={{ width: 150, height: 13 }} />
                      <span className="sk sk-faint" style={{ width: 230, height: 11 }} />
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* --- KPI strip ------------------------------------------------ */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(4,1fr)",
                borderTop: "2px solid var(--color-divider)",
                borderBottom: "2px solid var(--color-divider)",
              }}
            >
              {(kpis.length
                ? kpis
                : [
                    { label: "Alpha" },
                    { label: "Currency impact" },
                    { label: "Volatility" },
                    { label: "Max drawdown" },
                  ]
              ).map((k, i) => (
                <div
                  key={k.label}
                  style={{
                    padding: "var(--space-4)",
                    borderLeft: i === 0 ? "none" : "2px solid var(--color-divider)",
                  }}
                >
                  <h6 style={{ margin: 0, color: "var(--color-neutral-700)" }}>{k.label}</h6>
                  {"value" in k ? (
                    <>
                      <div
                        className="fig"
                        style={{
                          marginTop: "var(--space-2)",
                          fontSize: 28,
                          fontWeight: 800,
                          lineHeight: 1,
                          color: k.color,
                        }}
                      >
                        {k.value}
                      </div>
                      <div
                        style={{
                          marginTop: "var(--space-2)",
                          fontSize: 12.5,
                          color: "var(--color-neutral-700)",
                        }}
                      >
                        {k.note}
                      </div>
                    </>
                  ) : (
                    <>
                      <span
                        className="sk"
                        style={{ marginTop: "var(--space-3)", width: 124, height: 28 }}
                      />
                      <span
                        className="sk sk-faint"
                        style={{ marginTop: "var(--space-3)", width: 164, height: 11 }}
                      />
                    </>
                  )}
                </div>
              ))}
            </div>

            {/* --- Holdings + rail ------------------------------------------ */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(0,1fr) 336px",
                gap: "var(--space-8)",
                alignItems: "start",
              }}
            >
              <div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "baseline",
                    justifyContent: "space-between",
                    marginBottom: "var(--space-2)",
                  }}
                >
                  <h4 style={{ margin: 0 }}>Holdings</h4>
                  <span style={{ fontSize: 12.5, color: "var(--color-neutral-700)" }}>
                    {holdingRows.length > 0 && (
                      <>
                        {holdingRows.length} position{holdingRows.length === 1 ? "" : "s"} ·{" "}
                      </>
                    )}
                    {running ? "returns pending" : "sorted by weight"}
                  </span>
                </div>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Asset</th>
                      <th style={{ textAlign: "right" }}>Value</th>
                      <th style={{ width: 150 }}>Weight</th>
                      <th style={{ textAlign: "right" }}>Total return</th>
                      <th style={{ textAlign: "right" }}>Grade</th>
                    </tr>
                  </thead>
                  <tbody>
                    {holdingRows.length === 0 && running
                      ? Array.from({ length: 6 }, (_, i) => (
                          <tr key={`sk-${i}`}>
                            <td>
                              <span className="sk" style={{ width: 120, height: 13 }} />
                              <span
                                className="sk sk-faint"
                                style={{ marginTop: 4, width: 90, height: 11 }}
                              />
                            </td>
                            <td style={{ textAlign: "right" }}>
                              <span
                                className="sk"
                                style={{ display: "inline-block", width: 78, height: 13 }}
                              />
                            </td>
                            <td>
                              <span className="sk sk-faint" style={{ width: "100%", height: 6 }} />
                            </td>
                            <td style={{ textAlign: "right" }}>
                              <span
                                className="sk"
                                style={{ display: "inline-block", width: 64, height: 13 }}
                              />
                            </td>
                            <td style={{ textAlign: "right" }}>
                              <span
                                className="sk"
                                style={{ display: "inline-block", width: 26, height: 19 }}
                              />
                            </td>
                          </tr>
                        ))
                      : holdingRows.map((h) => (
                          <tr key={h.key} className="holding-row">
                            <td>
                              <div
                                style={{
                                  display: "flex",
                                  alignItems: "baseline",
                                  gap: "var(--space-2)",
                                }}
                              >
                                <Link
                                  className="fig holding-link"
                                  to={`/holdings/${encodeURIComponent(h.ticker)}`}
                                  aria-label={`View ${h.ticker} holding`}
                                >
                                  {h.ticker}
                                </Link>
                                <span
                                  style={{
                                    fontSize: 12.5,
                                    color: "var(--color-neutral-700)",
                                    maxWidth: 150,
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                    whiteSpace: "nowrap",
                                  }}
                                >
                                  {h.name}
                                </span>
                              </div>
                              <div
                                className="fig"
                                style={{
                                  marginTop: 2,
                                  fontSize: 11.5,
                                  color: "var(--color-neutral-700)",
                                }}
                              >
                                {h.position}
                              </div>
                            </td>
                            <td
                              className="fig"
                              style={{ textAlign: "right", whiteSpace: "nowrap" }}
                            >
                              {h.value}
                            </td>
                            <td>
                              <div
                                style={{
                                  display: "flex",
                                  alignItems: "center",
                                  gap: "var(--space-2)",
                                }}
                              >
                                <div
                                  style={{
                                    flex: 1,
                                    height: 6,
                                    background: "var(--color-neutral-200)",
                                  }}
                                >
                                  <div
                                    style={{
                                      height: 6,
                                      background: h.barColor,
                                      width: h.barWidth,
                                    }}
                                  />
                                </div>
                                <span
                                  className="fig"
                                  style={{
                                    fontSize: 11.5,
                                    color: "var(--color-neutral-700)",
                                    width: 42,
                                    textAlign: "right",
                                  }}
                                >
                                  {h.weight}
                                </span>
                              </div>
                            </td>
                            <td
                              className="fig"
                              style={{
                                textAlign: "right",
                                fontWeight: 800,
                                whiteSpace: "nowrap",
                                color: h.retColor,
                              }}
                            >
                              {h.totalRet}
                            </td>
                            <td style={{ textAlign: "right" }}>
                              <span
                                className={`tag ${h.gradeClass}`.trim()}
                                style={{ fontWeight: 800 }}
                              >
                                {h.grade}
                              </span>
                            </td>
                          </tr>
                        ))}
                  </tbody>
                </table>
              </div>

              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: running ? "var(--space-6)" : "var(--space-8)",
                }}
              >
                {/* --- Allocation ------------------------------------------ */}
                <div>
                  <h4 style={{ margin: "0 0 var(--space-3)" }}>Allocation</h4>
                  <div style={{ display: "flex", height: 10 }}>
                    {allocation.map((a) => (
                      <div key={a.key} style={{ background: a.color, width: a.width }} />
                    ))}
                    {allocation.length === 0 && (
                      <div className="sk sk-faint" style={{ width: "100%", height: 10 }} />
                    )}
                  </div>
                  <div style={{ marginTop: "var(--space-3)" }}>
                    {allocation.map((a) => (
                      <div
                        key={a.key}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "var(--space-2)",
                          padding: "var(--space-2) 0",
                          borderBottom: "1px solid var(--color-divider)",
                        }}
                      >
                        <span style={{ width: 9, height: 9, background: a.color, flex: "none" }} />
                        <span
                          style={{
                            flex: 1,
                            fontSize: 13,
                            textTransform: "uppercase",
                            letterSpacing: ".04em",
                          }}
                        >
                          {a.label}
                        </span>
                        <span
                          className="fig"
                          style={{ fontSize: 12.5, color: "var(--color-neutral-700)" }}
                        >
                          {a.value}
                        </span>
                        <span
                          className="fig"
                          style={{
                            fontSize: 12.5,
                            fontWeight: 800,
                            width: 48,
                            textAlign: "right",
                          }}
                        >
                          {a.pct}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* --- Movers ---------------------------------------------- */}
                <div>
                  <h4 style={{ margin: "0 0 var(--space-1)" }}>Movers</h4>
                  <p
                    style={{
                      fontSize: 12,
                      color: "var(--color-neutral-700)",
                      margin: "0 0 var(--space-3)",
                    }}
                  >
                    {running ? "Waiting on the performance run" : "Total return, all time"}
                  </p>
                  {movers.length === 0
                    ? Array.from({ length: 5 }, (_, i) => (
                        <div
                          key={`msk-${i}`}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "var(--space-2)",
                            padding: "var(--space-2) 0",
                            borderBottom: "1px solid var(--color-divider)",
                          }}
                        >
                          <span className="sk" style={{ width: 58, height: 12 }} />
                          <span className="sk sk-faint" style={{ flex: 1, height: 6 }} />
                          <span className="sk" style={{ width: 48, height: 12 }} />
                        </div>
                      ))
                    : movers.map((m) => (
                        <div
                          key={m.key}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "var(--space-2)",
                            padding: "var(--space-2) 0",
                            borderBottom: "1px solid var(--color-divider)",
                          }}
                        >
                          <span
                            className="fig"
                            style={{ fontWeight: 800, fontSize: 12.5, width: 66 }}
                          >
                            {m.ticker}
                          </span>
                          <div
                            style={{
                              flex: 1,
                              height: 6,
                              background: "var(--color-neutral-200)",
                              position: "relative",
                            }}
                          >
                            <span
                              style={{
                                position: "absolute",
                                top: -2,
                                bottom: -2,
                                left: "50%",
                                width: 2,
                                background: "var(--color-neutral-400)",
                              }}
                            />
                            <div
                              style={{
                                position: "absolute",
                                top: 0,
                                height: 6,
                                background: m.color,
                                left: m.left,
                                width: m.width,
                              }}
                            />
                          </div>
                          <span
                            className="fig"
                            style={{
                              fontWeight: 800,
                              fontSize: 12.5,
                              width: 64,
                              textAlign: "right",
                              color: m.color,
                            }}
                          >
                            {m.value}
                          </span>
                        </div>
                      ))}
                </div>

                {/* --- Recent activity ------------------------------------- */}
                <div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "baseline",
                      justifyContent: "space-between",
                      marginBottom: "var(--space-3)",
                    }}
                  >
                    <h4 style={{ margin: 0 }}>Recent activity</h4>
                    <Link to="/trades" style={{ fontSize: 12.5, fontWeight: 800 }}>
                      All trades
                    </Link>
                  </div>
                  {activity.map((t) => (
                    <div
                      key={t.key}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "var(--space-2)",
                        padding: "var(--space-2) 0",
                        borderBottom: "1px solid var(--color-divider)",
                      }}
                    >
                      <span className={`tag ${t.tagClass}`.trim()} style={{ flex: "none" }}>
                        {t.typeLabel}
                      </span>
                      <span className="fig" style={{ fontWeight: 800, fontSize: 12.5, width: 62 }}>
                        {t.ticker}
                      </span>
                      <span
                        className="fig"
                        style={{
                          flex: 1,
                          fontSize: 11.5,
                          color: "var(--color-neutral-700)",
                        }}
                      >
                        {t.detail}
                      </span>
                      <span
                        className="fig"
                        style={{
                          fontSize: 11.5,
                          color: "var(--color-neutral-700)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {t.date}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Nav
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Empty state (design option 2b)
// ---------------------------------------------------------------------------

function EmptyOverview({
  groupName,
  onNewTrade,
  onBrowseAssets,
}: {
  groupName?: string;
  onNewTrade: () => void;
  onBrowseAssets: () => void;
}) {
  return (
    <>
      <div>
        <h6 style={{ margin: "0 0 var(--space-2)", color: "var(--color-neutral-700)" }}>
          Total portfolio value
        </h6>
        <span
          className="fig"
          style={{
            fontSize: 60,
            fontWeight: 800,
            lineHeight: 1,
            letterSpacing: "-.025em",
            color: "var(--color-neutral-700)",
          }}
        >
          {money(0, BASE_CURRENCY)}
        </span>
        <div
          style={{
            marginTop: "var(--space-3)",
            fontSize: 13.5,
            color: "var(--color-neutral-700)",
          }}
        >
          Nothing invested yet
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4,1fr)",
          borderTop: "2px solid var(--color-divider)",
          borderBottom: "2px solid var(--color-divider)",
        }}
      >
        {["Alpha", "Currency impact", "Volatility", "Max drawdown"].map((label, i) => (
          <div
            key={label}
            style={{
              padding: "var(--space-4)",
              borderLeft: i === 0 ? "none" : "2px solid var(--color-divider)",
            }}
          >
            <h6 style={{ margin: 0, color: "var(--color-neutral-700)" }}>{label}</h6>
            <div
              className="fig"
              style={{
                marginTop: "var(--space-2)",
                fontSize: 28,
                fontWeight: 800,
                lineHeight: 1,
                color: "var(--color-neutral-700)",
              }}
            >
              —
            </div>
            <div
              style={{
                marginTop: "var(--space-2)",
                fontSize: 12.5,
                color: "var(--color-neutral-700)",
              }}
            >
              Needs at least one trade
            </div>
          </div>
        ))}
      </div>

      <div
        style={{
          border: "2px solid var(--color-divider)",
          padding: "var(--space-8)",
          display: "grid",
          gridTemplateColumns: "minmax(0,1fr) 300px",
          gap: "var(--space-8)",
          alignItems: "center",
        }}
      >
        <div>
          <h2 style={{ margin: "0 0 var(--space-3)" }}>Record your first trade</h2>
          <p
            style={{
              fontSize: 14,
              color: "var(--color-neutral-800)",
              maxWidth: 460,
              margin: "0 0 var(--space-6)",
              textWrap: "pretty",
            }}
          >
            Positions, returns and risk grades are all derived from your trade history. Add a buy
            and the overview fills in immediately.
          </p>
          <div style={{ display: "flex", gap: "var(--space-2)" }}>
            <button className="btn btn-primary" type="button" onClick={onNewTrade}>
              + New trade
            </button>
            <button className="btn btn-secondary" type="button" onClick={onBrowseAssets}>
              Research an asset
            </button>
          </div>
        </div>
        <div
          style={{ display: "flex", alignItems: "flex-end", gap: "var(--space-2)", height: 120 }}
        >
          <span style={{ width: 22, height: "46%", background: "var(--color-neutral-300)" }} />
          <span style={{ width: 22, height: "78%", background: "var(--color-neutral-400)" }} />
          <span style={{ width: 22, height: "30%", background: "var(--color-neutral-300)" }} />
          <span style={{ width: 22, height: "100%", background: "var(--color-accent)" }} />
        </div>
      </div>

      <div style={{ fontSize: 12.5, color: "var(--color-neutral-700)" }}>
        {groupName ? (
          <>
            Group <strong>{groupName}</strong> ·{" "}
          </>
        ) : null}
        base currency {BASE_CURRENCY} · benchmark {BENCHMARK}
      </div>
    </>
  );
}
