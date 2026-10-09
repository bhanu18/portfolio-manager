import { useId } from "react";
import type { MarketSnapshot } from "../types";

const names: Record<string, string> = {
  buy_hold: "Buy & hold",
  price_above_sma200: "Price > SMA200",
  sma50_above_sma200: "SMA50 > SMA200",
};
const pct = (value: number | null) =>
  value === null ? "Unavailable" : (value * 100).toFixed(1) + "%";
const colors = ["#264653", "#b14d28", "#597640"];
type Series = { name: string; values: (number | null)[] };

function Chart({
  title,
  dates,
  series,
  percent = false,
}: {
  title: string;
  dates: string[];
  series: Series[];
  percent?: boolean;
}) {
  const id = useId();
  const values = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
  if (!dates.length || !values.length) return null;
  const low = Math.min(...values),
    high = Math.max(...values);
  const span = high - low || 1;
  const label = (v: number) => (percent ? pct(v) : v.toFixed(1));
  return (
    <figure className="investment-chart">
      <figcaption>{title}</figcaption>
      <svg viewBox="0 0 620 200" role="img" aria-labelledby={id}>
        <title id={id}>
          {title +
            ". " +
            dates[0] +
            " to " +
            dates[dates.length - 1] +
            ". Values from " +
            label(low) +
            " to " +
            label(high) +
            "."}
        </title>
        <text x="0" y="18">
          {label(high)}
        </text>
        <text x="0" y="175">
          {label(low)}
        </text>
        {series.map((s, index) => (
          <path
            key={s.name}
            fill="none"
            stroke={colors[index % colors.length]}
            strokeWidth="2"
            strokeDasharray={index === 1 ? "6 3" : index === 2 ? "2 3" : undefined}
            d={s.values
              .map((v, i) =>
                v === null
                  ? ""
                  : (i === 0 || s.values[i - 1] === null ? "M" : "L") +
                    (60 + (i / Math.max(1, dates.length - 1)) * 550).toFixed(2) +
                    "," +
                    (175 - ((v - low) / span) * 155).toFixed(2),
              )
              .join(" ")}
          />
        ))}
        <text x="60" y="198">
          {dates[0]}
        </text>
        <text x="610" y="198" textAnchor="end">
          {dates[dates.length - 1]}
        </text>
      </svg>
      <div className="investment-legend">
        {series.map((s, i) => (
          <span key={s.name} style={{ color: colors[i % colors.length] }}>
            {s.name}
          </span>
        ))}
      </div>
    </figure>
  );
}

export function InvestmentAnalysisView({ snapshot }: { snapshot: MarketSnapshot }) {
  const data = snapshot.analysis;
  if (!data) return null;
  const full = data.backtests.filter((result) => result.period === "full");
  return (
    <section className="investment-analysis" aria-label={snapshot.symbol + " investment analysis"}>
      <h3>{snapshot.symbol} · Trend & backtests</h3>
      <p>
        Completed close as of {snapshot.observed_at?.slice(0, 10)}. Historical simulations, not
        forecasts.
      </p>
      <p>Next-session close execution · 0.10% cost per entry/exit · 0% cash yield.</p>
      <dl className="investment-figures">
        <div>
          <dt>Adjusted close</dt>
          <dd>{data.price.toFixed(2)}</dd>
        </div>
        <div>
          <dt>SMA50</dt>
          <dd>
            {data.sma50.toFixed(2)} ({pct(data.distance_sma50)} distance)
          </dd>
        </div>
        <div>
          <dt>SMA200</dt>
          <dd>
            {data.sma200.toFixed(2)} ({pct(data.distance_sma200)} distance)
          </dd>
        </div>
        <div>
          <dt>20-session MA changes</dt>
          <dd>
            {pct(data.sma50_change_20_sessions)} / {pct(data.sma200_change_20_sessions)}
          </dd>
        </div>
      </dl>
      <p>
        Latest 50/200 crossover:{" "}
        {data.last_crossover
          ? data.last_crossover.direction + " · " + data.last_crossover.date
          : "None in available history"}
        .
      </p>
      <Chart
        title="Adjusted price and moving averages"
        dates={data.trend.map((p) => p.date)}
        series={[
          { name: "Adjusted close", values: data.trend.map((p) => p.price) },
          { name: "SMA50", values: data.trend.map((p) => p.sma50) },
          { name: "SMA200", values: data.trend.map((p) => p.sma200) },
        ]}
      />
      <Chart
        title="Growth of 100 after costs"
        dates={full[0]?.curve.map((p) => p.date) ?? []}
        series={full.map((r) => ({
          name: names[r.strategy] ?? r.strategy,
          values: r.curve.map((p) => p.equity),
        }))}
      />
      <Chart
        title="Drawdown from previous peak"
        percent
        dates={full[0]?.curve.map((p) => p.date) ?? []}
        series={full.map((r) => ({
          name: names[r.strategy] ?? r.strategy,
          values: r.curve.map((p) => p.drawdown),
        }))}
      />
      {[...new Set(data.backtests.map((r) => r.period))].map((period) => {
        const rows = data.backtests.filter((r) => r.period === period);
        return (
          <div key={period}>
            <h4>
              {period === "full"
                ? "Full evaluation"
                : period === "earlier_70_percent"
                  ? "Earlier 70%"
                  : "Recent 30%"}{" "}
              · {rows[0].start} – {rows[0].end}
            </h4>
            <div
              className="investment-table"
              role="region"
              aria-label={period + " strategy comparison"}
              tabIndex={0}
            >
              <table>
                <thead>
                  <tr>
                    {[
                      "Strategy",
                      "Total return",
                      "Annual return",
                      "Max drawdown",
                      "Volatility",
                      "Trades",
                      "Invested",
                    ].map((label) => (
                      <th scope="col" key={label}>
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.strategy}>
                      <th scope="row">{names[r.strategy] ?? r.strategy}</th>
                      <td>{pct(r.total_return)}</td>
                      <td>{pct(r.annualized_return)}</td>
                      <td>{pct(r.max_drawdown)}</td>
                      <td>{pct(r.annualized_volatility)}</td>
                      <td>{r.trades}</td>
                      <td>{pct(r.time_invested)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
      <details>
        <summary>Methodology & limitations</summary>
        <ul>
          {[...data.assumptions, ...snapshot.warnings].map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}
