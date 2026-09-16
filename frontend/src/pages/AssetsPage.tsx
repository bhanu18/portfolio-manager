import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as assetsApi from "../api/assets";
import { isAsset } from "../api/assets";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { getErrorMessage, parseApiError } from "../lib/errors";
import { formatDateTime, formatNumber, formatPrice } from "../lib/format";
import { Spinner } from "../components/Spinner";
import { ErrorState } from "../components/ErrorState";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { AssetFormModal, type AssetFormValues } from "../components/AssetFormModal";
import type { Asset } from "../types";

export function AssetsPage() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Asset | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Asset | null>(null);
  const [search, setSearch] = useState("");
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  // The list endpoint is admin-only; only query it for admins.
  const listQuery = useQuery({
    queryKey: ["assets"],
    queryFn: () => assetsApi.listAssets({ limit: 200 }),
    enabled: isAdmin,
  });

  const refreshMutation = useMutation({
    mutationFn: assetsApi.updateAllPrices,
    onSuccess: (result) => {
      toast.success(
        `Prices refreshed: ${result.updated_count} updated, ${result.skipped_count} skipped.`,
      );
      void queryClient.invalidateQueries({ queryKey: ["assets"] });
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  const createMutation = useMutation({
    mutationFn: (values: AssetFormValues) => assetsApi.createAsset(values),
    onSuccess: (asset) => {
      toast.success(`${asset.symbol} created.`);
      setFormOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["assets"] });
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: number; values: AssetFormValues }) =>
      assetsApi.updateAsset(id, {
        symbol: values.symbol,
        name: values.name,
        market: values.market,
        type: values.type,
      }),
    onSuccess: (asset) => {
      toast.success(`${asset.symbol} updated.`);
      setFormOpen(false);
      setEditing(null);
      void queryClient.invalidateQueries({ queryKey: ["assets"] });
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => assetsApi.deleteAsset(id),
    onSuccess: () => {
      toast.success("Asset deleted.");
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["assets"] });
    },
    onError: (err) => {
      // Surface the specific "trades still reference it" backend message.
      toast.error(getErrorMessage(err));
      setDeleteTarget(null);
    },
  });

  const handleFormSubmit = (values: AssetFormValues) => {
    if (editing) {
      updateMutation.mutate({ id: editing.id, values });
    } else {
      createMutation.mutate(values);
    }
  };

  const handleSearch = async (e: FormEvent) => {
    e.preventDefault();
    const symbol = search.trim();
    if (!symbol) return;
    setSearchError(null);
    setSearching(true);
    try {
      const result = await assetsApi.getAssetBySymbol(symbol);
      // This endpoint returns { error } (HTTP 200) on a miss — check the body.
      if (isAsset(result)) {
        navigate(`/assets/${encodeURIComponent(result.symbol)}`);
      } else {
        setSearchError(result.error || `No asset found for "${symbol}".`);
      }
    } catch (err) {
      setSearchError(getErrorMessage(err));
    } finally {
      setSearching(false);
    }
  };

  const openCreate = () => {
    setEditing(null);
    setFormOpen(true);
  };

  const openEdit = (asset: Asset) => {
    setEditing(asset);
    setFormOpen(true);
  };

  return (
    <div className="page">
      <div className="page__header">
        <h1 className="page__title">Assets</h1>
        <div className="page__actions">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => refreshMutation.mutate()}
            disabled={refreshMutation.isPending}
          >
            {refreshMutation.isPending ? "Refreshing…" : "Refresh prices"}
          </button>
          {isAdmin && (
            <button type="button" className="btn btn--primary" onClick={openCreate}>
              + Add asset
            </button>
          )}
        </div>
      </div>

      <form className="search-bar" onSubmit={handleSearch}>
        <input
          type="text"
          className="field__input"
          placeholder="Search by symbol (e.g. AAPL)…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search assets by symbol"
        />
        <button type="submit" className="btn btn--secondary" disabled={searching}>
          {searching ? "Searching…" : "Search"}
        </button>
      </form>
      {searchError && (
        <div className="alert alert--error" role="alert">
          {searchError}
        </div>
      )}

      {!isAdmin && (
        <div className="alert alert--info">
          Listing all assets requires an admin account. Use the search above to look up a specific
          asset by its symbol.
        </div>
      )}

      {isAdmin && (
        <AssetsTable
          loading={listQuery.isLoading}
          error={listQuery.isError ? getErrorMessage(listQuery.error) : null}
          forbidden={listQuery.isError && parseApiError(listQuery.error).isForbidden}
          assets={(listQuery.data ?? []).filter(
            (a) => a.total_quantity != null && a.total_quantity > 0,
          )}
          isAdmin={isAdmin}
          onRetry={() => void listQuery.refetch()}
          onView={(a) => navigate(`/assets/${encodeURIComponent(a.symbol)}`)}
          onEdit={openEdit}
          onDelete={setDeleteTarget}
        />
      )}

      <AssetFormModal
        open={formOpen}
        asset={editing}
        busy={createMutation.isPending || updateMutation.isPending}
        onCancel={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        onSubmit={handleFormSubmit}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete asset"
        message={
          deleteTarget
            ? `Delete ${deleteTarget.symbol} (${deleteTarget.name})? This cannot be undone.`
            : ""
        }
        confirmLabel="Delete"
        busy={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

interface AssetsTableProps {
  loading: boolean;
  error: string | null;
  forbidden: boolean;
  assets: Asset[];
  isAdmin: boolean;
  onRetry: () => void;
  onView: (asset: Asset) => void;
  onEdit: (asset: Asset) => void;
  onDelete: (asset: Asset) => void;
}

function AssetsTable({
  loading,
  error,
  forbidden,
  assets,
  isAdmin,
  onRetry,
  onView,
  onEdit,
  onDelete,
}: AssetsTableProps) {
  if (loading) return <Spinner block label="Loading assets…" />;

  if (forbidden) {
    return <div className="alert alert--info">You don't have permission to list all assets.</div>;
  }

  if (error) return <ErrorState message={error} onRetry={onRetry} />;

  if (assets.length === 0) {
    return (
      <div className="empty-state">
        <p>No assets yet.</p>
        {isAdmin && <p className="muted">Use “Add asset” to create one.</p>}
      </div>
    );
  }

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Name</th>
            <th>Market</th>
            <th>Type</th>
            <th className="num">Position</th>
            <th className="num">Current price</th>
            <th>Last updated</th>
            {isAdmin && <th aria-label="Actions" />}
          </tr>
        </thead>
        <tbody>
          {assets.map((asset) => (
            <tr key={asset.id}>
              <td>
                <button type="button" className="link-button" onClick={() => onView(asset)}>
                  {asset.symbol}
                </button>
              </td>
              <td>{asset.name}</td>
              <td>{asset.market}</td>
              <td>
                <span className="badge badge--muted">{asset.type}</span>
              </td>
              <td className="num">
                {asset.total_quantity != null ? (
                  formatNumber(asset.total_quantity)
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td className="num">{formatPrice(asset.current_price)}</td>
              <td>{formatDateTime(asset.price_last_updated)}</td>
              {isAdmin && (
                <td className="row-actions">
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={() => onEdit(asset)}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    className="btn btn--danger btn--sm"
                    onClick={() => onDelete(asset)}
                  >
                    Delete
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
