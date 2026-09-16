import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import * as assetsApi from "../api/assets";
import * as tradesApi from "../api/trades";
import { parseApiError, getErrorMessage } from "../lib/errors";
import { formatDate, formatDateTime, formatNumber, formatPrice } from "../lib/format";
import { Spinner } from "../components/Spinner";
import { ErrorState } from "../components/ErrorState";
import type { Asset, TradeResponse } from "../types";

export function AssetDetailPage() {
  // Route is /assets/:symbol — look up by symbol string, not numeric ID.
  const { symbol } = useParams<{ symbol: string }>();

  const assetQuery = useQuery({
    queryKey: ["asset", "symbol", symbol],
    queryFn: async () => {
      const result = await assetsApi.getAssetBySymbol(symbol!);
      // The endpoint returns { error: "..." } with HTTP 200 on a miss.
      if (!assetsApi.isAsset(result)) {
        throw new Error(result.error ?? "Asset not found.");
      }
      return result as Asset;
    },
    enabled: Boolean(symbol),
  });

  const asset = assetQuery.data;

  // Trades for this asset, looked up by symbol once we know it.
  const tradesQuery = useQuery({
    queryKey: ["trades", "symbol", symbol],
    queryFn: () => tradesApi.listTradesBySymbol(symbol!),
    enabled: Boolean(symbol),
    // The endpoint 404s when there are no trades — treat that as "empty".
    retry: false,
  });

  // True while the asset is still loading or trades haven't started yet.
  // Prevents a premature "No trades" empty state.
  const tradesLoading = assetQuery.isLoading || tradesQuery.isLoading || tradesQuery.isFetching;

  if (assetQuery.isLoading) {
    return <Spinner block label="Loading asset…" />;
  }

  if (assetQuery.isError || !asset) {
    return (
      <div className="page">
        <Link to="/assets" className="back-link">
          ← Back to assets
        </Link>
        <ErrorState
          message={assetQuery.error ? getErrorMessage(assetQuery.error) : "Asset not found."}
          onRetry={() => void assetQuery.refetch()}
        />
      </div>
    );
  }

  return (
    <div className="page">
      <Link to="/assets" className="back-link">
        ← Back to assets
      </Link>

      <div className="page__header">
        <div>
          <h1 className="page__title">
            {asset.symbol}
            <span className="badge badge--muted" style={{ marginLeft: 12 }}>
              {asset.type}
            </span>
          </h1>
          <p className="muted">{asset.name}</p>
        </div>
        <div className="page__actions">
          <Link to="/trades" className="btn btn--secondary">
            Go to trades
          </Link>
        </div>
      </div>

      <section className="card">
        <h2 className="card__title">Details</h2>
        <dl className="detail-list">
          <div className="detail-list__row">
            <dt>Market</dt>
            <dd>{asset.market}</dd>
          </div>
          <div className="detail-list__row">
            <dt>Current price</dt>
            <dd>{formatPrice(asset.current_price)}</dd>
          </div>
          <div className="detail-list__row">
            <dt>Price last updated</dt>
            <dd>{formatDateTime(asset.price_last_updated)}</dd>
          </div>
          <div className="detail-list__row">
            <dt>Created</dt>
            <dd>{formatDateTime(asset.created_at)}</dd>
          </div>
          <div className="detail-list__row">
            <dt>Updated</dt>
            <dd>{formatDateTime(asset.updated_at)}</dd>
          </div>
        </dl>
      </section>

      <section className="card">
        <h2 className="card__title">Trades for {asset.symbol}</h2>
        <AssetTrades
          loading={tradesLoading}
          error={tradesQuery.error}
          trades={tradesQuery.data ?? []}
          onRetry={() => void tradesQuery.refetch()}
        />
      </section>
    </div>
  );
}

interface AssetTradesProps {
  loading: boolean;
  error: unknown;
  trades: TradeResponse[];
  onRetry: () => void;
}

function AssetTrades({ loading, error, trades, onRetry }: AssetTradesProps) {
  if (loading) return <Spinner block label="Loading trades…" />;

  if (error) {
    // 404 from this endpoint means "no trades for this symbol", not a failure.
    const parsed = parseApiError(error);
    if (parsed.status === 404) {
      return <p className="muted">No trades recorded for this asset yet.</p>;
    }
    return <ErrorState message={parsed.message} onRetry={onRetry} />;
  }

  if (trades.length === 0) {
    return <p className="muted">No trades recorded for this asset yet.</p>;
  }

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Type</th>
            <th>Date</th>
            <th className="num">Quantity</th>
            <th className="num">Price / unit</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.id}>
              <td>
                <span className={`badge ${t.trade_type === "buy" ? "badge--buy" : "badge--sell"}`}>
                  {t.trade_type}
                </span>
              </td>
              <td>{formatDate(t.trade_date)}</td>
              <td className="num">{formatNumber(t.quantity)}</td>
              <td className="num">{formatPrice(t.price_per_unit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
