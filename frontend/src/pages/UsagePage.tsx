import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import * as api from "../api/research";
import { ErrorState } from "../components/ErrorState";
import { formatDate } from "../lib/format";
import { parseApiError } from "../lib/errors";

const RANGES = [
  { days: 1, label: "Today" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
  { days: 365, label: "1 year" },
];
const PROVIDERS: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  local: "Local",
};

const tokens = (value: number) => value.toLocaleString();
const compact = (value: number) =>
  value.toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 });

/** Admin view of research token spend per model (server-wide, UTC days). */
export function UsagePage() {
  const [params, setParams] = useSearchParams();
  const requested = Number(params.get("days"));
  const days = RANGES.some((range) => range.days === requested) ? requested : 30;
  const usage = useQuery({
    queryKey: ["research", "usage", days],
    queryFn: () => api.modelUsage(days),
  });
  const report = usage.data;
  const calls = report?.models.reduce((sum, model) => sum + model.calls, 0) ?? 0;
  const failed = report?.models.reduce((sum, model) => sum + model.failed_calls, 0) ?? 0;

  return (
    <div className="page usage-page">
      <h1 className="page__title">Model usage</h1>
      <p className="muted">
        Research tokens by model across all users, including failed and failed-over calls.
        {report && <> Since {formatDate(report.since)} (UTC).</>}
      </p>
      <div className="workflow-toolbar">
        <label>
          Period
          <select
            className="field__input"
            value={days}
            onChange={(event) => setParams({ days: event.target.value }, { replace: true })}
          >
            {RANGES.map((range) => (
              <option key={range.days} value={range.days}>
                {range.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {usage.isLoading && <p role="status">Loading usage…</p>}
      {usage.isError && (
        <ErrorState
          message={parseApiError(usage.error).message}
          onRetry={() => void usage.refetch()}
        />
      )}
      {report && (
        <>
          <dl className="usage-stats">
            <div>
              <dt>Total tokens</dt>
              <dd className="fig" title={tokens(report.total_tokens)}>
                {compact(report.total_tokens)}
              </dd>
            </div>
            <div>
              <dt>Input</dt>
              <dd className="fig" title={tokens(report.input_tokens)}>
                {compact(report.input_tokens)}
              </dd>
            </div>
            <div>
              <dt>Output</dt>
              <dd className="fig" title={tokens(report.output_tokens)}>
                {compact(report.output_tokens)}
              </dd>
            </div>
            <div>
              <dt>Model calls</dt>
              <dd className="fig">
                {tokens(calls)}
                {failed > 0 && <span className="usage-failed"> · {tokens(failed)} failed</span>}
              </dd>
            </div>
          </dl>
          {report.models.length === 0 ? (
            <p>No research model calls in this period.</p>
          ) : (
            <div className="workflow-table">
              <table className="table">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Provider</th>
                    <th className="num">Input</th>
                    <th className="num">Output</th>
                    <th className="num">Total</th>
                    <th className="usage-share-head">Share</th>
                    <th className="num">Calls</th>
                    <th className="num">Failed</th>
                  </tr>
                </thead>
                <tbody>
                  {report.models.map((model) => {
                    const share = report.total_tokens
                      ? model.total_tokens / report.total_tokens
                      : 0;
                    return (
                      <tr key={`${model.provider}:${model.model}`}>
                        <td className="fig">{model.model}</td>
                        <td>{PROVIDERS[model.provider] ?? model.provider}</td>
                        <td className="num">{tokens(model.input_tokens)}</td>
                        <td className="num">{tokens(model.output_tokens)}</td>
                        <td className="num">{tokens(model.total_tokens)}</td>
                        <td>
                          <span className="usage-share" aria-label={`${(share * 100).toFixed(1)}%`}>
                            <span style={{ width: `${share * 100}%` }} />
                          </span>
                          <span className="usage-share-label">{(share * 100).toFixed(1)}%</span>
                        </td>
                        <td className="num">{tokens(model.calls)}</td>
                        <td className={`num${model.failed_calls ? " usage-failed" : ""}`}>
                          {tokens(model.failed_calls)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
