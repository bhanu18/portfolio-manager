// ---------------------------------------------------------------------------
// Assets resource module (/assets prefix).
// ---------------------------------------------------------------------------

import { apiClient } from "../lib/apiClient";
import type {
  Asset,
  AssetBySymbolResult,
  AssetCreatePayload,
  AssetUpdatePayload,
  UpdateAllPricesResult,
} from "../types";

export interface ListAssetsParams {
  skip?: number;
  limit?: number;
}

/** GET /assets/ — admin only. */
export async function listAssets(
  params: ListAssetsParams = {},
): Promise<Asset[]> {
  const { data } = await apiClient.get<Asset[]>("/assets/", { params });
  return data;
}

/**
 * GET /assets/{asset_id} — fetch by numeric ID (the natural list/detail flow).
 * NOTE: the /assets/{value} route also handles symbol lookups server-side, so
 * on a miss it can return HTTP 200 + { error: "..." } instead of a 404.
 * Returns the union so callers can use isAsset() to guard.
 */
export async function getAssetById(assetId: number): Promise<AssetBySymbolResult> {
  const { data } = await apiClient.get<AssetBySymbolResult>(`/assets/${assetId}`);
  return data;
}

/**
 * GET /assets/{symbol} — symbol lookup used as a "search" feature.
 * This endpoint is quirky: on a miss it returns HTTP 200 with a plain
 * { error: "Asset not found" } body instead of a 404, so callers must
 * inspect the body. We surface the raw union and let the caller decide.
 */
export async function getAssetBySymbol(
  symbol: string,
): Promise<AssetBySymbolResult> {
  const { data } = await apiClient.get<AssetBySymbolResult>(
    `/assets/${encodeURIComponent(symbol)}`,
  );
  return data;
}

/** Type guard for the symbol-lookup union. */
export function isAsset(result: AssetBySymbolResult): result is Asset {
  return (result as Asset).id !== undefined;
}

/** POST /assets/create — server fetches a live price via yfinance. */
export async function createAsset(
  payload: AssetCreatePayload,
): Promise<Asset> {
  const { data } = await apiClient.post<Asset>("/assets/create", payload);
  return data;
}

/** POST /assets/update-all-prices — bulk refresh. */
export async function updateAllPrices(): Promise<UpdateAllPricesResult> {
  const { data } = await apiClient.post<UpdateAllPricesResult>(
    "/assets/update-all-prices",
  );
  return data;
}

/** PATCH /assets/{asset_id} — admin only. `type` is required by the schema. */
export async function updateAsset(
  assetId: number,
  payload: AssetUpdatePayload,
): Promise<Asset> {
  const { data } = await apiClient.patch<Asset>(`/assets/${assetId}`, payload);
  return data;
}

/** DELETE /assets/{asset_id} — admin only. 204 on success. */
export async function deleteAsset(assetId: number): Promise<void> {
  await apiClient.delete(`/assets/${assetId}`);
}
