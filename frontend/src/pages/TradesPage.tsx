import { Link, useSearchParams } from "react-router-dom";
import { useQueries } from "@tanstack/react-query";
import { useAuth } from "../context/AuthContext";
import { listTradesInGroup } from "../api/trades";
import { money } from "../lib/overview";
import { formatDate, formatNumber } from "../lib/format";
import { ErrorState } from "../components/ErrorState";

export function TradesPage() {
  const { user } = useAuth();
  const groups = user?.groups ?? [];
  const [params, setParams] = useSearchParams();
  const group = params.get("group") ?? "";
  const search = params.get("q") ?? "";
  const selected = group ? groups.filter((g) => String(g.id) === group) : groups;
  const queries = useQueries({
    queries: selected.map((g) => ({
      queryKey: ["trades", "group", g.id],
      queryFn: () => listTradesInGroup(g.id),
    })),
  });
  const loading = queries.some((q) => q.isPending);
  const failed = queries.some((q) => q.isError);
  const rows = queries
    .flatMap((q) => q.data ?? [])
    .filter((t) => (t.symbol ?? "").toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => b.trade_date.localeCompare(a.trade_date) || b.id - a.id);
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  return (
    <div className="page">
      <h1 className="page__title">Trades</h1>
      <p className="muted">
        Your transaction history, newest first. Open a holding to review or edit its trades.
      </p>
      <div className="workflow-toolbar">
        <label>
          Group
          <select
            className="field__input"
            value={group}
            onChange={(e) => update("group", e.target.value)}
          >
            <option value="">All groups</option>
            {group && !selected.length && <option value={group}>Unavailable group</option>}
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Search symbol
          <input
            className="field__input"
            type="search"
            value={search}
            onChange={(e) => update("q", e.target.value)}
            placeholder="e.g. AAPL"
          />
        </label>
      </div>
      {loading && <p role="status">Loading trades…</p>}
      {failed && (
        <ErrorState
          message="Some group trades could not be loaded. The list may be incomplete."
          onRetry={() =>
            queries.forEach((q) => {
              if (q.isError) void q.refetch();
            })
          }
        />
      )}
      {group && !selected.length && (
        <ErrorState message="This group is unavailable. Choose one of your groups above." />
      )}
      {rows.length > 0 && (
        <div className="workflow-table">
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Asset</th>
                <th>Type</th>
                <th>Group</th>
                <th className="num">Quantity</th>
                <th className="num">Price</th>
                <th className="num">Total</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id}>
                  <td>{formatDate(t.trade_date)}</td>
                  <td>
                    {t.symbol ? (
                      <Link
                        className="holding-link"
                        to={`/holdings/${encodeURIComponent(t.symbol)}`}
                      >
                        {t.symbol}
                      </Link>
                    ) : (
                      `Asset #${t.asset_id}`
                    )}
                  </td>
                  <td>{t.trade_type.toUpperCase()}</td>
                  <td>{groups.find((g) => g.id === t.group_id)?.name ?? t.group_id}</td>
                  <td className="num">{formatNumber(t.quantity)}</td>
                  <td className="num">
                    {money(t.price_per_unit, t.currency)} {t.currency}
                  </td>
                  <td className="num">
                    {money(t.quantity * t.price_per_unit, t.currency)} {t.currency}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!loading && !failed && rows.length === 0 && (!group || selected.length > 0) && (
        <p>
          {groups.length === 0 ? (
            <>
              Join a group from <Link to="/profile">Profile</Link> before recording a trade.
            </>
          ) : search ? (
            "No trades match this symbol."
          ) : (
            "No trades yet. Use Record trade to add your first transaction."
          )}
        </p>
      )}
    </div>
  );
}
