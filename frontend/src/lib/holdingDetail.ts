// ---------------------------------------------------------------------------
// Asset detail view — pure view-model derivations.
//
// Same Modernist colour rules as the overview (see ./overview.ts): gains stay
// in ink, losses take the accent, every figure carries an explicit sign, and
// the neutral ramp carries anything that isn't a gain/loss read.
// ---------------------------------------------------------------------------

import type { Asset, HoldingAnalysis, Score, TradeResponse } from "../types";
import { money, returnColor, signedMoney, signedPct } from "./overview";

// --- Sidebar ---------------------------------------------------------------

export interface SidebarRow {
  key: string;
  ticker: string;
  name: string;
  value: string;
  ret: string;
  retColor: string;
  /** Left rule: accent marks the selected row, transparent otherwise. */
  bar: string;
  bg: string;
}

export function buildSidebarRows(
  holdings: HoldingAnalysis[],
  baseCurrency: string,
  selected: string | null,
  search: string,
): SidebarRow[] {
  const q = search.trim().toLowerCase();
  return holdings
    .filter(
      (h) =>
        q.length === 0 ||
        h.ticker.toLowerCase().includes(q) ||
        h.asset_name.toLowerCase().includes(q),
    )
    .sort((a, b) => b.weight_pct - a.weight_pct)
    .map((h) => {
      const isSelected = h.ticker === selected;
      return {
        key: h.ticker,
        ticker: h.ticker,
        name: h.asset_name,
        value: money(h.current_value_base, baseCurrency),
        ret: signedPct(h.total_return_pct, 1),
        retColor: returnColor(h.total_return_pct),
        bar: isSelected ? "var(--color-accent)" : "transparent",
        bg: isSelected ? "var(--color-neutral-100)" : "transparent",
      };
    });
}

// --- Stat strip ------------------------------------------------------------

export interface DetailStat {
  label: string;
  value: string;
  note: string;
  color: string;
}

/**
 * The four-up strip. Labels are fixed by the design; the notes carry the
 * "not held" wording from state 2d when there is no position.
 */
export function buildDetailStats(
  holding: HoldingAnalysis | null,
  asset: Asset | null,
  baseCurrency: string,
): DetailStat[] {
  const ink = "var(--color-text)";
  const muted = "var(--color-neutral-700)";

  if (!holding) {
    return [
      {
        label: "Market value",
        value: money(0, baseCurrency),
        note: "You hold no units of this asset",
        color: muted,
      },
      {
        label: "Last price",
        value: asset?.current_price != null ? money(asset.current_price, baseCurrency) : "—",
        note: asset?.market ? `Quoted on ${asset.market}` : "No price on file",
        color: ink,
      },
      { label: "Position", value: "—", note: "No trades recorded", color: muted },
      { label: "Average cost", value: "—", note: "Set by your first buy", color: muted },
    ];
  }

  const avgCost = holding.quantity !== 0 ? holding.cost_basis_original / holding.quantity : null;
  const priceVsCost =
    avgCost != null && avgCost !== 0
      ? ((holding.current_price_original - avgCost) / avgCost) * 100
      : null;

  return [
    {
      label: "Market value",
      value: money(holding.current_value_base, baseCurrency),
      note: `${signedMoney(holding.unrealized_gain_loss_base, baseCurrency)} unrealized`,
      color: ink,
    },
    {
      label: "Last price",
      value: money(holding.current_price_original, holding.original_currency),
      note: `Priced in ${holding.original_currency}`,
      color: ink,
    },
    {
      label: "Position",
      value: holding.quantity.toLocaleString(undefined, { maximumFractionDigits: 6 }),
      note: `Held ${holding.holding_period_days} days`,
      color: ink,
    },
    {
      label: "Average cost",
      value: avgCost != null ? money(avgCost, holding.original_currency) : "—",
      note: priceVsCost != null ? `${signedPct(priceVsCost, 1)} vs last price` : "—",
      color: priceVsCost != null ? returnColor(priceVsCost) : ink,
    },
  ];
}

// --- Risk metrics ----------------------------------------------------------

export interface MetricRow {
  key: string;
  label: string;
  value: string;
  read: string;
  color: string;
}

/**
 * The five metric rows under the risk grade, each with a plain-language read —
 * the design pairs every figure with a sentence rather than leaving bare
 * statistics on the page.
 */
export function buildMetricRows(score: Score | null | undefined): MetricRow[] {
  const m = score?.metrics;
  const ink = "var(--color-text)";
  const dash = (v: string | null) => v ?? "—";

  return [
    {
      key: "cagr",
      label: "CAGR",
      value: m?.cagr != null ? signedPct(m.cagr, 1) : "—",
      read:
        m?.cagr != null
          ? "Annualised growth since the first buy."
          : "Needs enough price history to compute.",
      color: m?.cagr != null ? returnColor(m.cagr) : ink,
    },
    {
      key: "volatility",
      label: "Volatility",
      value: m?.volatility != null ? `${m.volatility.toFixed(1)}%` : "—",
      read:
        m?.volatility != null
          ? "Annualised swing in daily returns."
          : "Needs enough price history to compute.",
      color: ink,
    },
    {
      key: "sharpe",
      label: "Sharpe",
      value: dash(m?.sharpe != null ? m.sharpe.toFixed(2) : null),
      read:
        m?.sharpe != null
          ? m.sharpe >= 1
            ? "Solid return for the risk taken."
            : "Thin return for the risk taken."
          : "Needs enough price history to compute.",
      color: m?.sharpe != null && m.sharpe < 0 ? "var(--color-accent)" : ink,
    },
    {
      key: "max_drawdown",
      label: "Max drawdown",
      value: m?.max_drawdown != null ? signedPct(-Math.abs(m.max_drawdown), 1) : "—",
      read:
        m?.max_drawdown != null
          ? "Worst peak-to-trough fall in the window."
          : "Needs enough price history to compute.",
      color: m?.max_drawdown != null ? "var(--color-accent)" : ink,
    },
    {
      key: "beta",
      label: "Beta",
      value: dash(m?.beta != null ? m.beta.toFixed(2) : null),
      read:
        m?.beta != null
          ? m.beta > 1
            ? "Moves more than the benchmark."
            : "Moves less than the benchmark."
          : "Needs a benchmark overlap to compute.",
      color: ink,
    },
  ];
}

// --- Return attribution ----------------------------------------------------

export interface AttributionRow {
  key: string;
  label: string;
  value: string;
  color: string;
  width: string;
}

/** Splits the holding's return into its local-price and currency components. */
export function buildAttribution(holding: HoldingAnalysis): AttributionRow[] {
  const parts = [
    { key: "local", label: "Local price return", pct: holding.local_return_pct },
    { key: "fx", label: "Currency (FX)", pct: holding.fx_return_pct },
    { key: "total", label: "Total return", pct: holding.total_return_pct },
  ];
  const maxAbs = parts.reduce((acc, p) => Math.max(acc, Math.abs(p.pct)), 0) || 1;

  return parts.map((p) => ({
    key: p.key,
    label: p.label,
    value: signedPct(p.pct),
    color: returnColor(p.pct),
    width: `${(Math.abs(p.pct) / maxAbs) * 100}%`,
  }));
}

/** The sentence under the attribution bars. */
export function attributionNote(holding: HoldingAnalysis, baseCurrency: string): string {
  const years = holding.holding_period_days / 365;
  const span =
    years >= 1 ? `over ${years.toFixed(1)} years` : `over ${holding.holding_period_days} days`;
  const fx =
    holding.original_currency === baseCurrency
      ? `${holding.original_currency}-priced, so no currency effect.`
      : `Priced in ${holding.original_currency}, so FX moves the ${baseCurrency} result.`;
  return `${fx} Annualised ${signedPct(holding.annualized_return)} ${span}.`;
}

// --- Trades ----------------------------------------------------------------

export interface TradeRow {
  key: number;
  typeLabel: string;
  tagClass: string;
  date: string;
  /** Row bookkeeping for the date cell's tooltip: when the record was entered,
   *  and when it was last edited if that differs. */
  recorded: string;
  /** True when the row has been edited since it was entered — the table marks
   *  those so an edited trade isn't silently identical to an untouched one. */
  edited: boolean;
  qty: string;
  price: string;
  cost: string;
  raw: TradeResponse;
}

/** Same day-level granularity as the rest of the table. */
function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** Trades are edited rarely, so a minute of slack absorbs the gap between the
 *  INSERT and the UPDATE in the same request without calling the row edited. */
function wasEdited(createdAt: string, updatedAt: string): boolean {
  const created = new Date(createdAt).getTime();
  const updated = new Date(updatedAt).getTime();
  if (Number.isNaN(created) || Number.isNaN(updated)) return false;
  return updated - created > 60_000;
}

export function buildTradeRows(trades: TradeResponse[]): TradeRow[] {
  return [...trades]
    .sort((a, b) => new Date(b.trade_date).getTime() - new Date(a.trade_date).getTime())
    .map((t) => {
      const currency = t.currency;
      const edited = wasEdited(t.created_at, t.updated_at);
      return {
        key: t.id,
        typeLabel: t.trade_type === "sell" ? "SELL" : "BUY",
        tagClass: t.trade_type === "sell" ? "tag-outline" : "",
        date: shortDate(t.trade_date),
        recorded: edited
          ? `Recorded ${shortDate(t.created_at)} · edited ${shortDate(t.updated_at)}`
          : `Recorded ${shortDate(t.created_at)}`,
        edited,
        qty: t.quantity.toLocaleString(undefined, { maximumFractionDigits: 6 }),
        price: money(t.price_per_unit, currency),
        cost: money(t.quantity * t.price_per_unit, currency),
        raw: t,
      };
    });
}

/** "4 · avg cost $94.75" — the meta line beside the Trades heading. */
export function tradesMeta(
  trades: TradeResponse[],
  holding: HoldingAnalysis | null,
  fallbackCurrency: string,
): string {
  if (trades.length === 0) return "No trades yet";
  // A row's own currency when there is one; the holding's only covers the
  // no-trades case, which returns early above anyway.
  const currency = trades[0]?.currency ?? fallbackCurrency;
  const avgCost =
    holding && holding.quantity !== 0 ? holding.cost_basis_original / holding.quantity : null;
  return avgCost != null
    ? `${trades.length} · avg cost ${money(avgCost, currency)}`
    : `${trades.length} trade${trades.length === 1 ? "" : "s"}`;
}

/** The footer under the trades table: net position, days held, invested. */
export function tradesFooter(
  holding: HoldingAnalysis | null,
  baseCurrency: string,
): { left: string; right: string } | null {
  if (!holding) return null;
  return {
    left: `Net position ${holding.quantity.toLocaleString(undefined, {
      maximumFractionDigits: 6,
    })} units · held ${holding.holding_period_days} days`,
    right: `${money(holding.cost_basis_base, baseCurrency)} invested`,
  };
}
