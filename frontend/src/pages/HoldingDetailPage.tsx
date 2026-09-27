// ---------------------------------------------------------------------------
// Asset detail — Modernist split panel.
//
// Implements option 1d of docs/frontend/Portfolio Dashboard (Modernist).dc.html
// ("Asset view · split panel, keeps your list + detail").
//
// States 2c (scoring pending) and 2d (asset exists, not held) are drawn on the
// 1e chrome in the design; their treatments are adapted into this layout's
// detail pane.
//
// Routes: /holdings and /holdings/:symbol. These replace the retired
// /portfolio split panel, which now redirects here.
//
// The app's modals render inline rather than through a portal, so they are
// mounted OUTSIDE the .mod wrapper: inside it they would inherit this page's
// scoped token overrides and lose their own styling.
// ---------------------------------------------------------------------------

import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as assetsApi from "../api/assets";
import * as tradesApi from "../api/trades";
import { getPortfolioPerformance } from "../api/reports";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { parseApiError } from "../lib/errors";
import {
  attributionNote,
  buildAttribution,
  buildDetailStats,
  buildMetricRows,
  buildSidebarRows,
  buildTradeRows,
  tradesFooter,
  tradesMeta,
} from "../lib/holdingDetail";
import type { Asset, PortfolioPerformanceReport, TradeResponse } from "../types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { TradeFormModal, type TradeFormResult } from "../components/TradeFormModal";
import { AssetFormModal, type AssetFormValues } from "../components/AssetFormModal";
import { ModernistNav } from "../components/ModernistNav";
import "../styles/modernist.css";

const BASE_CURRENCY = "USD";
const BENCHMARK = "SPY";

export function HoldingDetailPage() {
  const { symbol: routeSymbol } = useParams<{ symbol: string }>();
  const queryClient = useQueryClient();
  const toast = useToast();
  const { user, refreshUser } = useAuth();
  const groups = useMemo(() => user?.groups ?? [], [user]);

  const [search, setSearch] = useState("");

  // --- Performance report (slow; cached so switching assets doesn't re-run) --
  const reportQuery = useQuery<PortfolioPerformanceReport>({
    queryKey: ["performance", BASE_CURRENCY, BENCHMARK],
    queryFn: ({ signal }) =>
      getPortfolioPerformance(
        { base_currency: BASE_CURRENCY, benchmark_ticker: BENCHMARK },
        signal,
      ),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const report = reportQuery.data ?? null;
  const holdings = useMemo(() => report?.holdings ?? [], [report]);

  // Default to the largest position when no symbol is in the URL.
  const selectedSymbol = useMemo(() => {
    if (routeSymbol) return routeSymbol.toUpperCase();
    const first = [...holdings].sort((a, b) => b.weight_pct - a.weight_pct)[0];
    return first?.ticker ?? null;
  }, [routeSymbol, holdings]);

  const holding = useMemo(
    () => holdings.find((h) => h.ticker === selectedSymbol) ?? null,
    [holdings, selectedSymbol],
  );

  // --- Asset record (exchange, type, last price) ----------------------------
  const assetQuery = useQuery<Asset | null>({
    queryKey: ["asset", "symbol", selectedSymbol],
    enabled: Boolean(selectedSymbol),
    queryFn: async () => {
      const result = await assetsApi.getAssetBySymbol(selectedSymbol!);
      return "error" in result ? null : result;
    },
    retry: false,
  });
  const asset = assetQuery.data ?? null;

  // --- Trades for this symbol ----------------------------------------------
  const tradesQuery = useQuery<TradeResponse[]>({
    queryKey: ["trades", "symbol", selectedSymbol],
    enabled: Boolean(selectedSymbol),
    queryFn: () => tradesApi.listTradesBySymbol(selectedSymbol!),
    retry: false,
  });
  const trades = useMemo(() => tradesQuery.data ?? [], [tradesQuery.data]);

  // --- Mutations ------------------------------------------------------------
  const [tradeFormOpen, setTradeFormOpen] = useState(false);
  const [editingTrade, setEditingTrade] = useState<TradeResponse | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<TradeResponse | null>(null);
  const [assetFormOpen, setAssetFormOpen] = useState(false);

  const invalidateAll = () => {
    void queryClient.invalidateQueries({ queryKey: ["trades"] });
    void queryClient.invalidateQueries({ queryKey: ["assets"] });
    void queryClient.invalidateQueries({ queryKey: ["performance"] });
  };

  /** 403 means the role/membership changed — re-sync the profile. */
  const handleTradeActionError = (err: unknown) => {
    const parsed = parseApiError(err);
    if (parsed.isForbidden) {
      toast.error("You don't have permission to modify this trade.");
      void refreshUser();
    } else {
      toast.error(parsed.message);
    }
  };

  const createMutation = useMutation({
    mutationFn: (values: TradeFormResult["values"]) =>
      tradesApi.createTrade(selectedSymbol!, values),
    onSuccess: () => {
      toast.success("Trade added.");
      setTradeFormOpen(false);
      invalidateAll();
    },
    onError: handleTradeActionError,
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: number; values: TradeFormResult["values"] }) =>
      tradesApi.updateTrade(id, values),
    onSuccess: () => {
      toast.success("Trade updated.");
      setTradeFormOpen(false);
      setEditingTrade(null);
      invalidateAll();
    },
    onError: handleTradeActionError,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => tradesApi.deleteTrade(id),
    onSuccess: () => {
      toast.success("Trade deleted.");
      setDeleteTarget(null);
      invalidateAll();
    },
    onError: (err) => {
      handleTradeActionError(err);
      setDeleteTarget(null);
    },
  });

  const updateAssetMutation = useMutation({
    mutationFn: (values: AssetFormValues) => assetsApi.updateAsset(asset!.id, values),
    onSuccess: () => {
      toast.success("Asset updated.");
      setAssetFormOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["asset", "symbol", selectedSymbol] });
      void queryClient.invalidateQueries({ queryKey: ["assets"] });
    },
    onError: (err) => toast.error(parseApiError(err).message),
  });

  // --- Derived view models --------------------------------------------------
  const sidebarRows = useMemo(
    () => buildSidebarRows(holdings, BASE_CURRENCY, selectedSymbol, search),
    [holdings, selectedSymbol, search],
  );
  const stats = useMemo(() => buildDetailStats(holding, asset, BASE_CURRENCY), [holding, asset]);
  const metricRows = useMemo(() => buildMetricRows(holding?.score), [holding]);
  const tradeRows = useMemo(() => buildTradeRows(trades), [trades]);
  const footer = useMemo(() => tradesFooter(holding, BASE_CURRENCY), [holding]);

  const loading = reportQuery.isPending;
  const score = holding?.score;

  return (
    <>
      <div className="mod" style={{ minHeight: "100%", display: "flex", flexDirection: "column" }}>
        <ModernistNav />

        <div
          style={{
            flex: 1,
            minHeight: 0,
            display: "grid",
            gridTemplateColumns: "262px minmax(0,1fr)",
          }}
        >
          {/* --- Sidebar ------------------------------------------------------ */}
          <aside
            style={{
              borderRight: "2px solid var(--color-divider)",
              display: "flex",
              flexDirection: "column",
            }}
          >
            <div
              style={{ padding: "var(--space-4)", borderBottom: "2px solid var(--color-divider)" }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  justifyContent: "space-between",
                  marginBottom: "var(--space-3)",
                }}
              >
                <h5 style={{ margin: 0 }}>
                  <Link to="/overview" style={{ textDecoration: "none" }}>
                    HOLDINGS
                  </Link>
                </h5>
                <span className="fig" style={{ fontSize: 11, color: "var(--color-neutral-700)" }}>
                  {loading ? "—" : holdings.length}
                </span>
              </div>
              <input
                className="input"
                type="text"
                placeholder="Search symbol…"
                aria-label="Search holdings"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{ width: "100%" }}
              />
            </div>

            {loading
              ? Array.from({ length: 8 }, (_, i) => (
                  <div
                    key={`ssk-${i}`}
                    style={{
                      padding: "var(--space-2) var(--space-4)",
                      borderBottom: "1px solid var(--color-divider)",
                      display: "flex",
                      flexDirection: "column",
                      gap: 4,
                    }}
                  >
                    <span className="sk" style={{ width: 54, height: 12 }} />
                    <span className="sk sk-faint" style={{ width: 110, height: 11 }} />
                  </div>
                ))
              : sidebarRows.map((a) => (
                  <Link
                    key={a.key}
                    to={`/holdings/${a.ticker}`}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "var(--space-2)",
                      padding: "var(--space-2) var(--space-4)",
                      borderBottom: "1px solid var(--color-divider)",
                      borderLeft: `3px solid ${a.bar}`,
                      background: a.bg,
                      textDecoration: "none",
                    }}
                    aria-current={a.ticker === selectedSymbol ? "page" : undefined}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="fig" style={{ fontWeight: 800, fontSize: 12.5 }}>
                        {a.ticker}
                      </div>
                      <div
                        style={{
                          fontSize: 11.5,
                          color: "var(--color-neutral-700)",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {a.name}
                      </div>
                    </div>
                    <div style={{ textAlign: "right", flex: "none" }}>
                      <div className="fig" style={{ fontSize: 12 }}>
                        {a.value}
                      </div>
                      <div
                        className="fig"
                        style={{ fontSize: 11, fontWeight: 800, color: a.retColor }}
                      >
                        {a.ret}
                      </div>
                    </div>
                  </Link>
                ))}

            {!loading && sidebarRows.length === 0 && (
              <div
                style={{
                  padding: "var(--space-4)",
                  fontSize: 12.5,
                  color: "var(--color-neutral-700)",
                }}
              >
                {search ? `Nothing matches “${search}”.` : "No holdings yet."}
              </div>
            )}
          </aside>

          {/* --- Detail pane --------------------------------------------------- */}
          <div>
            <div
              style={{
                padding: "var(--space-6)",
                borderBottom: "2px solid var(--color-divider)",
                display: "flex",
                alignItems: "flex-start",
                justifyContent: "space-between",
                gap: "var(--space-6)",
              }}
            >
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
                  <span
                    className="fig"
                    style={{
                      fontSize: 34,
                      fontWeight: 800,
                      lineHeight: 1,
                      letterSpacing: "-.02em",
                    }}
                  >
                    {selectedSymbol ?? "—"}
                  </span>
                  {(asset?.type || holding?.asset_type) && (
                    <span className="tag tag-neutral">
                      {(asset?.type ?? holding?.asset_type ?? "").toUpperCase()}
                    </span>
                  )}
                  {holding?.is_long_term && <span className="tag tag-outline">LONG TERM</span>}
                  {!loading && selectedSymbol && !holding && (
                    <span className="tag tag-outline">NOT HELD</span>
                  )}
                </div>
                <div
                  style={{
                    marginTop: "var(--space-2)",
                    fontSize: 13,
                    color: "var(--color-neutral-700)",
                  }}
                >
                  {asset || holding ? (
                    [
                      asset?.name ?? holding?.asset_name,
                      asset?.market,
                      `priced in ${holding?.original_currency ?? BASE_CURRENCY}`,
                    ]
                      .filter(Boolean)
                      .join(" · ")
                  ) : (
                    <span className="sk" style={{ width: 280, height: 12 }} />
                  )}
                </div>
              </div>
              <div style={{ display: "flex", gap: "var(--space-2)" }}>
                <button
                  className="btn btn-secondary"
                  type="button"
                  disabled={!asset}
                  onClick={() => setAssetFormOpen(true)}
                >
                  Edit asset
                </button>
                <button
                  className="btn btn-primary"
                  type="button"
                  disabled={!selectedSymbol}
                  onClick={() => {
                    setEditingTrade(null);
                    setTradeFormOpen(true);
                  }}
                >
                  + New trade
                </button>
              </div>
            </div>

            <div
              style={{
                padding: "var(--space-6)",
                display: "flex",
                flexDirection: "column",
                gap: "var(--space-6)",
              }}
            >
              {/* --- Stat strip ---------------------------------------------- */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(4,1fr)",
                  borderTop: "2px solid var(--color-divider)",
                  borderBottom: "2px solid var(--color-divider)",
                }}
              >
                {stats.map((s, i) => (
                  <div
                    key={s.label}
                    style={{
                      padding: "var(--space-3) var(--space-4)",
                      borderLeft: i === 0 ? "none" : "2px solid var(--color-divider)",
                    }}
                  >
                    <h6 style={{ margin: 0, color: "var(--color-neutral-700)" }}>{s.label}</h6>
                    {loading ? (
                      <>
                        <span
                          className="sk"
                          style={{ marginTop: "var(--space-2)", width: 110, height: 26 }}
                        />
                        <span
                          className="sk sk-faint"
                          style={{ marginTop: "var(--space-2)", width: 140, height: 11 }}
                        />
                      </>
                    ) : (
                      <>
                        <div
                          className="fig"
                          style={{
                            marginTop: "var(--space-2)",
                            fontSize: 26,
                            fontWeight: 800,
                            lineHeight: 1,
                            color: s.color,
                          }}
                        >
                          {s.value}
                        </div>
                        <div
                          className="fig"
                          style={{
                            marginTop: "var(--space-2)",
                            fontSize: 12,
                            color: "var(--color-neutral-700)",
                          }}
                        >
                          {s.note}
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "minmax(0,1fr) 340px",
                  gap: "var(--space-6)",
                  alignItems: "start",
                }}
              >
                {/* --- Trades ------------------------------------------------ */}
                <div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "baseline",
                      justifyContent: "space-between",
                      marginBottom: "var(--space-2)",
                    }}
                  >
                    <h4 style={{ margin: 0 }}>Trades</h4>
                    <span
                      className="fig"
                      style={{ fontSize: 11.5, color: "var(--color-neutral-700)" }}
                    >
                      {tradesMeta(trades, holding, holding?.original_currency ?? BASE_CURRENCY)}
                    </span>
                  </div>

                  {tradeRows.length === 0 && !tradesQuery.isPending ? (
                    <div
                      style={{
                        border: "2px solid var(--color-divider)",
                        padding: "var(--space-6)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: "var(--space-4)",
                      }}
                    >
                      <span style={{ fontSize: 13.5 }}>No trades for {selectedSymbol} yet</span>
                      <button
                        className="btn btn-primary"
                        type="button"
                        disabled={!selectedSymbol}
                        onClick={() => {
                          setEditingTrade(null);
                          setTradeFormOpen(true);
                        }}
                      >
                        + New trade
                      </button>
                    </div>
                  ) : (
                    <>
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Type</th>
                            <th>Date</th>
                            <th style={{ textAlign: "right" }}>Qty</th>
                            <th style={{ textAlign: "right" }}>Price</th>
                            <th style={{ textAlign: "right" }}>Cost</th>
                            <th />
                          </tr>
                        </thead>
                        <tbody>
                          {tradeRows.map((t) => (
                            <tr key={t.key}>
                              <td>
                                <span className={`tag ${t.tagClass}`.trim()}>{t.typeLabel}</span>
                              </td>
                              <td
                                className="fig"
                                style={{ whiteSpace: "nowrap" }}
                                title={t.recorded}
                              >
                                {t.date}
                                {t.edited && (
                                  <span
                                    aria-label="Edited since it was recorded"
                                    style={{
                                      marginLeft: "var(--space-1)",
                                      color: "var(--color-neutral-500)",
                                    }}
                                  >
                                    *
                                  </span>
                                )}
                              </td>
                              <td className="fig" style={{ textAlign: "right" }}>
                                {t.qty}
                              </td>
                              <td className="fig" style={{ textAlign: "right" }}>
                                {t.price}
                              </td>
                              <td className="fig" style={{ textAlign: "right" }}>
                                {t.cost}
                              </td>
                              <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                                <button
                                  className="btn btn-ghost"
                                  type="button"
                                  onClick={() => {
                                    setEditingTrade(t.raw);
                                    setTradeFormOpen(true);
                                  }}
                                >
                                  Edit
                                </button>
                                <button
                                  className="btn btn-ghost"
                                  type="button"
                                  onClick={() => setDeleteTarget(t.raw)}
                                >
                                  Delete
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {footer && (
                        <div
                          className="fig"
                          style={{
                            padding: "var(--space-2)",
                            fontSize: 12,
                            color: "var(--color-neutral-700)",
                            display: "flex",
                            justifyContent: "space-between",
                          }}
                        >
                          <span>{footer.left}</span>
                          <span>{footer.right}</span>
                        </div>
                      )}
                    </>
                  )}
                </div>

                {/* --- Risk + attribution rail -------------------------------- */}
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
                  <div
                    style={{ border: "2px solid var(--color-divider)", padding: "var(--space-4)" }}
                  >
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "var(--space-4)",
                        paddingBottom: "var(--space-3)",
                        borderBottom: "2px solid var(--color-divider)",
                      }}
                    >
                      {score?.grade ? (
                        <>
                          <div
                            className="fig"
                            style={{ fontSize: 40, fontWeight: 800, lineHeight: 0.9 }}
                          >
                            {score.grade}
                          </div>
                          <div>
                            <div style={{ fontWeight: 800, fontSize: 14 }}>
                              Risk score{" "}
                              <span className="fig">
                                {score.composite_score != null
                                  ? `${Math.round(score.composite_score)} / 100`
                                  : "—"}
                              </span>
                            </div>
                            <div
                              className="fig"
                              style={{ fontSize: 11.5, color: "var(--color-neutral-700)" }}
                            >
                              {score.sample_days} trading days
                            </div>
                          </div>
                        </>
                      ) : holding || loading ? (
                        // State 2c: there is a position, the scoring run hasn't landed.
                        <>
                          <span className="sk" style={{ width: 40, height: 40 }} />
                          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                            <span style={{ fontWeight: 800, fontSize: 14 }}>
                              Scoring this holding
                            </span>
                            <span style={{ fontSize: 11.5, color: "var(--color-neutral-700)" }}>
                              Risk metrics arrive with the scoring run.
                            </span>
                          </div>
                        </>
                      ) : (
                        // State 2d: no position, so there is nothing to score.
                        <>
                          <div
                            className="fig"
                            style={{
                              fontSize: 40,
                              fontWeight: 800,
                              lineHeight: 0.9,
                              color: "var(--color-neutral-400)",
                            }}
                          >
                            —
                          </div>
                          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                            <span style={{ fontWeight: 800, fontSize: 14 }}>No risk score</span>
                            <span style={{ fontSize: 11.5, color: "var(--color-neutral-700)" }}>
                              Scoring starts once you hold a position.
                            </span>
                          </div>
                        </>
                      )}
                    </div>

                    {metricRows.map((m) => (
                      <div
                        key={m.key}
                        style={{
                          padding: "var(--space-2) 0",
                          borderBottom: "1px solid var(--color-divider)",
                        }}
                      >
                        <div
                          style={{ display: "flex", alignItems: "baseline", gap: "var(--space-2)" }}
                        >
                          <span style={{ flex: 1, fontSize: 12.5, fontWeight: 600 }}>
                            {m.label}
                          </span>
                          <span
                            className="fig"
                            style={{ fontSize: 13, fontWeight: 800, color: m.color }}
                          >
                            {m.value}
                          </span>
                        </div>
                        <div
                          style={{
                            marginTop: 2,
                            fontSize: 11.5,
                            color: "var(--color-neutral-700)",
                            textWrap: "pretty",
                          }}
                        >
                          {m.read}
                        </div>
                      </div>
                    ))}
                  </div>

                  {holding && (
                    <div>
                      <h4 style={{ margin: "0 0 var(--space-3)" }}>Where the return came from</h4>
                      {buildAttribution(holding).map((a) => (
                        <div
                          key={a.key}
                          style={{
                            padding: "var(--space-2) 0",
                            borderBottom: "1px solid var(--color-divider)",
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              alignItems: "baseline",
                              gap: "var(--space-2)",
                              marginBottom: 5,
                            }}
                          >
                            <span style={{ flex: 1, fontSize: 12.5 }}>{a.label}</span>
                            <span
                              className="fig"
                              style={{ fontSize: 12.5, fontWeight: 800, color: a.color }}
                            >
                              {a.value}
                            </span>
                          </div>
                          <div style={{ height: 5, background: "var(--color-neutral-200)" }}>
                            <div style={{ height: 5, background: a.color, width: a.width }} />
                          </div>
                        </div>
                      ))}
                      <div
                        className="fig"
                        style={{
                          marginTop: "var(--space-2)",
                          fontSize: 11.5,
                          color: "var(--color-neutral-700)",
                        }}
                      >
                        {attributionNote(holding, BASE_CURRENCY)}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Modals live outside .mod so they keep the app's own styling. */}
      {tradeFormOpen && (
        <TradeFormModal
          open
          trade={
            editingTrade
              ? {
                  id: editingTrade.id,
                  asset_id: 0,
                  symbol: editingTrade.symbol,
                  trade_type: editingTrade.trade_type,
                  trade_date: editingTrade.trade_date,
                  quantity: editingTrade.quantity,
                  price_per_unit: editingTrade.price_per_unit,
                  currency: editingTrade.currency,
                  group_id: editingTrade.group_id ?? 0,
                  created_at: editingTrade.created_at,
                  updated_at: editingTrade.updated_at,
                }
              : null
          }
          groups={groups}
          defaultGroupId={groups[0]?.id ?? null}
          knownSymbol={selectedSymbol}
          busy={createMutation.isPending || updateMutation.isPending}
          onCancel={() => {
            setTradeFormOpen(false);
            setEditingTrade(null);
          }}
          onSubmit={(result) => {
            if (editingTrade) {
              updateMutation.mutate({ id: editingTrade.id, values: result.values });
            } else {
              createMutation.mutate(result.values);
            }
          }}
        />
      )}

      {assetFormOpen && asset && (
        <AssetFormModal
          open
          asset={asset}
          busy={updateAssetMutation.isPending}
          onCancel={() => setAssetFormOpen(false)}
          onSubmit={(values) => updateAssetMutation.mutate(values)}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete trade"
        message={
          deleteTarget ? `Delete this ${deleteTarget.trade_type} trade? This cannot be undone.` : ""
        }
        confirmLabel="Delete"
        busy={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
        onCancel={() => setDeleteTarget(null)}
      />
    </>
  );
}
