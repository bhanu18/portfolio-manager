# Portfolio Manager — codebase context

Last reviewed: **2026-10-09**. This is a developer/agent handoff for the current working tree, including recent uncommitted features. It is not a claim that these changes are committed, deployed, or migrated in every environment. Recheck the source and Git status before making changes.

## Product and scope

Portfolio Manager is a local-first, multi-currency portfolio application for stocks, ETFs, crypto, and cash. Users record trades in shared portfolio groups, inspect holdings, and view valuation and performance reports. A separate, private Research workspace provides on-demand market research without requiring asset ownership.

The recent research direction is a smaller Bloomberg-like desk: sourced analysis, follow-up conversations, selectable OpenAI/Anthropic models, and deterministic investment-analysis tools. The user requested deeper investment analysis starting with MA50/200, three backtests, valuation, and bull/base/bear scenarios. This is implemented through shared prompting and tools, not model-weight fine-tuning.

Research covers US stocks/ETFs, Treasury rates/bills, money-market questions, and qualitative bond-issuer research. Individual-bond quotes/accounting, trade execution, alerts, scheduled research, and shared research sessions are outside its current scope.

## Architecture

```text
React/Vite browser
  -> axios REST client with Bearer JWT
  -> FastAPI routers
     -> SQLAlchemy async sessions -> MySQL
     -> portfolio/report services -> Yahoo / FX data
     -> research submission -> persistent database queue

Separate research worker
  -> atomically claims a queued run
  -> selected OpenAI or Anthropic adapter
  -> shared prompt + read-only market/calculation tools + provider web search
  -> saves progress, evidence, citations, usage and final report

Browser polls saved research while a run is active.
```

- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, async MySQL (`aiomysql`), sync migration driver (`pymysql`), httpx, pandas, yfinance, forex-python, JWT/bcrypt, SMTP, slowapi.
- Frontend: React 18, TypeScript, Vite 5, React Router 6, TanStack Query 5, axios, plain CSS. No general UI or charting library; investment charts use SVG.
- Backend API defaults to port 8000. Vite defaults to 5173 with `strictPort: true`; alternate ports require explicit configuration and matching CORS.
- MySQL is the supported database. Research uses row locking with `SKIP LOCKED` and MySQL microsecond datetime variants; database portability requires review.
- Deployment assets include `backend/Dockerfile`; CI exists, but there is no configured continuous-deployment workflow.

## Source map

| Area | Main files | Responsibility |
| --- | --- | --- |
| API entry | `backend/main.py` | Router registration, CORS, lifespan, health endpoint, request timing |
| Settings | `backend/core/config.py`, `backend/.env.example` | Server configuration and documented defaults |
| Database | `backend/db/session.py`, `backend/db/dependencies.py` | Sessions, authentication and permission dependencies |
| Portfolio models | `backend/db/orm_models.py` | Assets, trades, users, groups, memberships |
| DB helpers | `backend/db/service.py` | Portfolio persistence and batch asset lookup |
| Contracts | `backend/models/`, `frontend/src/types/index.ts` | Pydantic and TypeScript API shapes |
| Routers | `backend/routers/` | Auth, assets, trades, groups, reports, email, research |
| Reporting | `backend/routers/reports.py` | FIFO valuation, FX attribution, benchmark and performance reporting |
| Scoring | `backend/service/scoring.py`, `backend/service/currency.py` | Risk/return metrics, scores, historical FX series |
| Imports | `backend/service/imports/` | Parser registry, Yahoo parser, idempotent trade import pipeline |
| Frontend bootstrap | `frontend/src/main.tsx`, `frontend/src/App.tsx` | Providers and routing |
| HTTP/auth | `frontend/src/lib/apiClient.ts`, `frontend/src/context/AuthContext.tsx` | API client, token attachment, session restoration and logout |
| Frontend API modules | `frontend/src/api/` | Typed resource requests |
| UI | `frontend/src/pages/`, `frontend/src/components/`, `frontend/src/styles/` | Screens, reusable components, Modernist presentation |
| CI | `.github/workflows/ci.yml` | Backend and frontend checks |
| Additional context | `docs/backend/`, `docs/frontend/`, `CLAUDE.md` | Specs and historical implementation notes; verify against current code |

## Portfolio data and permissions

- `Asset` is a globally stored instrument, identified by numeric ID and unique symbol. It stores name, market, type, current price, and price-update timestamps.
- `Trade` belongs to an asset and a **group**, with buy/sell type, trade date, quantity, price, currency, and bookkeeping timestamps.
- Asset ownership is not the portfolio ownership boundary: group ownership is on trades.
- `Trade.source_ref` is a nullable unique identifier used for idempotent imports. Manual trades can leave it null.
- `User` has an active flag and global role (`user` / `admin`).
- `UserGroupAssociation` connects users and groups, with scoped roles (`member` / `group_admin`). Global admin and group admin are distinct concepts.
- Server dependencies and router checks enforce permissions. Client route guards are UX, not security boundaries. Consult `docs/backend/permissions_and_roles.md` and the relevant route before changing access behavior.
- Login uses OAuth2 form encoding: `username` contains the email address. It is not a JSON login body.
- The axios interceptor adds the stored Bearer token. A 401 clears it and dispatches `auth:unauthorized`; 403 errors remain available for pages to display.
- Registration, password change/reset, SMTP email, and sensitive-endpoint rate limits exist.

### Batch asset lookup

`POST /assets/batch` accepts `{"ids": [1, 2, 3]}` for an active signed-in user.

- Accepts 1–500 strictly positive integer IDs.
- Uses one SQL `IN` query, removes duplicates, and preserves first-requested order.
- Missing IDs are omitted. The response is an array of stored asset records, not refreshed quotes.
- Implemented in `backend/models/asset.py`, `backend/routers/assets.py`, and `backend/db/service.py`.
- `frontend/src/api/assets.ts` deduplicates and chunks larger requests into groups of 500.
- `frontend/src/api/trades.ts` uses batch lookup to fill missing asset symbols, replacing per-asset requests. Embedded symbols are retained, and lookup failure does not hide trades.

### Reporting and scoring

Portfolio reporting uses FIFO lots, historical acquisition FX, current FX/value, local-vs-FX attribution, currency/type breakdowns, and benchmarks. Scoring is implemented in `service/scoring.py` and called from reports. It includes CAGR, volatility, Sharpe/Sortino, drawdown, beta/alpha, normalized subscores and composite grades.

Research backtests are a separate implementation and do not calculate actual user portfolio performance or reuse portfolio balances. Current report dividend accounting remains incomplete: `total_dividends_base` is currently initialized to zero. Do not confuse that limitation with research simulations using distribution-adjusted history.

The import pipeline remains in the service layer and tests; the former standalone CLI scripts were removed. Do not assume an import UI/API is connected without checking current callers.

## Frontend navigation and presentation

Current route definitions live in `frontend/src/App.tsx`:

- Public-only auth: `/login`, `/register`, `/forgot-password`, `/reset-password`.
- Protected Modernist pages with their own shell: `/overview`, `/holdings/:symbol`, `/research`, `/research/:sessionId`.
- Protected pages under `Layout`: `/holdings`, `/trades`, `/profile`, `/groups/:groupId`, `/reports/valuation`, `/reports/performance`.
- Legacy redirects: `/portfolio` to `/overview`, `/assets` to `/holdings`, `/assets/:symbol` through `LegacyAssetRedirect`, `/groups` to `/profile`.
- `/` redirects to `/overview`; unmatched routes use `NotFoundPage`.

Navigation, price freshness, and trade-entry components include `ModernistNav`, `PriceFreshness`, `RecordTradeButton`, and `TradeFormModal`. Preserve the existing plain-CSS Modernist style. There are existing local edits across these screens; inspect before changing them.

## Research subsystem

### Files and roles

| File | Role |
| --- | --- |
| `backend/models/research.py` | Session/run/message contracts, evidence, citations, snapshots, analysis and chart schemas |
| `backend/db/research_models.py` | Research sessions, runs, messages and daily usage tables |
| `backend/routers/research.py` | Owner-scoped CRUD, capabilities, submission, status and cancellation |
| `backend/service/research/configuration.py` | Provider availability, defaults, and model lookup; never exposes keys |
| `backend/service/research/queue.py` | Expiry and atomic claims |
| `backend/service/research/worker.py` | Separate process, heartbeats, history, execution and fenced saves |
| `backend/service/research/agent.py` | OpenAI Responses adapter, tool definitions, shared execution and checkpoints |
| `backend/service/research/anthropic_agent.py` | Claude Messages adapter, server/client tool continuation and citations |
| `backend/service/research/prompt.md` | **Single shared editable system prompt for both providers** |
| `backend/service/research/providers.py` | Yahoo stock/ETF snapshots and official Treasury XML data |
| `backend/service/research/investment.py` | Deterministic moving averages and backtests |
| `frontend/src/api/research.ts` | Research HTTP requests |
| `frontend/src/pages/ResearchPage.tsx` | Sessions, provider selector, composer, polling, runs and evidence |
| `frontend/src/components/ResearchReport.tsx` | Safe Markdown subset and inline citations |
| `frontend/src/components/InvestmentAnalysis.tsx` | Trend/equity/drawdown SVG charts and metric tables |
| `frontend/src/lib/research.ts` | Safe source URL validation |
| `frontend/src/styles/research.css` | Responsive workspace and analysis styling |

### API and persistence

Authenticated endpoints include:

- `GET /research/capabilities`
- `GET /research/sessions`, `POST /research/sessions`
- `GET`, `PATCH`, `DELETE /research/sessions/{session_id}`
- `POST /research/sessions/{session_id}/messages`
- `GET /research/runs/{run_id}`
- `POST /research/runs/{run_id}/cancel`

Submission includes `prompt`, UUID `request_id`, and optional `provider` (`openai` / `anthropic`). It returns a queued run immediately (202), including the run ID. The frontend preserves the request ID across transport failures. Reusing it for a different prompt or explicit provider produces a conflict.

Every session/run operation enforces ownership, including status and cancellation. Group membership does not grant access to another user's research. User-row locking serializes submissions; limits apply across the user's sessions, and a session cannot have simultaneous turns.

Records include:

- `ResearchSession`: owner, title, creation/update timestamps.
- `ResearchRun`: owner/session, request key, prompt, provider/model, status/stage, report/error, JSON evidence/citations, token/tool/turn counts, worker lease and timestamps.
- `ResearchMessage`: session/run, role, content and timestamp.
- `ResearchDailyUsage`: user/day and start count, retained when sessions are deleted.

Run states are `queued`, `running`, `completed`, `failed`, `cancelled`. Failed and cancelled starts consume daily quota. Deleting sessions cannot reset quota. Research timestamps use microsecond precision on MySQL and serialize with explicit UTC timezone in API responses.

Migrations:

1. `a913ed042d10_add_research_desk.py`, after `2f8ad6c1b503`: research tables.
2. `b260109a6e01_add_research_provider.py`: persisted provider, with `openai` as the backfill/default for existing runs.

Investment data lives in evidence JSON through optional `MarketSnapshot.analysis`; it required no additional table migration. Older snapshots without analysis remain readable.

### Worker lifecycle

The API does not perform research inline. Run `python -m service.research.worker` as a separate process against the same database and provider configuration.

1. Expire stale queued/running jobs.
2. Atomically claim one queued job using a row lock and `SKIP LOCKED`.
3. Mark it running, assign worker ID, and establish a lease.
4. Load completed previous turns only (up to eight), including dated source context. Failed/cancelled prompts are excluded from factual history.
5. Instantiate the saved provider and model; run under the configured deadline.
6. Heartbeat renewals preserve ownership. Saves are fenced by worker ID, state and unexpired lease.
7. Persist the report or an actionable failure, keeping partial evidence.

The default heartbeat interval is one-third of the 30-second lease. Cancellation is observed by the worker and cancels in-flight async work; already accepted provider requests may still be billed. Expired/interrupted jobs fail and require explicit retry rather than automatic provider resubmission. Browser navigation/refresh does not stop a run.

### Provider behavior and prompt editing

- OpenAI: direct httpx calls to Responses API; default `gpt-5-mini`, built-in web search and read-only function tools.
- Anthropic: direct httpx calls to Messages API; default `claude-sonnet-5-5`, basic `web_search_20250305`, and the same client-side market tools. Handles `tool_use` and `pause_turn`, preserving server tool content for continuation.
- Anthropic cited text receives source markers with offsets compatible with the report renderer. OpenAI inline citation spans are retained. Citation offsets use Unicode code points.
- Provider/model are frozen when a run is queued. An explicit unavailable provider is rejected; failures never silently switch providers.
- If the preferred default provider lacks a key, capabilities choose another configured provider. If none is configured, saved reports remain readable and new research is disabled.
- The prompt is loaded from `prompt.md` at import time: **restart workers after prompt edits**. This is prompt/tool engineering, not training or fine-tuning a model.

The shared brief requests dated facts, primary sources, recent developments, valuation, trend/backtest interpretation, risks, and a bull/base/bear table. Default scenario horizon is 12 months, explicitly stated as an assumption unless the user provides another horizon. Numerical targets require sourced inputs and explained arithmetic; unsupported scenarios stay qualitative. No invented probabilities, backtests or quotes.

Research tools cannot change portfolios, execute arbitrary code, or access credentials. Only explicitly allowed tool names and arguments are dispatched. Retrieved content is untrusted evidence, not instructions. Portfolio balances are excluded; a holding's Research action passes only its ticker. Source links allow HTTP(S), reject credentials in URLs, and report HTML is escaped.

### Market tools

- `stock_snapshot(symbol)`: Yahoo quote/fundamentals, including P/E, market capitalization, cash/debt, free cash flow, growth, margin, ROE and fund expense ratio. Free-cash-flow yield is calculated for equities with usable market cap. Missing/nonfinite figures become null. Reporting periods need verification in filings.
- `treasury_snapshot(kind)`: official Treasury XML par curve or bill rates; preserves observation date, retrieval timestamp, percent units and yield definitions. Distinguishes bank-discount, coupon-equivalent, par, and fund SEC yields. Handles the New Year fallback; rejects unsafe/oversized XML.
- `investment_analysis(symbol)`: adjusted daily history, deterministic trend statistics, and three fixed backtests. Full chart data is persisted, while model tool output omits chart arrays to conserve context.

### Investment methodology — preserve these semantics

| Item | Implemented behavior |
| --- | --- |
| Data window | Up to ten years of evaluation plus 200 warm-up observations |
| Bars | Daily Yahoo closes adjusted for splits/distributions; current UTC date excluded conservatively |
| Validity | At least 201 observations; unique ascending dates and positive finite prices |
| Trend | SMA50/SMA200, price distance, 20-session MA percentage changes, latest 50/200 crossover |
| Benchmark | Buy-and-hold of the same instrument over matching dates |
| Strategy 2 | Hold when completed close is strictly above SMA200; otherwise cash |
| Strategy 3 | Hold when SMA50 is strictly above SMA200; otherwise cash |
| Execution | Signal at close t executes at close t+1; earns holding returns only after execution |
| Positioning | Long-only, fully invested or cash; no leverage |
| Costs | Fixed combined fees/slippage of 0.10% on every entry or exit (`COST` in investment.py) |
| Cash | 0% return, not a Treasury-rate cash proxy |
| Dividends | Adjusted prices approximate reinvestment; no separate cash dividend ledger |
| Ending position | Mark to market; no forced final liquidation or exit charge |
| Metrics | Total return, CAGR, maximum drawdown, annualized volatility, one-way trades, time invested |
| Annualization | CAGR uses calendar years and is null for periods under one year; volatility uses sample standard deviation and 252 sessions/year |
| Subperiods | Earlier 70% / recent 30%, only if each has at least 252 evaluation observations; each starts in cash |
| Charts | At most 160 sampled points per series; metrics use all daily observations |
| Validation meaning | Fixed rules, no parameter optimization; historical splits are not independently unseen tests |

Units for return, drawdown, exposure and volatility are fractions in API data and percentages in the UI. Adjusted prices can differ from current quote prices. Missing history is not filled or fabricated. Stale history, long gaps, limited history, revisions and selection/survivorship bias are disclosed. Taxes and market impact are excluded. Current fundamentals are not historical backtest inputs.

### Research UI behavior

The workspace has a session sidebar, central conversation/report, and sources panel that stack on mobile. It supports starter questions, provider selection, follow-ups, elapsed time/stages, cancellation, explicit retry, rename/delete, and saved-session recovery. TanStack Query polls active session detail every two seconds and scopes query keys by user ID.

The renderer supports a safe Markdown subset, comparison tables and citations. Computed analysis appears independently of model prose; partial evidence can remain visible after failures. Chart/table assumptions are accessible through methodology details. Tables scroll within their region on narrow screens.

## Configuration

Use `backend/.env.example` and `frontend/.env.example` as templates. Never copy live `.env` contents, credentials, tokens or private database URLs into documentation.

Backend requires `DATABASE_URL`, `SYNC_DATABASE_URL` and a strong `SECRET_KEY` (minimum 32 characters). Other groups include `TEST_DATABASE_URL`, `DB_ECHO`, `CORS_ORIGINS`, `FRONTEND_URL`, JWT expiry and SMTP settings. Settings load `.env` relative to the current working directory, so launch backend commands from `backend/`.

| Research setting | Default |
| --- | --- |
| `OPENAI_API_KEY` | Empty; server only |
| `RESEARCH_MODEL` | `gpt-5-mini` |
| `ANTHROPIC_API_KEY` | Empty; server only |
| `ANTHROPIC_RESEARCH_MODEL` | `claude-sonnet-5-5` |
| `RESEARCH_PROVIDER` | `openai` |
| `RESEARCH_DAILY_LIMIT` | 20 starts per user per UTC day |
| `RESEARCH_MAX_ACTIVE_PER_USER` | 1 |
| `RESEARCH_MAX_MODEL_TURNS` | 6 |
| `RESEARCH_MAX_TOOL_CALLS` | 8 |
| `RESEARCH_TIMEOUT_SECONDS` | 180 |
| `RESEARCH_MAX_INPUT_TOKENS` | 24000 |
| `RESEARCH_MAX_OUTPUT_TOKENS` | 12000 |
| `RESEARCH_LEASE_SECONDS` | 30 |
| `RESEARCH_POLL_SECONDS` | 2 |

Model requests use conservative UTF-8 byte bounds for input and record provider-reported usage. Token/tool limits are not an exact monetary spending cap. The investment cost assumption is currently a code constant, not an environment setting.

Frontend public configuration is `VITE_API_BASE_URL`, defaulting to `http://localhost:8000`. Never put provider keys in `VITE_*` variables.

## Local development and verification

Backend setup and API (from `backend/`):

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
# Create .env from .env.example and configure your own database/secrets.
python -m alembic upgrade head
python -m uvicorn main:app --reload
```

In another terminal, from `backend/`, using the same environment:

```bash
venv/bin/python -m service.research.worker
```

Frontend (from `frontend/`):

```bash
npm ci
# Create .env from .env.example if needed.
npm run dev
```

Backend checks (from `backend/`):

```bash
ruff check .
ruff format --check .
venv/bin/python -m mypy
venv/bin/python -m pytest -q
```

Frontend checks (from `frontend/`):

```bash
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
```

`npm run test:research` runs research rendering/API-contract tests only. `npm test` also includes batch-asset tests. Frontend tests use Node's test runner, transpile actual TypeScript modules, and render React components server-side without paid APIs.

**The backend test database is destructive and must be disposable.** `tests/conftest.py` reflects and drops every table before/after the integration-test session, upgrades with Alembic, and uses savepoint rollback for normal tests. Never point `TEST_DATABASE_URL` at development/production data. Avoid concurrent integration-test processes targeting the same database. Tests needing a DB are skipped if it is not configured; a green run with skips is not full integration coverage.

Tests cover auth, trades/imports/scoring, batch asset lookup, research providers, ownership/idempotency/limits, worker leases/cancellation, migration round trips, deterministic investment math, citations and rendering. Provider calls are mocked in CI. GitHub Actions uses Python 3.12, MySQL 8.4, and Node 22; it runs lint/format/types/tests and the frontend build.

In the current local environment some virtualenv console-script paths were stale; `venv/bin/python -m pytest` works reliably. Recreate the venv if needed rather than depending on machine-specific tool-cache paths.

## Dated validation and remaining limitations

Last feature validation on 2026-10-09:

- 136 backend tests passed; 11 frontend tests passed.
- Research/backend type checks and lint, frontend type checks and production build passed.
- Frontend lint had two existing warnings in `AssetFormModal` and `TradeFormModal` about synchronous state updates in effects.
- Standalone chart preview was inspected at mobile 390px and desktop 1280px, without page overflow. This was component preview verification, not a full authenticated browser regression test.
- A live public Yahoo SPY history smoke returned 2,713 observations and nine strategy/period results.
- Live Anthropic research completed with an investment-analysis snapshot. The OpenAI live smoke returned a rate/billing-limit error before tool execution; mocked OpenAI tests passed. This is a dated test result, not a statement about current account availability.
- No deployment or production migration is implied by these checks.

Known maintenance issues/context:

- Older `CLAUDE.md` backlog statements that scoring is absent or only auth tests exist are obsolete. Source code and current tests take precedence.
- Some older docs and README tables lag current routing/test commands; use this map and actual configuration.
- Legacy SQLAlchemy `Column()` models require mypy overrides for `db.orm_models`/`db.service`; new research models use `Mapped` typing.
- There is a documented historical downgrade issue around `b46451958cb3` (unnamed foreign key). The test fixture wipes the disposable schema rather than relying on a full downgrade.
- Legacy asset GET routes have the same path shape (`/{symbol}` and `/{asset_id}`); route order matters. The new batch endpoint is explicit and does not resolve that old ambiguity.
- Existing monetary portfolio fields use FLOAT; do not assume exact decimal accounting.
- Python 3.12 is pinned; dependency upgrades are needed before assuming newer Python compatibility.
- Keep the research worker running separately. Restart it after prompt/provider configuration changes. New analysis does not retroactively rewrite existing reports.

## Guidance for future changes

1. Inspect current source/Git status and preserve unrelated working-tree edits. Historical conversation state is not proof that work is committed.
2. Update Pydantic schemas, TypeScript types, API clients and tests together when changing response shapes.
3. Add server settings to both `core/config.py` and `.env.example`. Keep secrets server-side.
4. Put shared analyst behavior in `service/research/prompt.md`; keep provider wire formats in adapters and financial calculations in deterministic tools.
5. Preserve owner isolation, idempotency, quota accounting, worker fencing, partial evidence and explicit failures.
6. Preserve backtest timing and units. Add numerical tests before changing execution, dividend, fee or cash-return assumptions.
7. Keep evidence dates, source URLs, definitions and limitations alongside calculated values; never silently invent missing data.
8. Use real migrations for schema changes; startup does not migrate automatically.
9. Update this document when architecture, operational requirements or calculation semantics change. Keep dated checks distinct from persistent guarantees.
