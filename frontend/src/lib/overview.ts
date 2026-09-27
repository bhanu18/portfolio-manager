// ---------------------------------------------------------------------------
// Overview page — pure view-model derivations.
//
// The Modernist design is a mono red-on-ground system, so gain/loss cannot be a
// green/red pair. The rules it encodes, and that these helpers enforce:
//   - gains stay in ink, losses take the accent;
//   - every figure carries an explicit + or −, so the read never depends on
//     colour;
//   - allocation and weight bars use the neutral ramp — red is reserved for
//     losses, the primary action, and the one poster statement.
// ---------------------------------------------------------------------------

import type {
  AssetTypeBreakdown,
  GradeValue,
  HoldingAnalysis,
  PortfolioPerformanceReport,
  Score,
  Trade,
} from "../types";
import { currencyPrefix } from "./format";

/** Ink for a gain, accent for a loss. Zero reads as a gain (neutral ink). */
export function returnColor(value: number | null | undefined): string {
  if (value == null) return "var(--color-neutral-700)";
  return value < 0 ? "var(--color-accent)" : "var(--color-text)";
}

/** Money with an explicit sign, e.g. "+$32,346.08" / "−$1,204.10". */
export function signedMoney(value: number | null | undefined, currency: string): string {
  if (value == null) return "—";
  const sign = value < 0 ? "−" : "+";
  return (
    sign +
    currencyPrefix(currency) +
    Math.abs(value).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  );
}

/** Percent with an explicit sign, e.g. "+25.18%" / "−4.02%". */
export function signedPct(value: number | null | undefined, digits = 2): string {
  if (value == null) return "—";
  const sign = value < 0 ? "−" : "+";
  return sign + Math.abs(value).toFixed(digits) + "%";
}

/** Unsigned money, for totals that are never negative (value, cost basis). */
export function money(value: number | null | undefined, currency: string): string {
  if (value == null) return "—";
  return (
    currencyPrefix(currency) +
    value.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  );
}

/** Compact money for dense rows, e.g. "$12.4k". */
export function plainNumber(value: number | null | undefined, digits = 2): string {
  if (value == null) return "—";
  return value.toFixed(digits);
}

// --- Grades ----------------------------------------------------------------

/**
 * Grade chip styling. Mono system: strong grades read as solid ink, weak
 * grades take the accent — the same "red means bad" rule as losses.
 */
export function gradeClass(grade: GradeValue | null | undefined): string {
  switch (grade) {
    case "A":
    case "B":
      return "";
    case "C":
      return "tag-neutral";
    case "D":
    case "F":
      return "tag-accent";
    default:
      return "tag-neutral";
  }
}

// --- KPI strip -------------------------------------------------------------

export interface Kpi {
  label: string;
  value: string;
  note: string;
  color: string;
}

/**
 * The four-up KPI strip under the headline figure.
 *
 * Risk metrics come from the portfolio score, which the backend does not
 * compute yet — when `portfolio_score` is absent these render as "—" with a
 * note, which is the design's own empty treatment.
 */
export function buildKpis(report: PortfolioPerformanceReport): Kpi[] {
  const s = report.portfolio_summary;
  const m: Score["metrics"] | undefined = report.portfolio_score?.metrics;
  const fx = s.currency_impact_summary;

  const alphaNote =
    s.benchmark_ticker != null
      ? `vs ${s.benchmark_ticker} at ${signedPct(s.benchmark_return)}`
      : "vs benchmark";

  return [
    {
      label: "Alpha",
      value: signedPct(s.alpha),
      note: alphaNote,
      color: returnColor(s.alpha),
    },
    {
      label: "Currency impact",
      value: signedPct(fx.total_fx_contribution_pct),
      note: `${signedMoney(fx.total_fx_gain_loss, report.base_currency)} from FX`,
      color: returnColor(fx.total_fx_contribution_pct),
    },
    {
      label: "Volatility",
      value: m?.volatility != null ? `${m.volatility.toFixed(1)}%` : "—",
      note: m?.volatility != null ? "Annualised, since inception" : "Needs the scoring run",
      color: "var(--color-text)",
    },
    {
      label: "Max drawdown",
      value: m?.max_drawdown != null ? signedPct(-Math.abs(m.max_drawdown), 1) : "—",
      note: m?.max_drawdown != null ? "Peak to trough" : "Needs the scoring run",
      color: m?.max_drawdown != null ? "var(--color-accent)" : "var(--color-text)",
    },
  ];
}

// --- Holdings --------------------------------------------------------------

export interface HoldingRow {
  key: string;
  ticker: string;
  name: string;
  position: string;
  value: string;
  weight: string;
  barWidth: string;
  barColor: string;
  totalRet: string;
  retColor: string;
  grade: string;
  gradeClass: string;
}

export function buildHoldingRows(
  holdings: (HoldingAnalysis & { score?: Score })[],
  baseCurrency: string,
): HoldingRow[] {
  const sorted = [...holdings].sort((a, b) => b.weight_pct - a.weight_pct);
  // Bars are scaled against the largest position, not against 100% — otherwise
  // a well-diversified portfolio renders as a column of stubs.
  const maxWeight = sorted.reduce((acc, h) => Math.max(acc, h.weight_pct), 0) || 1;

  return sorted.map((h) => ({
    key: h.ticker,
    ticker: h.ticker,
    name: h.asset_name,
    position: `${h.quantity.toLocaleString(undefined, { maximumFractionDigits: 6 })} @ ${money(
      h.current_price_original,
      h.original_currency,
    )}`,
    value: money(h.current_value_base, baseCurrency),
    weight: `${h.weight_pct.toFixed(1)}%`,
    barWidth: `${(h.weight_pct / maxWeight) * 100}%`,
    barColor: "var(--color-neutral-700)",
    totalRet: signedPct(h.total_return_pct),
    retColor: returnColor(h.total_return_pct),
    grade: h.score?.grade ?? "—",
    gradeClass: gradeClass(h.score?.grade),
  }));
}

// --- Allocation ------------------------------------------------------------

export interface AllocationRow {
  key: string;
  label: string;
  value: string;
  pct: string;
  width: string;
  color: string;
}

/** Neutral ramp — allocation never uses the accent. */
const ALLOCATION_RAMP = [
  "var(--color-neutral-900)",
  "var(--color-neutral-700)",
  "var(--color-neutral-500)",
  "var(--color-neutral-400)",
  "var(--color-neutral-300)",
  "var(--color-neutral-200)",
];

export function buildAllocation(
  byAssetType: Record<string, AssetTypeBreakdown>,
  baseCurrency: string,
): AllocationRow[] {
  return Object.entries(byAssetType)
    .sort(([, a], [, b]) => b.weight_pct - a.weight_pct)
    .map(([label, b], i) => ({
      key: label,
      label,
      value: money(b.value_base, baseCurrency),
      pct: `${b.weight_pct.toFixed(1)}%`,
      width: `${b.weight_pct}%`,
      color: ALLOCATION_RAMP[i % ALLOCATION_RAMP.length],
    }));
}

// --- Movers ----------------------------------------------------------------

export interface MoverRow {
  key: string;
  ticker: string;
  value: string;
  color: string;
  /** Offset from the left edge of the track, as a percentage string. */
  left: string;
  width: string;
}

/**
 * Top and bottom performers on a shared centre line: the track's midpoint is
 * zero, bars grow right for a gain and left for a loss, scaled against the
 * largest absolute move so the extremes touch the edges.
 */
export function buildMovers(report: PortfolioPerformanceReport, limit = 6): MoverRow[] {
  const combined = [...report.top_performers, ...report.bottom_performers];

  // top_ and bottom_performers can overlap on a small portfolio.
  const seen = new Set<string>();
  const unique = combined.filter((m) => {
    if (seen.has(m.ticker)) return false;
    seen.add(m.ticker);
    return true;
  });

  const ranked = unique
    .sort((a, b) => Math.abs(b.total_return_pct) - Math.abs(a.total_return_pct))
    .slice(0, limit)
    .sort((a, b) => b.total_return_pct - a.total_return_pct);

  const maxAbs = ranked.reduce((acc, m) => Math.max(acc, Math.abs(m.total_return_pct)), 0) || 1;

  return ranked.map((m) => {
    const halfWidth = (Math.abs(m.total_return_pct) / maxAbs) * 50;
    const isLoss = m.total_return_pct < 0;
    return {
      key: m.ticker,
      ticker: m.ticker,
      value: signedPct(m.total_return_pct, 1),
      color: returnColor(m.total_return_pct),
      left: `${isLoss ? 50 - halfWidth : 50}%`,
      width: `${halfWidth}%`,
    };
  });
}

// --- Recent activity -------------------------------------------------------

export interface ActivityRow {
  key: number;
  typeLabel: string;
  tagClass: string;
  ticker: string;
  detail: string;
  date: string;
}

export function buildActivity(trades: Trade[], limit = 4): ActivityRow[] {
  return [...trades]
    .sort((a, b) => new Date(b.trade_date).getTime() - new Date(a.trade_date).getTime())
    .slice(0, limit)
    .map((t) => ({
      key: t.id,
      typeLabel: t.trade_type === "sell" ? "SELL" : "BUY",
      // Mono system: a buy is solid ink, a sell is the outlined counterpart.
      tagClass: t.trade_type === "sell" ? "tag-outline" : "",
      ticker: t.symbol ?? `#${t.asset_id}`,
      detail: `${t.quantity.toLocaleString(undefined, { maximumFractionDigits: 6 })} @ ${money(
        t.price_per_unit,
        t.currency,
      )}`,
      date: new Date(t.trade_date).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      }),
    }));
}
