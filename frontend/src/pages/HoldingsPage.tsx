import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getPortfolioPerformance } from "../api/reports";
import { money, signedMoney, signedPct } from "../lib/overview";
import { parseApiError } from "../lib/errors";
import { ErrorState } from "../components/ErrorState";

export function HoldingsPage() {
  const [params, setParams] = useSearchParams();
  const search = params.get("q") ?? "";
  const sort = params.get("sort") ?? "weight";
  const report = useQuery({
    queryKey: ["performance", "USD", "SPY"],
    queryFn: ({ signal }) =>
      getPortfolioPerformance({ base_currency: "USD", benchmark_ticker: "SPY" }, signal),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const rows = [...(report.data?.holdings ?? [])]
    .filter((h) => `${h.ticker} ${h.asset_name}`.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) =>
      sort === "symbol"
        ? a.ticker.localeCompare(b.ticker)
        : sort === "return"
          ? b.total_return_pct - a.total_return_pct
          : b.weight_pct - a.weight_pct,
    );
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const returnTo = `/holdings${params.size ? `?${params}` : ""}`;
  return (
    <div className="page">
      <h1 className="page__title">Holdings</h1>
      <p className="muted">
        All positions across your groups. Choose a holding to review its trades, returns, and
        research.
      </p>
      <div className="workflow-toolbar">
        <label>
          Search holdings
          <input
            className="field__input"
            type="search"
            value={search}
            onChange={(e) => update("q", e.target.value)}
            placeholder="Symbol or name"
          />
        </label>
        <label>
          Sort by
          <select
            className="field__input"
            value={sort}
            onChange={(e) => update("sort", e.target.value)}
          >
            <option value="weight">Largest position</option>
            <option value="symbol">Symbol A–Z</option>
            <option value="return">Highest total return</option>
          </select>
        </label>
        <Link className="btn btn-secondary" to="/trades">
          View all trades
        </Link>
      </div>
      {report.isPending && (
        <p role="status">Loading positions and returns… This can take up to a minute.</p>
      )}
      {report.isError && (
        <ErrorState
          message={parseApiError(report.error).message}
          onRetry={() => void report.refetch()}
        />
      )}
      {report.data && (
        <div className="workflow-table">
          <table className="table">
            <thead>
              <tr>
                <th>Asset</th>
                <th className="num">Quantity</th>
                <th className="num">Value (USD)</th>
                <th className="num">Weight</th>
                <th className="num">Unrealized P&amp;L</th>
                <th className="num">Total return</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((h) => (
                <tr key={h.ticker} className="holding-row">
                  <td>
                    <Link
                      className="holding-link"
                      to={`/holdings/${encodeURIComponent(h.ticker)}`}
                      state={{ holdingsReturnTo: returnTo }}
                    >
                      {h.ticker}
                    </Link>
                    <div className="muted small">{h.asset_name}</div>
                  </td>
                  <td className="num">{h.quantity.toLocaleString()}</td>
                  <td className="num">{money(h.current_value_base, "USD")}</td>
                  <td className="num">{h.weight_pct.toFixed(1)}%</td>
                  <td className="num">{signedMoney(h.unrealized_gain_loss_base, "USD")}</td>
                  <td className="num">{signedPct(h.total_return_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {report.data && rows.length === 0 && (
        <div className="card">
          <p>
            {search
              ? "No holdings match your search."
              : "No positions yet. Record a trade to start your portfolio."}
          </p>
          {search ? (
            <button className="btn btn-secondary" onClick={() => update("q", "")}>
              Clear search
            </button>
          ) : (
            <Link className="btn btn-primary" to="/trades?recordTrade=1">
              Record your first trade
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
