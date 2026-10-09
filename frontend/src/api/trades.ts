import { getAssetsByIds } from "./assets";
// ---------------------------------------------------------------------------
// Trades resource module (/trades prefix). All endpoints require auth.
// ---------------------------------------------------------------------------

import { apiClient } from "../lib/apiClient";
import type {
  RawTrade,
  Trade,
  TradeCreatePayload,
  TradeResponse,
  TradeUpdatePayload,
} from "../types";

/**
 * The backend may embed the related asset on a trade (nested object) or expose
 * its symbol directly rather than a bare `asset_id`. Collapse the variants so
 * the UI always has a usable `asset_id` and, when available, an inline symbol.
 */
function normalizeTrade(raw: RawTrade): Trade {
  const nested = raw.asset ?? null;
  const assetId = raw.asset_id ?? raw.assetId ?? nested?.id ?? 0;

  // The backend returns the ticker as "asset_name" (confirmed from live response).
  // Also accept the other variants for robustness.
  const symbol = raw.symbol ?? raw.asset_symbol ?? raw.asset_name ?? nested?.symbol ?? undefined;

  return {
    id: raw.id,
    asset_id: assetId,
    symbol,
    trade_type: raw.trade_type,
    trade_date: raw.trade_date,
    quantity: raw.quantity,
    price_per_unit: raw.price_per_unit,
    currency: raw.currency,
    group_id: raw.group_id ?? 0,
    // Every /trades endpoint returns these now. The fallback matches how the
    // migration backfilled pre-existing rows, so a payload from an older
    // backend still sorts sensibly instead of showing "Invalid Date".
    created_at: raw.created_at ?? raw.trade_date,
    updated_at: raw.updated_at ?? raw.created_at ?? raw.trade_date,
  };
}

/** GET /trades/in-group/{group_id} — caller must be a member of the group. */
export async function listTradesInGroup(groupId: number): Promise<Trade[]> {
  const { data } = await apiClient.get<RawTrade[]>(`/trades/in-group/${groupId}`);
  const trades = Array.isArray(data) ? data.map(normalizeTrade) : [];
  // Resolve missing symbols in a batch, rather than one HTTP request per asset.
  const missingIds = [...new Set(trades.filter((t) => !t.symbol).map((t) => t.asset_id))];
  const symbols = new Map<number, string>();
  try {
    for (const asset of await getAssetsByIds(missingIds)) {
      symbols.set(asset.id, asset.symbol);
    }
  } catch {
    // Keep transactions visible even when the asset lookup is unavailable.
  }
  return trades.map((t) => ({ ...t, symbol: t.symbol ?? symbols.get(t.asset_id) }));
}

/**
 * GET /trades/symbol/{symbol} — returns TradeResponse[] (distinct shape).
 * NOTE: the backend returns 404 (not an empty array) when no trades exist.
 */
export async function listTradesBySymbol(symbol: string): Promise<TradeResponse[]> {
  const { data } = await apiClient.get<TradeResponse[]>(
    `/trades/symbol/${encodeURIComponent(symbol)}`,
  );
  return data;
}

/**
 * POST /trades/?symbol={symbol} — create a trade.
 * IMPORTANT: `symbol` is a QUERY PARAM, the rest is the JSON body.
 */
export async function createTrade(symbol: string, payload: TradeCreatePayload): Promise<Trade> {
  const { data } = await apiClient.post<RawTrade>("/trades/", payload, {
    params: { symbol },
  });
  return normalizeTrade(data);
}

/** PATCH /trades/{trade_id} — partial update. */
export async function updateTrade(tradeId: number, payload: TradeUpdatePayload): Promise<Trade> {
  const { data } = await apiClient.patch<RawTrade>(`/trades/${tradeId}`, payload);
  return normalizeTrade(data);
}

/** DELETE /trades/{trade_id} — 204 on success. */
export async function deleteTrade(tradeId: number): Promise<void> {
  await apiClient.delete(`/trades/${tradeId}`);
}
