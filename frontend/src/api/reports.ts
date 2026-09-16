// ---------------------------------------------------------------------------
// Reports resource module (/reports prefix).
// ---------------------------------------------------------------------------

import { apiClient } from "../lib/apiClient";
import type { PortfolioPerformanceReport, ValuationReport } from "../types";

/**
 * GET /reports/valuation/{symbol}/{target_currency}
 * Single-asset valuation in a target currency.
 * Errors to handle:
 *   - 404: asset not found or no trades
 *   - 503: FX rate service unavailable (forex_python can be flaky)
 */
export async function getValuation(
  symbol: string,
  targetCurrency: string,
): Promise<ValuationReport> {
  const { data } = await apiClient.get<ValuationReport>(
    `/reports/valuation/${encodeURIComponent(symbol)}/${encodeURIComponent(targetCurrency)}`,
  );
  return data;
}

export interface PortfolioPerformanceParams {
  base_currency?: string;
  benchmark_ticker?: string;
  lookback_period?: string;
  risk_free_rate?: number;
}

/**
 * GET /reports/portfolio-performance
 * Full portfolio performance report. SLOW — expect 10–60+ seconds.
 * Supports an AbortSignal so callers can cancel mid-flight.
 */
export async function getPortfolioPerformance(
  params: PortfolioPerformanceParams = {},
  signal?: AbortSignal,
): Promise<PortfolioPerformanceReport> {
  const { data } = await apiClient.get<PortfolioPerformanceReport>(
    "/reports/portfolio-performance",
    { params, signal },
  );
  return data;
}
