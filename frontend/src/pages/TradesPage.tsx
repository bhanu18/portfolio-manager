import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import * as tradesApi from "../api/trades";
import * as assetsApi from "../api/assets";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { getErrorMessage, parseApiError } from "../lib/errors";
import { formatDate, formatNumber, formatPrice } from "../lib/format";
import { Spinner } from "../components/Spinner";
import { ErrorState } from "../components/ErrorState";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { TradeFormModal, type TradeFormResult } from "../components/TradeFormModal";
import type { Trade } from "../types";

export function TradesPage() {
  const { user } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();

  const groups = user?.groups ?? [];
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(groups[0]?.id ?? null);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Trade | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Trade | null>(null);

  const tradesQuery = useQuery({
    queryKey: ["trades", "group", selectedGroupId],
    queryFn: () => tradesApi.listTradesInGroup(selectedGroupId!),
    enabled: selectedGroupId !== null,
  });

  const trades = useMemo(() => tradesQuery.data ?? [], [tradesQuery.data]);

  // Collect all trade rows that don't already carry an inline symbol.
  // We resolve asset_id -> symbol by calling getAssetBySymbol is not feasible
  // without the symbol. Instead we call getAssetById which hits /assets/{id}.
  // NOTE: the /assets/{value} route handles both symbol strings AND numeric IDs
  // server-side. We pass the numeric id; if the backend returns an error body
  // (the quirky 200+{error} pattern) we guard with isAsset().
  const uniqueAssetIds = useMemo(
    () =>
      Array.from(new Set(trades.filter((t) => !t.symbol && t.asset_id > 0).map((t) => t.asset_id))),
    [trades],
  );

  const assetQueries = useQueries({
    queries: uniqueAssetIds.map((id) => ({
      queryKey: ["asset", id],
      queryFn: async () => {
        const result = await assetsApi.getAssetById(id);
        // getAssetById hits /assets/{id}. The same route also serves symbol
        // lookups and returns a 200 + {error} body on a miss — guard here.
        if (!assetsApi.isAsset(result)) {
          throw new Error((result as { error?: string }).error ?? "Not found");
        }
        return result;
      },
      staleTime: 5 * 60_000,
      retry: 1,
    })),
  });

  // Map asset_id -> symbol for display in the trades table rows.
  // Trades that already carry t.symbol skip the lookup entirely.
  const assetSymbolById = useMemo(() => {
    const map = new Map<number, string>();
    assetQueries.forEach((q) => {
      if (q.data && assetsApi.isAsset(q.data)) {
        map.set(q.data.id, q.data.symbol);
      }
    });
    return map;
  }, [assetQueries]);

  // Set of IDs whose asset query is still in-flight (show "…" placeholder).
  const assetLoadingIds = useMemo(() => {
    const set = new Set<number>();
    assetQueries.forEach((q, i) => {
      if (q.isLoading || q.isFetching) set.add(uniqueAssetIds[i]);
    });
    return set;
  }, [assetQueries, uniqueAssetIds]);

  const createMutation = useMutation({
    mutationFn: ({ symbol, values }: { symbol: string; values: TradeFormResult["values"] }) =>
      tradesApi.createTrade(symbol, values),
    onSuccess: () => {
      toast.success("Trade created.");
      setFormOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["trades"] });
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: number; values: TradeFormResult["values"] }) =>
      tradesApi.updateTrade(id, values),
    onSuccess: () => {
      toast.success("Trade updated.");
      setFormOpen(false);
      setEditing(null);
      void queryClient.invalidateQueries({ queryKey: ["trades"] });
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => tradesApi.deleteTrade(id),
    onSuccess: () => {
      toast.success("Trade deleted.");
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["trades"] });
    },
    onError: (err) => {
      toast.error(getErrorMessage(err));
      setDeleteTarget(null);
    },
  });

  const handleSubmit = (result: TradeFormResult) => {
    if (editing) {
      updateMutation.mutate({ id: editing.id, values: result.values });
    } else if (result.symbol) {
      createMutation.mutate({ symbol: result.symbol, values: result.values });
    }
  };

  const openCreate = () => {
    setEditing(null);
    setFormOpen(true);
  };

  const openEdit = (trade: Trade) => {
    setEditing(trade);
    setFormOpen(true);
  };

  if (groups.length === 0) {
    return (
      <div className="page">
        <div className="page__header">
          <h1 className="page__title">Trades</h1>
        </div>
        <div className="empty-state">
          <p>You're not a member of any group yet.</p>
          <p className="muted">
            Trades are scoped to a group. Once you're added to one, it'll appear here. You can
            review your memberships on your <Link to="/profile">profile</Link>.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page__header">
        <h1 className="page__title">Trades</h1>
        <div className="page__actions">
          <button
            type="button"
            className="btn btn--primary"
            onClick={openCreate}
            disabled={selectedGroupId === null}
          >
            + New trade
          </button>
        </div>
      </div>

      <div className="field field--inline">
        <label htmlFor="group-select" className="field__label">
          Group
        </label>
        <select
          id="group-select"
          className="field__input"
          value={selectedGroupId ?? ""}
          onChange={(e) => setSelectedGroupId(Number(e.target.value))}
        >
          {groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
      </div>

      <TradesTable
        loading={tradesQuery.isLoading}
        error={tradesQuery.error}
        trades={trades}
        assetSymbolById={assetSymbolById}
        assetLoadingIds={assetLoadingIds}
        onRetry={() => void tradesQuery.refetch()}
        onEdit={openEdit}
        onDelete={setDeleteTarget}
      />

      <TradeFormModal
        open={formOpen}
        trade={editing}
        groups={groups}
        defaultGroupId={selectedGroupId}
        knownSymbol={
          editing ? (editing.symbol ?? assetSymbolById.get(editing.asset_id) ?? null) : null
        }
        busy={createMutation.isPending || updateMutation.isPending}
        onCancel={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        onSubmit={handleSubmit}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete trade"
        message={deleteTarget ? `Delete trade #${deleteTarget.id}? This cannot be undone.` : ""}
        confirmLabel="Delete"
        busy={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

interface TradesTableProps {
  loading: boolean;
  error: unknown;
  trades: Trade[];
  assetSymbolById: Map<number, string>;
  /** IDs currently being fetched — used to show a loading placeholder. */
  assetLoadingIds: Set<number>;
  onRetry: () => void;
  onEdit: (trade: Trade) => void;
  onDelete: (trade: Trade) => void;
}

function TradesTable({
  loading,
  error,
  trades,
  assetSymbolById,
  assetLoadingIds,
  onRetry,
  onEdit,
  onDelete,
}: TradesTableProps) {
  if (loading) return <Spinner block label="Loading trades…" />;

  if (error) {
    const parsed = parseApiError(error);
    if (parsed.isForbidden) {
      return (
        <div className="alert alert--info">
          You're not a member of this group, so its trades can't be shown.
        </div>
      );
    }
    return <ErrorState message={parsed.message} onRetry={onRetry} />;
  }

  if (trades.length === 0) {
    return (
      <div className="empty-state">
        <p>No trades in this group yet.</p>
        <p className="muted">Use "New trade" to record one.</p>
      </div>
    );
  }

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Asset</th>
            <th>Type</th>
            <th>Date</th>
            <th className="num">Quantity</th>
            <th className="num">Price / unit</th>
            <th>Currency</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => {
            // t.symbol is set when the backend embeds the asset inline.
            // Otherwise fall back to the async-resolved symbol map.
            const symbol = t.symbol ?? assetSymbolById.get(t.asset_id);
            const isLoadingAsset = !symbol && t.asset_id > 0 && assetLoadingIds.has(t.asset_id);
            const label =
              symbol ?? (isLoadingAsset ? "…" : t.asset_id > 0 ? `Asset #${t.asset_id}` : "—");
            return (
              <tr key={t.id}>
                <td>
                  {symbol ? (
                    <Link to={`/assets/${encodeURIComponent(symbol)}`} className="link-button">
                      {label}
                    </Link>
                  ) : (
                    label
                  )}
                </td>
                <td>
                  <span
                    className={`badge ${t.trade_type === "buy" ? "badge--buy" : "badge--sell"}`}
                  >
                    {t.trade_type}
                  </span>
                </td>
                <td>{formatDate(t.trade_date)}</td>
                <td className="num">{formatNumber(t.quantity)}</td>
                <td className="num">{formatPrice(t.price_per_unit)}</td>
                <td>{t.currency}</td>
                <td className="row-actions">
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={() => onEdit(t)}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    className="btn btn--danger btn--sm"
                    onClick={() => onDelete(t)}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
