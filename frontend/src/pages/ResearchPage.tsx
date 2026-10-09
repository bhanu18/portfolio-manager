import { useEffect, useRef, useState, type FormEvent } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import * as api from "../api/research";
import { ModernistNav } from "../components/ModernistNav";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { InvestmentAnalysisView } from "../components/InvestmentAnalysis";
import { ResearchReport } from "../components/ResearchReport";
import { safeResearchUrl } from "../lib/research";
import { useAuth } from "../context/AuthContext";
import { parseApiError } from "../lib/errors";
import type { ResearchEvidence, ResearchRun, ResearchProvider } from "../types";
import "../styles/modernist.css";
import "../styles/research.css";

const STARTERS = [
  {
    category: "COMPANY BRIEF",
    text: "Research Apple",
    description: "Valuation, MA50/200, backtests and scenarios",
  },
  {
    category: "SIDE BY SIDE",
    text: "Compare SPY and VTI",
    description: "Exposure, costs and important differences",
  },
  {
    category: "RATES & CASH",
    text: "Compare Treasury bills with money-market funds",
    description: "Yield conventions, liquidity and tradeoffs",
  },
];
const active = (run: ResearchRun) => run.status === "queued" || run.status === "running";
const date = (value: string) =>
  new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

function RunClock({ run }: { run: ResearchRun }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (run.status !== "queued" && run.status !== "running") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [run.status]);
  const seconds = Math.max(
    0,
    Math.floor(
      ((run.finished_at ? new Date(run.finished_at).getTime() : now) -
        new Date(run.created_at).getTime()) /
        1000,
    ),
  );
  return (
    <span>
      {Math.floor(seconds / 60)}m {seconds % 60}s
    </span>
  );
}

function SourceCard({ evidence }: { evidence: ResearchEvidence }) {
  const url = safeResearchUrl(evidence.url);
  const snapshot = evidence.snapshot;
  return (
    <li className="research-source">
      {url ? (
        <a href={url} target="_blank" rel="noopener noreferrer">
          {evidence.title} <span aria-hidden="true">↗</span>
        </a>
      ) : (
        <strong>{evidence.title}</strong>
      )}
      <small>{url ? new URL(url).hostname : "Source"}</small>
      {snapshot?.observed_at && <small>Observed {snapshot.observed_at.slice(0, 10)}</small>}
      <small>Retrieved {date(evidence.retrieved_at)}</small>
      {snapshot?.warnings.map((warning) => (
        <p className="research-data-warning" key={warning}>
          {warning}
        </p>
      ))}
      {snapshot && (
        <details>
          <summary>View figures & definitions</summary>
          <dl>
            {Object.entries(snapshot.values).map(([key, value]) => (
              <div key={key}>
                <dt>{key.replace(/_/g, " ")}</dt>
                <dd>
                  {value === null ? "Unavailable" : String(value)} {snapshot.units[key] ?? ""}
                </dd>
              </div>
            ))}
          </dl>
          {Object.entries(snapshot.definitions).map(([key, definition]) => (
            <p key={key}>{definition}</p>
          ))}
        </details>
      )}
    </li>
  );
}

export function ResearchPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [search] = useSearchParams();
  const { user } = useAuth();
  return (
    <ResearchWorkspace
      key={`${user?.id}:${sessionId ?? "new"}:${search.get("symbol") ?? ""}`}
      sessionId={sessionId}
      symbol={search.get("symbol")}
      userId={user?.id}
    />
  );
}

function ResearchWorkspace({
  sessionId,
  symbol,
  userId,
}: {
  sessionId?: string;
  symbol: string | null;
  userId?: number;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);
  const [prompt, setPrompt] = useState(symbol ? `Research ${symbol.slice(0, 20)}` : "");
  const [providerChoice, setProviderChoice] = useState<ResearchProvider | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const request = useRef<{
    prompt: string;
    provider: ResearchProvider;
    id: string;
    sessionId?: string;
  } | null>(null);
  const prefix = ["research", userId];
  const capabilities = useQuery({
    queryKey: [...prefix, "capabilities"],
    queryFn: api.capabilities,
  });
  const sessions = useInfiniteQuery({
    queryKey: [...prefix, "sessions"],
    queryFn: ({ pageParam }) => api.listSessions(pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => (last.length === 50 ? pages.length * 50 : undefined),
  });
  const detail = useQuery({
    queryKey: [...prefix, "session", sessionId],
    queryFn: () => api.getSession(sessionId!),
    enabled: !!sessionId,
    refetchInterval: (query) => (query.state.data?.runs.some(active) ? 2000 : false),
  });
  const runs = detail.data?.runs ?? [];
  const currentRun = runs.find(active);
  const selectedRun = runs.find((run) => run.id === selectedRunId) ?? runs[runs.length - 1];
  const options = capabilities.data?.providers ?? [];
  const previousProvider = runs[runs.length - 1]?.provider;
  const provider =
    providerChoice ??
    (options.find((option) => option.id === previousProvider)?.enabled
      ? previousProvider
      : capabilities.data?.default_provider) ??
    "openai";
  const unavailable = !options.find((option) => option.id === provider)?.enabled;
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: prefix });
  };
  const fail = (error: unknown) => setMutationError(parseApiError(error).message);
  const send = useMutation({
    mutationFn: async (question: string) => {
      // Keep the request key on transport failure: Retry cannot enqueue the same turn twice.
      if (
        !request.current ||
        request.current.prompt !== question ||
        request.current.provider !== provider
      )
        request.current = {
          prompt: question,
          provider,
          id: crypto.randomUUID(),
          sessionId: request.current?.sessionId ?? sessionId,
        };
      if (!request.current.sessionId) {
        request.current.sessionId = (await api.createSession()).id;
        void queryClient.invalidateQueries({ queryKey: [...prefix, "sessions"] });
      }
      return api.submitMessage(
        request.current.sessionId,
        question,
        request.current.id,
        request.current.provider,
      );
    },
    onSuccess: (run) => {
      request.current = null;
      setPrompt("");
      setMutationError(null);
      setSelectedRunId(run.id);
      void refresh();
      if (sessionId !== run.session_id) navigate(`/research/${run.session_id}`);
    },
    onError: fail,
  });
  const cancel = useMutation({
    mutationFn: api.cancelRun,
    onSuccess: () => void refresh(),
    onError: fail,
  });
  const rename = useMutation({
    mutationFn: () => api.renameSession(sessionId!, title.trim()),
    onSuccess: () => {
      setRenaming(false);
      void refresh();
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: () => api.deleteSession(sessionId!),
    onSuccess: () => {
      void refresh();
      navigate("/research");
    },
    onError: fail,
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!prompt.trim() || currentRun || unavailable || send.isPending) return;
    setMutationError(null);
    send.mutate(prompt.trim());
  };
  const choosePrompt = (question: string) => {
    setPrompt(question);
    textarea.current?.focus();
  };
  const retry = (question: string) => {
    request.current = null;
    choosePrompt(question);
  };
  const error = mutationError ?? (detail.error ? parseApiError(detail.error).message : null);
  const sourceCount = selectedRun?.evidence.length ?? 0;

  return (
    <>
      <div className="mod research-shell">
        <ModernistNav />
        <main className="research-main">
          <header className="research-heading">
            <div>
              <span className="research-eyebrow">MARKET INTELLIGENCE / US</span>
              <h1>
                Research desk<span className="research-dot">.</span>
              </h1>
              <p>Follow the evidence. Build your view.</p>
            </div>
            <div className="research-private">
              <span aria-hidden="true">◈</span> Private workspace
              <small>Public market data · On-demand analysis</small>
            </div>
          </header>
          {capabilities.data?.message && (
            <div className="research-notice" role="status">
              {capabilities.data.message}
            </div>
          )}
          {capabilities.error && (
            <div className="research-notice" role="alert">
              {parseApiError(capabilities.error).message}{" "}
              <button className="btn btn-ghost" onClick={() => void capabilities.refetch()}>
                Retry connection
              </button>
            </div>
          )}
          <div className="research-grid">
            <aside className="research-sidebar" aria-label="Saved research">
              <div className="research-panel-heading">
                <h2>Your research</h2>
                <Link to="/research" className="research-new" aria-label="New research">
                  +
                </Link>
              </div>
              <p className="research-muted">Saved automatically. Only visible to you.</p>
              {sessions.isPending && <p role="status">Loading sessions…</p>}
              {sessions.error && (
                <p role="alert">
                  Could not load sessions.{" "}
                  <button onClick={() => void sessions.refetch()}>Retry</button>
                </p>
              )}
              <nav className="research-sessions" aria-label="Research sessions">
                {sessions.data?.pages.flat().map((session) => (
                  <Link
                    key={session.id}
                    to={`/research/${session.id}`}
                    aria-current={session.id === sessionId ? "page" : undefined}
                  >
                    <strong>{session.title}</strong>
                    <small>{new Date(session.updated_at).toLocaleDateString()}</small>
                  </Link>
                ))}
              </nav>
              {sessions.data?.pages[0].length === 0 && (
                <p className="research-muted">Your first brief starts with a question.</p>
              )}
              {sessions.hasNextPage && (
                <button
                  className="btn btn-ghost"
                  disabled={sessions.isFetchingNextPage}
                  onClick={() => void sessions.fetchNextPage()}
                >
                  Load older research
                </button>
              )}
              <div className="research-sidebar-footer">
                <span className="research-eyebrow">COVERAGE</span>
                <p>
                  Stocks & ETFs
                  <br />
                  Treasury yields & bills
                  <br />
                  Bonds & money markets
                </p>
              </div>
            </aside>
            <section className="research-conversation" aria-label="Research conversation">
              {detail.isPending && sessionId ? (
                <p role="status">Loading research…</p>
              ) : (
                <>
                  {detail.data && (
                    <header className="research-session-heading">
                      {renaming ? (
                        <form
                          onSubmit={(event) => {
                            event.preventDefault();
                            rename.mutate();
                          }}
                        >
                          <label className="research-sr-only" htmlFor="research-title">
                            Session title
                          </label>
                          <input
                            id="research-title"
                            value={title}
                            onChange={(event) => setTitle(event.target.value)}
                            maxLength={120}
                            autoFocus
                          />
                          <button
                            className="btn btn-secondary"
                            disabled={!title.trim() || rename.isPending}
                          >
                            Save
                          </button>
                          <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={() => setRenaming(false)}
                          >
                            Cancel
                          </button>
                        </form>
                      ) : (
                        <>
                          <h2>{detail.data.title}</h2>
                          <div>
                            <button
                              className="btn btn-ghost"
                              onClick={() => {
                                setTitle(detail.data!.title);
                                setRenaming(true);
                              }}
                            >
                              Rename
                            </button>
                            <button className="btn btn-ghost" onClick={() => setDeleting(true)}>
                              Delete
                            </button>
                          </div>
                        </>
                      )}
                    </header>
                  )}
                  {!runs.length && !detail.error && (
                    <div className="research-welcome">
                      <span className="research-eyebrow">YOUR NEXT QUESTION</span>
                      <h2>
                        A clearer view of
                        <br />
                        the market.
                      </h2>
                      <p>
                        Ask about a company, compare funds, or understand rates. Get a concise brief
                        with sources you can inspect.
                      </p>
                      <div className="research-starters">
                        {STARTERS.map((starter) => (
                          <button key={starter.text} onClick={() => choosePrompt(starter.text)}>
                            <span className="research-eyebrow">{starter.category}</span>
                            <strong>
                              {starter.text} <span aria-hidden="true">↗</span>
                            </strong>
                            <small>{starter.description}</small>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {runs.map((run) => (
                    <article
                      key={run.id}
                      className={`research-turn ${selectedRun?.id === run.id ? "research-turn-selected" : ""}`}
                    >
                      <div className="research-question">
                        <span className="research-eyebrow">YOU ASKED</span>
                        <h2>{run.prompt}</h2>
                        <small>{date(run.created_at)}</small>
                      </div>
                      <div className="research-run-meta">
                        <span className={`research-status research-status-${run.status}`}>
                          {run.status}
                        </span>
                        <RunClock run={run} />
                        <button
                          className="btn btn-ghost"
                          onClick={() => setSelectedRunId(run.id)}
                          aria-pressed={selectedRun?.id === run.id}
                        >
                          Sources ({run.evidence.length})
                        </button>
                      </div>
                      {active(run) && (
                        <div className="research-progress" role="status">
                          <span className="research-pulse" aria-hidden="true" />
                          <div>
                            <strong>{run.stage}</strong>
                            <p>You can leave this page; your research will keep running.</p>
                            {run.status === "queued" && (
                              <small>
                                If this stays queued, make sure the research worker is running.
                              </small>
                            )}
                          </div>
                          <button
                            className="btn btn-secondary"
                            disabled={cancel.isPending}
                            onClick={() => cancel.mutate(run.id)}
                          >
                            Cancel
                          </button>
                        </div>
                      )}
                      {run.report && <ResearchReport text={run.report} citations={run.citations} />}
                      {run.error && (
                        <p className="research-notice" role="alert">
                          {run.error}
                        </p>
                      )}
                      {(run.status === "failed" || run.status === "cancelled") && (
                        <div className="research-incomplete">
                          <p>Incomplete research · {run.evidence.length} saved sources</p>
                          <button
                            className="btn btn-secondary"
                            disabled={!!currentRun || unavailable}
                            onClick={() => retry(run.prompt)}
                          >
                            Retry question
                          </button>
                        </div>
                      )}
                      {run.evidence
                        .filter((item) => item.snapshot?.analysis)
                        .map((item, index) => (
                          <InvestmentAnalysisView key={index} snapshot={item.snapshot!} />
                        ))}
                      {run.status === "completed" && (
                        <p className="research-report-footer">
                          {run.provider === "anthropic" ? "Anthropic" : "OpenAI"} · {run.model} ·{" "}
                          {run.tool_calls} tool calls ·{" "}
                          {(run.input_tokens + run.output_tokens).toLocaleString()} tokens ·
                          Research as of {date(run.finished_at!)}.
                        </p>
                      )}
                    </article>
                  ))}
                </>
              )}
              {error && (
                <div className="research-notice" role="alert">
                  {error}
                  {detail.error && (
                    <button className="btn btn-ghost" onClick={() => void detail.refetch()}>
                      Reload
                    </button>
                  )}
                </div>
              )}
              <form className="research-composer" onSubmit={submit}>
                <label htmlFor="research-provider">Research model</label>
                <select
                  id="research-provider"
                  value={provider}
                  onChange={(event) => setProviderChoice(event.target.value as ResearchProvider)}
                  disabled={!!currentRun || send.isPending || !capabilities.data?.enabled}
                >
                  {options.map((option) => (
                    <option key={option.id} value={option.id} disabled={!option.enabled}>
                      {option.label} · {option.model}
                      {option.enabled ? "" : " (not configured)"}
                    </option>
                  ))}
                </select>
                <label htmlFor="research-question">
                  {runs.length ? "Ask a follow-up" : "What would you like to research?"}
                </label>
                <textarea
                  id="research-question"
                  ref={textarea}
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  maxLength={6000}
                  rows={3}
                  placeholder="A ticker, a comparison, or a market question…"
                  disabled={!!currentRun || send.isPending || !!detail.error}
                />
                <div>
                  <small>
                    Sources and dates included · {capabilities.data?.daily_limit ?? 20} runs/day
                  </small>
                  <button
                    className="btn btn-primary"
                    disabled={
                      !prompt.trim() ||
                      !!currentRun ||
                      send.isPending ||
                      unavailable ||
                      !!detail.error ||
                      (!!sessionId && detail.isPending)
                    }
                  >
                    {send.isPending
                      ? "Starting…"
                      : runs.length
                        ? "Ask follow-up ↗"
                        : "Start research ↗"}
                  </button>
                </div>
              </form>
            </section>
            <aside className="research-evidence" aria-label="Sources and evidence">
              <div className="research-panel-heading">
                <h2>Evidence</h2>
                <span className="research-count">{sourceCount.toString().padStart(2, "0")}</span>
              </div>
              {selectedRun && <p className="research-muted">Sources for “{selectedRun.prompt}”</p>}
              {sourceCount ? (
                <ul>
                  {selectedRun!.evidence.map((item, index) => (
                    <SourceCard key={`${item.url}-${index}`} evidence={item} />
                  ))}
                </ul>
              ) : (
                <div className="research-evidence-empty">
                  <span aria-hidden="true">↗</span>
                  <h3>Trace every insight.</h3>
                  <p>
                    Source links, observation dates, and market-data warnings appear here as
                    research progresses.
                  </p>
                </div>
              )}
              <p className="research-muted research-source-footnote">
                Quotes may be delayed. Figures with different dates or yield definitions are not
                directly comparable.
              </p>
            </aside>
          </div>
        </main>
      </div>
      <ConfirmDialog
        open={deleting}
        title="Delete research?"
        message="This deletes the session, messages and saved evidence. Any running research will stop."
        confirmLabel="Delete research"
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
        onCancel={() => setDeleting(false)}
      />
    </>
  );
}
