// ---------------------------------------------------------------------------
// PortfolioPage — split-panel view combining assets (left) + trades (right).
//
// Left panel  : asset list with position + price. Click a row to select it.
// Right panel : trades for the selected asset, full CRUD + group selector.
//               Also shows asset detail stats at the top.
// URL sync    : ?asset=NVDA keeps the selection bookmarkable / shareable.
// ---------------------------------------------------------------------------

import { useMemo, useState, useCallback } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import * as assetsApi from "../api/assets";
import * as tradesApi from "../api/trades";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { getErrorMessage, parseApiError } from "../lib/errors";
import { formatDate, formatDateTime, formatNumber, formatPrice, formatValue } from "../lib/format";
import { canEditOrDeleteTrade } from "../lib/permissions";
import { Spinner } from "../components/Spinner";
import { ErrorState } from "../components/ErrorState";
import { ConfirmDialog } from "../components/ConfirmDialog";
import {
  TradeFormModal,
  type TradeFormResult,
} from "../components/TradeFormModal";
import type { Asset } from "../types";

// ─── Asset list panel ────────────────────────────────────────────────────────

interface AssetRowProps {
  asset: Asset;
  selected: boolean;
  onSelect: () => void;
}

function AssetRow({ asset, selected, onSelect }: AssetRowProps) {
  const qty = asset.total_quantity ?? 0;
  const value = asset.current_price != null ? qty * asset.current_price : null;

  return (
    <button
      type="button"
      className={`portfolio-asset-row${selected ? " portfolio-asset-row--active" : ""}`}
      onClick={onSelect}
    >
      <div className="portfolio-asset-row__main">
        <span className="portfolio-asset-row__symbol">{asset.symbol}</span>
        <span className="portfolio-asset-row__name muted">{asset.name}</span>
      </div>
      <div className="portfolio-asset-row__meta">
        <span className="portfolio-asset-row__qty">
          {formatNumber(qty)} <span className="muted small">units</span>
        </span>
        <span className="portfolio-asset-row__value muted small">
          {formatValue(value, asset.market)}
        </span>
      </div>
    </button>
  );
}

// ─── Right panel: asset header ───────────────────────────────────────────────

interface AssetHeaderProps {
  asset: Asset;
  currency: string | null; // derived from trades, not the asset schema
  isAdmin: boolean;
  onEdit: () => void;
  onDelete: () => void;
}

function AssetHeader({ asset, currency, isAdmin, onEdit, onDelete }: AssetHeaderProps) {
  const qty = asset.total_quantity ?? 0;
  const value = asset.current_price != null ? qty * asset.current_price : null;

  return (
    <div className="portfolio-detail-header">
      <div className="portfolio-detail-header__top">
        <div>
          <div className="portfolio-detail-header__symbol">
            {asset.symbol}
            <span className="badge badge--muted" style={{ marginLeft: 8 }}>
              {asset.type}
            </span>
          </div>
          <div className="muted small">{asset.name} · {asset.market}</div>
        </div>
        {isAdmin && (
          <div className="row-actions">
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={onEdit}
            >
              Edit
            </button>
            <button
              type="button"
              className="btn btn--danger btn--sm"
              onClick={onDelete}
            >
              Delete
            </button>
          </div>
        )}
      </div>

      <div className="portfolio-detail-header__stats">
        <div className="portfolio-stat">
          <span className="portfolio-stat__label">
            Price {currency ? `(${currency.toUpperCase()})` : ""}
          </span>
          <span className="portfolio-stat__value">
            {formatValue(asset.current_price, currency)}
          </span>
        </div>
        <div className="portfolio-stat">
          <span className="portfolio-stat__label">Position</span>
          <span className="portfolio-stat__value">{formatNumber(qty)}</span>
        </div>
        <div className="portfolio-stat">
          <span className="portfolio-stat__label">Market value</span>
          <span className="portfolio-stat__value">
            {formatValue(value, currency)}
          </span>
        </div>
        <div className="portfolio-stat">
          <span className="portfolio-stat__label">Last updated</span>
          <span className="portfolio-stat__value small">
            {formatDateTime(asset.price_last_updated)}
          </span>
        </div>
      </div>
    </div>
  );
}

// ─── Right panel: trades table ───────────────────────────────────────────────
// Fetches trades directly by symbol — no group selection needed for viewing.
// Group selector only appears inside the "New trade" modal for creation.

interface TradesPanelProps {
  symbol: string;
  groups: { id: number; name: string }[];
  onNewTrade: () => void;
}

function TradesPanel({ symbol, groups, onNewTrade }: TradesPanelProps) {
  const { user, refreshUser } = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();

  const [editingId, setEditingId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; trade_type: string } | null>(null);
  const [formOpen, setFormOpen] = useState(false);

  // Fetch all trades for this symbol directly — works across all groups.
  const tradesQuery = useQuery({
    queryKey: ["trades", "symbol", symbol],
    queryFn: () => tradesApi.listTradesBySymbol(symbol),
    retry: false, // 404 = no trades, not a network error
  });

  const trades = tradesQuery.data ?? [];

  // For edit we need the full Trade shape — find it from the symbol response.
  // TradeResponse has id, trade_type, trade_date, quantity, price_per_unit.
  const editingTrade = editingId != null
    ? (trades.find((t) => t.id === editingId) ?? null)
    : null;

  /**
   * On 403, show a specific permission-denied message and re-sync the user
   * profile in case their role/membership changed since last fetch.
   */
  const handleTradeActionError = (err: unknown) => {
    const parsed = parseApiError(err);
    if (parsed.isForbidden) {
      toast.error("You don't have permission to modify this trade.");
      void refreshUser(); // re-sync role/group data in case it changed
    } else {
      toast.error(parsed.message);
    }
  };

  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: number; values: TradeFormResult["values"] }) =>
      tradesApi.updateTrade(id, values),
    onSuccess: () => {
      toast.success("Trade updated.");
      setFormOpen(false);
      setEditingId(null);
      void queryClient.invalidateQueries({ queryKey: ["trades"] });
      void queryClient.invalidateQueries({ queryKey: ["assets"] });
    },
    onError: handleTradeActionError,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => tradesApi.deleteTrade(id),
    onSuccess: () => {
      toast.success("Trade deleted.");
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["trades"] });
      void queryClient.invalidateQueries({ queryKey: ["assets"] });
    },
    onError: (err) => {
      handleTradeActionError(err);
      setDeleteTarget(null);
    },
  });

  const openEdit = (id: number) => {
    setEditingId(id);
    setFormOpen(true);
  };

  if (groups.length === 0) {
    return (
      <div className="empty-state">
        <p className="muted">You're not in any group yet.</p>
        <Link to="/profile" className="btn btn--ghost btn--sm">
          Go to profile
        </Link>
      </div>
    );
  }

  return (
    <>
      {/* Toolbar — just the "+ New trade" button, no group selector */}
      <div className="portfolio-trades-toolbar">
        <button
          type="button"
          className="btn btn--primary btn--sm"
          onClick={onNewTrade}
        >
          + New trade
        </button>
      </div>

      {tradesQuery.isLoading ? (
        <Spinner block label="Loading trades…" />
      ) : tradesQuery.isError ? (
        (() => {
          const parsed = parseApiError(tradesQuery.error);
          // 404 from this endpoint = no trades exist yet, not a real error.
          return parsed.isNotFound ? (
            <div className="empty-state">
              <p>No trades for {symbol} yet.</p>
              <p className="muted">Use "+ New trade" to record one.</p>
            </div>
          ) : (
            <ErrorState
              message={parsed.message}
              onRetry={() => void tradesQuery.refetch()}
            />
          );
        })()
      ) : trades.length === 0 ? (
        <div className="empty-state">
          <p>No trades for {symbol} yet.</p>
          <p className="muted">Use "+ New trade" to record one.</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Type</th>
                <th>Date</th>
                <th className="num">Quantity</th>
                <th className="num">Price / unit</th>
                <th>Group</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => {
                const canModify = canEditOrDeleteTrade(user, t);
                const createdBy = t.created_by_user_name;
                return (
                  <tr key={t.id}>
                    <td>
                      <span className={`badge ${t.trade_type === "buy" ? "badge--buy" : "badge--sell"}`}>
                        {t.trade_type}
                      </span>
                    </td>
                    <td>{formatDate(t.trade_date)}</td>
                    <td className="num">{formatNumber(t.quantity)}</td>
                    <td className="num">{formatPrice(t.price_per_unit)}</td>
                    <td className="muted small">
                      {t.group_name ?? "—"}
                      {!canModify && createdBy && (
                        <span
                          className="muted small"
                          style={{ display: "block", fontSize: "0.75em", marginTop: 2 }}
                          title={`Created by ${createdBy}`}
                        >
                          by {createdBy}
                        </span>
                      )}
                    </td>
                    <td className="row-actions">
                      {canModify ? (
                        <>
                          <button
                            type="button"
                            className="btn btn--ghost btn--sm"
                            onClick={() => openEdit(t.id)}
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            className="btn btn--danger btn--sm"
                            onClick={() => setDeleteTarget({ id: t.id, trade_type: t.trade_type })}
                          >
                            Delete
                          </button>
                        </>
                      ) : (
                        <span
                          className="muted small"
                          title={
                            createdBy
                              ? `Only ${createdBy} or a group admin can edit this trade`
                              : "You don't have permission to edit this trade"
                          }
                        >
                          —
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Edit modal — pre-fills from the TradeResponse fields we have */}
      {formOpen && editingTrade && (
        <TradeFormModal
          open
          trade={{
            id: editingTrade.id,
            asset_id: 0,
            symbol: editingTrade.symbol,
            trade_type: editingTrade.trade_type,
            trade_date: editingTrade.trade_date,
            quantity: editingTrade.quantity,
            price_per_unit: editingTrade.price_per_unit,
            currency: "",
            group_id: 0,
          }}
          groups={groups}
          defaultGroupId={groups[0]?.id ?? null}
          knownSymbol={symbol}
          busy={updateMutation.isPending}
          onCancel={() => { setFormOpen(false); setEditingId(null); }}
          onSubmit={(result) => {
            updateMutation.mutate({ id: editingTrade.id, values: result.values });
          }}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete trade"
        message={deleteTarget ? `Delete this ${deleteTarget.trade_type} trade? This cannot be undone.` : ""}
        confirmLabel="Delete"
        busy={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
        onCancel={() => setDeleteTarget(null)}
      />
    </>
  );
}

// ─── Main page ───────────────────────────────────────────────────────────────

export function PortfolioPage() {
  const { user, isAdmin } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  const groups = useMemo(() => user?.groups ?? [], [user]);

  // Selected asset driven by URL ?asset=SYMBOL for shareability.
  const selectedSymbol = searchParams.get("asset");

  const selectAsset = (symbol: string) => {
    setSearchParams({ asset: symbol }, { replace: true });
  };

  // ── Asset list ──────────────────────────────────────────────────────────────
  // Admins: GET /assets/ returns everything with total_quantity pre-computed.
  // Members: the /assets/ endpoint returns 403. Instead we fan-out over the
  //   user's groups via GET /trades/in-group/{id}, aggregate net quantities per
  //   symbol, then fetch each asset's current price/detail via GET /assets/{symbol}.
  //   This is done in a single React Query so the sidebar either loads or errors
  //   as one unit.

  const adminListQuery = useQuery({
    queryKey: ["assets"],
    queryFn: () => assetsApi.listAssets({ limit: 200 }),
    enabled: isAdmin,
  });

  // Fan-out: fetch all trades across every group the member belongs to.
  const memberTradesQueryFn = useCallback(async (): Promise<Asset[]> => {
    if (groups.length === 0) return [];

    // Fetch trades from each group in parallel (403 on any = skip it gracefully).
    const perGroupTrades = await Promise.all(
      groups.map((g) =>
        tradesApi.listTradesInGroup(g.id).catch(() => [] as Awaited<ReturnType<typeof tradesApi.listTradesInGroup>>),
      ),
    );
    const allTrades = perGroupTrades.flat();

    if (allTrades.length === 0) return [];

    // Aggregate net quantity per symbol.
    const symbolQty = new Map<string, number>();
    for (const t of allTrades) {
      const sym = t.symbol ?? "";
      if (!sym) continue;
      const delta = t.trade_type === "buy" ? t.quantity : -t.quantity;
      symbolQty.set(sym, (symbolQty.get(sym) ?? 0) + delta);
    }

    // Fetch asset detail for each unique symbol in parallel.
    const symbolEntries = [...symbolQty.entries()].filter(([, qty]) => qty > 0);
    const assetResults = await Promise.all(
      symbolEntries.map(async ([sym, qty]) => {
        const result = await assetsApi.getAssetBySymbol(sym).catch(() => null);
        if (!result || !assetsApi.isAsset(result)) return null;
        return { ...result, total_quantity: qty } as Asset;
      }),
    );

    return assetResults.filter((a): a is Asset => a !== null);
  }, [groups]);

  const memberListQuery = useQuery({
    queryKey: ["assets", "member", groups.map((g) => g.id).join(",")],
    queryFn: memberTradesQueryFn,
    enabled: !isAdmin && groups.length > 0,
  });

  // Unify both paths into a single `assets` array and loading/error flags.
  const listQuery = isAdmin ? adminListQuery : memberListQuery;

  const assets = useMemo(() => {
    if (isAdmin) {
      return (adminListQuery.data ?? []).filter(
        (a) => a.total_quantity != null && a.total_quantity > 0,
      );
    }
    // Member path: memberTradesQueryFn already filters qty > 0.
    return memberListQuery.data ?? [];
  }, [isAdmin, adminListQuery.data, memberListQuery.data]);

  // Selected asset detail (fetched by symbol).
  const selectedAssetQuery = useQuery({
    queryKey: ["asset", "symbol", selectedSymbol],
    queryFn: async () => {
      const result = await assetsApi.getAssetBySymbol(selectedSymbol!);
      if (!assetsApi.isAsset(result)) throw new Error(result.error ?? "Not found.");
      return result as Asset;
    },
    enabled: Boolean(selectedSymbol),
  });

  // New-trade modal (create only — edit lives inside TradesPanel).
  const [newTradeOpen, setNewTradeOpen] = useState(false);

  // Invalidate both the admin asset list and the member-built asset list.
  const invalidateAssets = () => {
    void queryClient.invalidateQueries({ queryKey: ["assets"] });
  };

  const createMutation = useMutation({
    mutationFn: ({ symbol, values }: { symbol: string; values: TradeFormResult["values"] }) =>
      tradesApi.createTrade(symbol, values),
    onSuccess: () => {
      toast.success("Trade created.");
      setNewTradeOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["trades"] });
      invalidateAssets();
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  // Asset admin: edit + delete.
  const [editingAsset, setEditingAsset] = useState<Asset | null>(null);
  const [deleteAssetTarget, setDeleteAssetTarget] = useState<Asset | null>(null);

  const deleteAssetMutation = useMutation({
    mutationFn: (id: number) => assetsApi.deleteAsset(id),
    onSuccess: () => {
      toast.success("Asset deleted.");
      setDeleteAssetTarget(null);
      if (selectedSymbol === deleteAssetTarget?.symbol) {
        setSearchParams({}, { replace: true });
      }
      invalidateAssets();
    },
    onError: (err) => {
      toast.error(getErrorMessage(err));
      setDeleteAssetTarget(null);
    },
  });

  // Refresh prices.
  const refreshMutation = useMutation({
    mutationFn: assetsApi.updateAllPrices,
    onSuccess: (r) => {
      toast.success(`Prices refreshed: ${r.updated_count} updated, ${r.skipped_count} skipped.`);
      invalidateAssets();
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  const selectedAsset = selectedAssetQuery.data ?? null;

  return (
    <div className="portfolio-shell">
      {/* ── Left panel: asset list ── */}
      <aside className="portfolio-sidebar">
        <div className="portfolio-sidebar__header">
          <span className="portfolio-sidebar__title">Portfolio</span>
          <div className="row-actions">
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              title="Refresh prices"
              onClick={() => refreshMutation.mutate()}
              disabled={refreshMutation.isPending}
            >
              {refreshMutation.isPending ? "…" : "↻"}
            </button>
          </div>
        </div>

        {groups.length === 0 && !isAdmin ? (
          <div className="portfolio-sidebar__empty muted small">
            You're not in any group yet.{" "}
            <Link to="/profile" style={{ fontSize: "inherit" }}>Profile →</Link>
          </div>
        ) : listQuery.isLoading ? (
          <Spinner block label="Loading…" />
        ) : listQuery.isError ? (
          <div className="portfolio-sidebar__error muted small">
            {getErrorMessage(listQuery.error)}
          </div>
        ) : assets.length === 0 ? (
          <div className="portfolio-sidebar__empty muted small">
            No positions yet.
          </div>
        ) : (
          <div className="portfolio-asset-list">
            {assets.map((a) => (
              <AssetRow
                key={a.id}
                asset={a}
                selected={selectedSymbol === a.symbol}
                onSelect={() => selectAsset(a.symbol)}
              />
            ))}
          </div>
        )}
      </aside>

      {/* ── Right panel: detail + trades ── */}
      <main className="portfolio-detail">
        {!selectedSymbol ? (
          <div className="portfolio-detail__empty">
            <p className="muted">Select an asset to view its trades.</p>
          </div>
        ) : selectedAssetQuery.isLoading ? (
          <Spinner block label="Loading asset…" />
        ) : selectedAssetQuery.isError || !selectedAsset ? (
          <ErrorState
            message={
              selectedAssetQuery.error
                ? getErrorMessage(selectedAssetQuery.error)
                : "Asset not found."
            }
            onRetry={() => void selectedAssetQuery.refetch()}
          />
        ) : (
          <div className="portfolio-detail__content">
            <AssetHeader
              asset={selectedAsset}
              currency={selectedAsset.market}
              isAdmin={isAdmin}
              onEdit={() => setEditingAsset(selectedAsset)}
              onDelete={() => setDeleteAssetTarget(selectedAsset)}
            />

            <div className="portfolio-detail__trades-heading">
              <h3 style={{ margin: 0 }}>Trades</h3>
            </div>

            <TradesPanel
              symbol={selectedSymbol}
              groups={groups}
              onNewTrade={() => setNewTradeOpen(true)}
            />
          </div>
        )}
      </main>

      {/* New trade modal (create mode, symbol locked to selection) */}
      <TradeFormModal
        open={newTradeOpen}
        trade={null}
        groups={groups}
        defaultGroupId={groups[0]?.id ?? null}
        knownSymbol={selectedSymbol}
        busy={createMutation.isPending}
        onCancel={() => setNewTradeOpen(false)}
        onSubmit={(result) => {
          if (result.symbol) {
            createMutation.mutate({ symbol: result.symbol, values: result.values });
          }
        }}
      />

      {/* Asset edit modal (reuses AssetFormModal) */}
      {editingAsset && isAdmin && (
        <AssetEditWrapper
          asset={editingAsset}
          onClose={() => setEditingAsset(null)}
          onSaved={() => {
            setEditingAsset(null);
            void queryClient.invalidateQueries({ queryKey: ["assets"] });
            void queryClient.invalidateQueries({ queryKey: ["asset", "symbol", selectedSymbol] });
          }}
        />
      )}

      {/* Asset delete confirm */}
      <ConfirmDialog
        open={deleteAssetTarget !== null}
        title="Delete asset"
        message={
          deleteAssetTarget
            ? `Delete ${deleteAssetTarget.symbol}? This cannot be undone if no trades reference it.`
            : ""
        }
        confirmLabel="Delete"
        busy={deleteAssetMutation.isPending}
        onConfirm={() => deleteAssetTarget && deleteAssetMutation.mutate(deleteAssetTarget.id)}
        onCancel={() => setDeleteAssetTarget(null)}
      />
    </div>
  );
}

// ─── Thin wrapper to lazy-import AssetFormModal only when needed ─────────────

import {
  AssetFormModal,
  type AssetFormValues,
} from "../components/AssetFormModal";
import * as assetsApiAlias from "../api/assets";

function AssetEditWrapper({
  asset,
  onClose,
  onSaved,
}: {
  asset: Asset;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();

  const updateMutation = useMutation({
    mutationFn: (values: AssetFormValues) =>
      assetsApiAlias.updateAsset(asset.id, {
        symbol: values.symbol,
        name: values.name,
        market: values.market,
        type: values.type,
      }),
    onSuccess: (updated) => {
      toast.success(`${updated.symbol} updated.`);
      onSaved();
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  return (
    <AssetFormModal
      open
      asset={asset}
      busy={updateMutation.isPending}
      onCancel={onClose}
      onSubmit={(values) => updateMutation.mutate(values)}
    />
  );
}
