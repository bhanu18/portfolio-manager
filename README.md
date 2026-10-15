# Portfolio Manager

[![CI](https://github.com/bhanu18/portfolio-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/bhanu18/portfolio-manager/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](backend/LICENSE)

A multi-currency stock, ETF and crypto portfolio tracker. Record trades, share portfolios with a group,
and see what your holdings are worth today in any currency — with FIFO cost basis and FX-adjusted returns.
A built-in research desk answers market questions with cited sources, orchestrated with LangChain and
LangGraph across OpenAI, Anthropic and local models, traced and evaluated with LangSmith.

<!-- Screenshots: add images to docs/screenshots/ and uncomment
![Portfolio](docs/screenshots/portfolio.png)
![Performance](docs/screenshots/performance.png)
-->

## Features

- **Assets** — stocks, ETFs, crypto and cash; live prices from Yahoo Finance with bulk refresh
- **Trades** — buys and sells in the asset's native currency, scoped to a group
- **Trade import** — upload a Yahoo Finance portfolio export (Trades → Import from Yahoo) with a
  dry-run preview; re-imports update rather than duplicate. Files with other column layouts are
  mapped by a local model (`IMPORT_LLM_MODEL`, else `LOCAL_LLM_MODEL`); the model only picks the
  columns — values are still parsed deterministically, and nothing leaves the machine
- **Groups** — shared portfolios with per-group roles (admin / member) on top of global user roles
- **Valuation** — current value of any holding converted to a target currency
- **Performance report** — FIFO cost basis, unrealized gain/loss, annualized return, local vs. FX gain,
  breakdowns by currency and asset type, benchmark comparison and alpha
- **Research desk** — sourced analyst briefs on stocks, ETFs, Treasuries and money markets, with
  moving-average backtests and follow-up questions; runs on OpenAI, Anthropic or a local model, or
  **Auto**, which routes each step to the cheapest capable model ([details](#research-desk))
- **Auth** — JWT (OAuth2 password flow), registration, password change and email-based reset,
  rate-limited sensitive endpoints

## Architecture

```
portfolio-manager/
├── backend/          FastAPI, SQLAlchemy (aiomysql), Alembic, pytest
│   ├── service/research/   research worker: LangGraph pipeline, LangChain agents, tools
│   └── evals/              research evals (LangSmith datasets and experiments)
├── frontend/         Vite, React 18, TypeScript, React Query, axios
├── docs/             feature specs (reports, permissions, scoring)
└── .github/workflows CI for both apps
```

## Getting started

### Backend — http://localhost:8000 (interactive docs at `/docs`)

Requires **Python 3.12** and a MySQL database.

```bash
cd backend
uv venv venv --python 3.12 && source venv/bin/activate   # or: python3.12 -m venv venv
uv pip install -r requirements-dev.txt                   # or: pip install -r requirements-dev.txt
cp .env.example .env                                     # set DB URLs, SECRET_KEY, SMTP
alembic upgrade head                                     # migrations are not run on app start
uvicorn main:app --reload
```

> Python 3.14 fails to build `pydantic_core` / `watchfiles` with the pinned versions.

### Frontend — http://localhost:5173

```bash
cd frontend
npm install
cp .env.example .env    # VITE_API_BASE_URL=http://localhost:8000
npm run dev
```

Allowed frontend origins are configured with `CORS_ORIGINS` (comma-separated) in `backend/.env`.

## Quality checks

Everything below runs in GitHub Actions on every push and pull request.

| | Backend (`cd backend`) | Frontend (`cd frontend`) |
|---|---|---|
| Lint | `ruff check .` | `npm run lint` |
| Format | `ruff format .` | `npm run format` |
| Types | `mypy` | `npm run typecheck` |
| Tests | `pytest` (needs `TEST_DATABASE_URL`) | `npm test` |
| Build | `docker build -t portfolio-api .` | `npm run build` |

Research evals are run on demand, not in CI, because the full ones call paid models. See
[Evaluation](#evaluation); `python -m evals.run_research routing --rules-only` is free.

Pre-commit hooks run the linters and formatters before each commit:

```bash
pip install pre-commit && pre-commit install
pre-commit run --all-files
```

Tests run against a real MySQL database: the schema is created with Alembic once per session and every
test runs inside a transaction that is rolled back.

## Docker (backend)

```bash
cd backend
docker build -t portfolio-api .
docker run --env-file .env portfolio-api alembic upgrade head
docker run --env-file .env -p 8000:8000 portfolio-api
```

Health check: `GET /health` (reports database connectivity).

## Tech stack

**Backend:** Python 3.12 · FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2 · MySQL · python-jose ·
passlib/bcrypt · slowapi · yfinance · pandas · pytest · ruff · mypy

**Research:** LangChain (`create_agent`, middleware) · LangGraph · LangSmith (tracing, datasets,
experiments) · OpenAI Responses API · Anthropic Messages API · OpenAI-compatible local servers

**Frontend:** React 18 · TypeScript · Vite · React Router · TanStack Query · axios · ESLint · Prettier

## Research desk

Research US stocks and ETFs, Treasury yields and bills, money-market funds, and bond
issuer risks in **Research**. Ask a question, inspect the dated evidence alongside a
saved analyst brief, and ask follow-ups. Use **Research** on a holding to prefill its
ticker; portfolio balances are never sent to the agent. Sessions are private to their
owner, including when that owner belongs to a shared portfolio group.

The agent supports OpenAI Responses (default `gpt-5-mini`), Anthropic Messages
(default `claude-sonnet-5-5`) and local models over an OpenAI-compatible API
(Ollama, LM Studio, vLLM, mlx_lm), with cited web search on the cloud providers,
read-only Yahoo market snapshots, and the official US Treasury XML feeds. Reports
retain inline citations, source URLs, observation dates, retrieval times, units, and
provider warnings. Quotes may be delayed; individual bond pricing, bond accounting,
trading, scheduled monitoring, and shared reports are not included.

### How it works

The API only queues a run; a separate worker process claims it and does the research.

**Auto mode** is a LangGraph graph. A local model (or keyword rules, if none is configured)
classifies the question; market data and, when needed, web research run **in parallel**; then the
writer runs on the cheapest model tier that fits the task (clarify/lookup → local, news → cheap
cloud, analysis → strong cloud):

```mermaid
graph TD;
  start([question]) --> classify;
  classify -.-> data["gather market data<br/>(no LLM)"];
  classify -.-> web["web research<br/>(cheap tier)"];
  data --> writer["writer<br/>(tier by task)"];
  web --> writer;
  writer --> report([cited report]);
```

**Each model step** is a LangChain `create_agent` loop over the provider's chat model, with the
read-only market tools as LangChain tools and the provider's own web search. A custom
`BudgetMiddleware` enforces the research rules:
- token, context and tool-call budgets, with hosted web searches counted;
- an output cap on each call;
- progress updates the UI polls;
- source collection;
- safe answers for invalid tool calls.

It also continues Anthropic's paused (`pause_turn`) responses. Provider differences live in small
hooks: stop reasons, citation format, error advice and request settings. Code:
`backend/service/research/` (`orchestrator.py`, `langchain_agent.py`, `models.py`, `tools.py`).

**Failover.** Account-level errors (credit, bad key, rate limit, outage) move the step to the next
configured model and put that provider in a short in-process cooldown. Question-level failures are
not retried on another cloud model. This applies whether you pick a provider explicitly or use Auto.
Retries are off in the SDKs, so a request is never silently billed twice.

**Tracing.** Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` to send one trace per run to
LangSmith: the graph, each node, each model step and every LLM and tool call, with token counts.
Tracing is off by default, because traces contain user questions. `LANGSMITH_HIDE_INPUTS` and
`LANGSMITH_HIDE_OUTPUTS` redact them.

### Setup

1. Apply migrations: `cd backend && alembic upgrade head`.
2. Configure at least one model in `backend/.env`; keys stay on the server:
   - `OPENAI_API_KEY` (`RESEARCH_MODEL` selects another Responses model with web search and
     function tools);
   - `ANTHROPIC_API_KEY` (`ANTHROPIC_RESEARCH_MODEL`);
   - and/or a local model: `LOCAL_LLM_MODEL`, with `LOCAL_LLM_BASE_URL` defaulting to Ollama's
     `http://localhost:11434/v1`. For example, `ollama pull qwen3:8b`; raise
     `OLLAMA_CONTEXT_LENGTH` to at least 16384.

   Auto's tiers are `RESEARCH_TIER_CHEAP` / `RESEARCH_TIER_STRONG` (`provider:model`).
3. Start the API normally, then start a **separate process** from `backend/`:

   ```bash
   source venv/bin/activate
   python -m service.research.worker
   ```

The API only queues work. At least one worker must run against the same database and
configuration as the API. Multiple workers use row locks and skip locked jobs to claim
work atomically (MySQL 8+). Navigation or refresh does not stop a job. Workers renew
30-second leases every 10 seconds. Shutdown, expired leases, missing workers, and the
three-minute run deadline produce retryable failures; partial evidence remains saved.
Cancellation stops future work and cancels an in-flight HTTP request when observed by
the heartbeat; a provider request already accepted may still incur charges.

Without a key, saved sessions remain readable and the composer shows a setup message.
The frontend polls active sessions every two seconds. The API exposes owner-scoped
`/research/sessions`, `/research/sessions/{id}/messages`, `/research/runs/{id}`, and
`/research/runs/{id}/cancel`; interactive schemas are available at `/docs`.

### Limits and validation

All research settings are documented in `backend/.env.example`. Defaults are one
active run per user, 20 starts per UTC day, six model turns, eight total tool calls,
24,000 input tokens and 12,000 output tokens per run. Input is conservatively bounded
by UTF-8 byte count before each model call; old conversation context is trimmed.
Usage totals include reasoning tokens reported by the provider. Cancelled and failed
starts count toward the daily limit, and deleting a session does not reset it.
These are request/token limits, not an exact dollar spending cap; configure provider
billing controls as appropriate. SDK-level retries are disabled; only the failover described
above moves a step to another model.

Offline tests never call a paid API:
- `tests/test_langchain_agent.py`, `test_openai_agent.py` and `test_local_agent.py` run the real
  LangChain clients against mocked provider HTTP APIs: request shape, parsing, budgets,
  citations, errors.
- `test_orchestrator.py` covers routing, the graph (including that data and web overlap),
  failover and trace shape.
- `test_research_agent.py` covers market-data providers.
- `test_research_api.py` covers the API, queue, migration round-trip and isolation; it needs the
  disposable `TEST_DATABASE_URL`. Run `npm run test:research` in
`frontend/` for citation, comparison-table, and HTML-safety rendering checks. CI never
needs a paid provider key. For a live smoke test after
setup, research Apple, compare SPY/VTI, compare Treasury bills with money-market funds,
ask a follow-up, reload an active session, and verify its citations and observation dates.

### Evaluation

`backend/evals/` scores the research pipeline. Usage is in its
[README](backend/evals/README.md).
- **Dataset:** 54 labelled questions. They test routing (question type, web need, tickers,
  Treasury topic) and report quality (every figure must match fetched market data; citation
  spans must be valid).
- **Running it:**
  - `python -m evals.run_research routing --rules-only` is free.
  - `full --market offline` runs real models on deterministic market data, so score changes come
    from the models and orchestration, not the market.
- **LangSmith:** with `LANGSMITH_API_KEY` set, the dataset syncs to LangSmith and each run is a
  comparable experiment, tagged with git SHA and model tiers.
- **What it found:** the evals uncovered router bugs (`P/E` and `T-bill` read as tickers,
  company names missed). They're fixed, with held-out examples to check that the fixes
  generalize.

### Research provider selection

Choose Auto, OpenAI, Anthropic or Local in the research composer, including for follow-up
questions. `RESEARCH_PROVIDER` sets the default (`openai`, `anthropic`, `local` or `auto`); if
the preferred one isn't configured, the first configured provider is used. Unconfigured
providers are disabled in the selector.

Run `alembic upgrade head` from `backend` and restart both the API and research
worker after configuration changes. Both processes need the selected provider's key.
Each queued run saves its provider and model; configuration changes do not switch an
existing run. If the chosen provider is unavailable for account-level reasons, the run
continues on the next configured model, and the steps panel under the report shows which
model handled each step and its tokens. All providers share the same read-only stock and
Treasury tools, run limits and private storage. Local models have no web search and say so
when a question needs it.

### Investment decision research

Stock/ETF research includes a read-only `investment_analysis` tool, shared by every
provider. It calculates SMA50/SMA200, 20-session MA changes, distance
from each average, and the latest crossover. Three fixed strategies are compared:
buy-and-hold, price above SMA200, and SMA50 above SMA200. The report shows sampled
price/equity/drawdown charts and full-resolution return, annualized return, maximum
drawdown, volatility, one-way trade count, and exposure metrics.

The engine requests up to ten years of evaluation history plus 200 warm-up observations.
Signals execute at the following session's close. Fees plus slippage are 10 basis points
per entry/exit, cash earns zero, and adjusted prices approximate dividend reinvestment.
Open positions are marked to market, without a forced exit. No taxes or market impact
are modeled. Earlier 70% and recent 30% evaluations appear when each has at least 252
observations; rules are never optimized, and these are not independently unseen tests.
Insufficient/invalid data is unavailable; stale, gapped, and short history is flagged.
These are historical simulations on selected tickers, not forecasts.

All providers read the same editable instructions from
`backend/service/research/prompt.md`. Restart research workers after editing.
The prompt requests valuation with verified reporting dates and a bull/base/bear
scenario table, using a disclosed 12-month horizon unless the user supplies one.
Unsourced price targets or probabilities are prohibited; qualitative scenarios are
used when numerical assumptions cannot be substantiated. Current Yahoo fundamentals
must not be used as historical backtest inputs.

Chart data persists within existing research evidence JSON; no new migration is
needed for this analysis upgrade. Existing reports remain readable; start a new turn
to request the expanded analysis.
