# CLAUDE.md — Portfolio Manager

Monorepo created 2026-09-16 by merging two projects (folder was `portfolio_dashboard`, renamed to `portfolio-manager` the same day):
- `backend/`  ← was `portfolio_tracker` (git history preserved; this repo's history is that repo's, remote `github.com/bhanu18/portfolio-manager`)
- `frontend/` ← was `portfolio_manager` (no prior git history)
Originals still exist at `~/Documents/projects/portfolio_tracker` and `portfolio_manager` as backups.

## Stack
- **Backend:** Python 3.12 (pinned: `backend/.python-version`, Dockerfile `python:3.12-slim`; 3.14 breaks pydantic_core/watchfiles wheels — upgrade deps before moving past 3.12), FastAPI, async SQLAlchemy (aiomysql / Cloud SQL MySQL), Alembic migrations, JWT auth (OAuth2 password flow, roles `user`/`admin`, scoped group roles), yfinance + forex-python for prices/FX, SMTP email, slowapi rate limits. Dockerfile kept; no hosting/deploy pipeline (Cloud Run/Cloud Build scripts removed 2026-09-16).
- **Frontend:** Vite 5 + React 18 + TypeScript, react-router v6, @tanstack/react-query v5, axios. No UI lib — plain CSS in `src/styles/index.css`.

## Layout
- `backend/main.py` — app, lifespan, CORS (from settings), routers, `/` and `/health`
- `backend/core/config.py` — pydantic-settings; `CORS_ORIGINS` comma-separated, `TEST_DATABASE_URL` optional, `DB_ECHO`
- `backend/routers/` — auth, assets, trades, group, reports, email
- `backend/models/` — Pydantic schemas; `backend/db/orm_models.py` — ORM
- `backend/service/` — security (JWT/bcrypt), email
- `backend/alembic/versions/` — migrations
- `frontend/src/api/` — one client per backend router (assets, auth, groups, reports, trades)
- `frontend/src/lib/apiClient.ts` — axios instance; base URL from `VITE_API_BASE_URL` (default `http://localhost:8000`)
- `frontend/src/pages/` — Assets, Trades, Groups, Portfolio, Performance, Valuation, Reports, auth pages
- `frontend/src/types/index.ts` — shared TS types; keep in sync with backend Pydantic models
- `docs/backend/`, `docs/frontend/` — feature specs (performance scoring, FX reports, permissions)

## Commands
- Backend setup: `uv venv venv --python 3.12 && uv pip install -r requirements-dev.txt` (runtime deps only in `requirements.txt`)
- Migrate: `cd backend && alembic upgrade head` — NOT run on startup
- Backend dev: `cd backend && source venv/bin/activate && uvicorn main:app --reload`
- Docker: `docker build -t portfolio-api backend && docker run --env-file backend/.env -p 8000:8000 portfolio-api`
- Backend checks (run in `backend/`): `ruff check .`, `ruff format .`, `mypy` (files list in pyproject), `pytest` (needs `TEST_DATABASE_URL`, a disposable MySQL DB)
- Research evals (in `backend/`): `venv/bin/python -m evals.run_research routing --rules-only` (free); `full --market offline --limit 5` calls paid models
- New migration: `cd backend && alembic revision --autogenerate -m "..." && alembic upgrade head`
- Frontend dev: `cd frontend && npm run dev` (port 5173, strictPort)
- Frontend checks: `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run build`
- Pre-commit: `pre-commit install` at repo root (ruff + prettier + eslint + whitespace hooks)

## Conventions & gotchas
- When changing a backend response model, update `frontend/src/types/index.ts` and the matching `frontend/src/api/*.ts` in the same change.
- Login is form-encoded (`username`=email), not JSON.
- `backend/scripts/` (CLI importers) removed 2026-10-02. `service/imports/` is now called by `POST /trades/import` (Yahoo parser fast path; otherwise a local model maps columns → `MappedParser`). All uploads use ref prefix `csv` so re-imports dedupe across both paths. 2B models (gemma-4-e2b) echo cell values instead of column names; use a 4B+ model via `IMPORT_LLM_MODEL`.
- MySQL 8 defaults to `caching_sha2_password`; aiomysql needs `cryptography` installed or login fails with a 500 at connect time.
- `/assets/{symbol}` and `/assets/{asset_id}` share a path shape — frontend uses numeric IDs.
- CORS: set `CORS_ORIGINS` in `backend/.env` (default `http://localhost:5173`).
- Deployment: only `backend/Dockerfile` + `.dockerignore`. CI (`.github/workflows/ci.yml`) runs lint/types/tests/build; no CD.
- Run ruff from `backend/` (config in `backend/pyproject.toml`). Local `alembic/` dir shadows the package for isort, hence `known-third-party = ["alembic"]`.
- mypy: `db/orm_models.py` + `db/service.py` have error codes disabled (legacy `Column()` models). Migrating to `Mapped[]` lets those overrides go.
- ESLint: `react-hooks/set-state-in-effect` is a warning (AssetFormModal, TradeFormModal reset form state in effects) — fix with key-based remount, then make it an error.
- Tests: `tests/test_reports.py` fakes every `_blocking_*` lookup + `calculate_performance_scores` via the `market` fixture — no network in tests. After `expire_all()` (e.g. `member_headers`), read ORM attributes only via `await db_session.refresh(obj)` or ids captured beforehand, or you get MissingGreenlet. `tests/conftest.py` uses httpx AsyncClient + savepoint rollback; wipes the test DB by reflect+drop (Alembic downgrade of `b46451958cb3` is broken: unnamed FK). slowapi limiters are disabled in tests.
- Root `.gitignore` is the Python template; its `lib/` rule once hid `frontend/src/lib` — anchor new generic rules to `backend/`.
- Use `lifespan` in main.py, not `@app.on_event`. New settings go in `core/config.py` AND `.env.example`.
- Never commit `.env` files (root `.gitignore` covers backend + frontend).
- `venv/` and `node_modules/` are not copied — recreate after cloning.
- `Group.members` is a `hybrid_property`: never `selectinload` it — load `Group.member_associations` → `UserGroupAssociation.user` (as `get_group_by_id` / `get_trade_by_id` do).
- Portfolio performance cost basis is true FIFO (sells consume the earliest buys), fixed 2026-10-15; it previously kept the earliest lots and understated cost.

## Research service (LLM orchestration)
- Public docs: README "Research desk" (How it works, Evaluation, provider selection; updated 2026-10-15). Keep it in sync when research behaviour changes.
- Lives in `backend/service/research/`; runs in a separate worker process (`python -m service.research.worker`) that claims queued `research_runs` rows. Fuller notes: `context.md`; migration history and design: `docs/backend/research_langchain_migration.md`.
- **Providers** (`orchestrator.AGENTS`): all three run on LangChain, in `langchain_agent.py`: `LangChainAnthropicAgent`, `LangChainOpenAIAgent` (Responses API, `store=False`, encrypted reasoning round-trips) and `LangChainLocalAgent` = `create_agent` + `BudgetMiddleware` + `ModelCallLimitMiddleware`. `agent.py` keeps only shared `ResearchAgent` state (budgets, evidence, citations, `checkpoint` progress), `TOOLS` descriptions and `market_tool`; `ResearchAgent.run` is abstract. No httpx provider loops remain.
- `BudgetMiddleware` = the research rules: per-call tools (web search `max_uses` = remaining budget), per-call output cap, context byte bound, tool budget counting server + client calls once, sources from `server_tool_result` (Anthropic: a list; OpenAI: `{"sources": [...]}`, title falls back to the URL), safe "Unsupported" JSON for bad tool calls, Anthropic `pause_turn` continuation (`aafter_model` jumps to `model`). Per-provider hooks: `call_settings(max_tokens, tool_budget)`, `check_response`, `finished`, `failure`, `clean`, `empty_report`, `drafting_stage`, `citation_markers` (Anthropic appends ` [Source N]` markers; OpenAI keeps its own text spans, offset across text blocks).
- `models.py` `chat_model()`: `max_retries=0` (failover owns retries), `output_version="v1"`. OpenAI: the default cap is set via `model_kwargs={"max_output_tokens": n}` because LangChain renames a model-level `max_tokens`/`max_completion_tokens` after merging per-call settings, which would override the per-call cap; per call it sends `max_output_tokens` + `max_tool_calls`; the system prompt goes as the first input message, not `instructions`. Local: `max_tokens` + thinking flag go in `extra_body`; the `StringifyToolArguments` transport re-encodes object-valued tool `arguments`; a missing key sends `Bearer unused`. A missing cloud key raises `ProviderUnavailable` with an 1800 s cooldown.
- `errors.py`: `classify_failure` (one cooldown table), `provider_failure` (OpenAI/Anthropic SDK errors; re-raises non-provider errors), `local_failure` (404 → "ollama pull", unreachable, timeout, 5xx). `http_failure`, `execute_tool`/`run_tool` and the httpx loops were removed 2026-10-15.
- `local_agent.py`: `NO_WEB`, `strip_thinking`, `local_json` (ChatOpenAI JSON mode, never raises; used by Auto's classifier, trade-import column mapping and the eval judge).
- **Auto** (`ResearchOrchestrator.graph()`): LangGraph `StateGraph` `classify → (gather market data ∥ web research) → writer`; data and web run in the same superstep, writer after both. Node names = LangSmith span names. Failover, tiers and cooldowns (`COOLDOWNS`, `candidates`) are our code. `FailoverResearchAgent` (explicit provider) is plain code, not a graph. Keep `research_runs.steps` shape (frontend renders it).
- **Tracing**: `tracing.py` applies `LANGSMITH_*` via `langsmith.configure` in the worker; off unless `LANGSMITH_TRACING=true` and a key. Tree: `research` → `auto research` (graph) → nodes → `<role>: <provider>` (chain for LangChain providers, `llm` for httpx ones, so tokens count once) → LangChain LLM/tool runs.
- **Evals**: `backend/evals/` (README there). Dataset: 54 routing examples (14 `holdout-*` added 2026-10-15 to check that the router fixes generalise; untuned they scored kind 0.714). Rules-only routing is 1.0 on all 54 after the fixes. The fixes: tickers can't touch `/ - & '` (P/E, T-bill, S&P), more NOT_TICKERS acronyms, `COMPANY_TICKERS` + `KNOWN_LOWER`, `FRESH` words need the web only without a ticker/Treasury topic, Treasury topic inherited by follow-ups, T-note/T-bond. When changing rules, add fresh examples, not just fixes. LangSmith upload is untested (cloud sessions block `api.smith.langchain.com`).
- **Tests**: the LangChain agents run the real ChatAnthropic/ChatOpenAI against `httpx2.MockTransport`: patch `langchain_anthropic.chat_models._get_default_async_httpx_client` / `langchain_openai.chat_models.base._get_default_async_httpx_client` (signature `(base_url, timeout, socket_options)`; build the client without `base_url` because it can be None); for local, patch `models.local_transport`. **Mock responses need unique ids**: LangGraph merges messages that share an id, so reusing one silently drops the tool-call turn. SDK exceptions need `httpx2` objects. `test_orchestrator.py` swaps `AGENTS` with `FakeAgent`; conftest clears `COOLDOWNS` per test. 298 passed + 2 skipped (recorded-fixture replays for Anthropic and OpenAI; record with `python -m evals.record_fixture anthropic|openai`).
- **Built 2026-10-15, NOT yet verified against real models** (no keys in cloud). The user has only an Anthropic key and no local model API yet. To do on a local machine: Anthropic baseline on commit `ee3a64b` (pre-LangChain) vs current with `full --market offline --provider anthropic|auto` (`RESEARCH_TIER_CHEAP=anthropic:claude-haiku-5-5`; the router fixes also change Auto), record fixtures, a UI smoke test, Ollama runs once set up, and OpenAI (fixture + parity) once a key exists. Everything is on PR https://github.com/bhanu18/portfolio-manager/pull/12 (branch `claude/tender-feynman-d45c4h`).
- Deps: `langsmith==0.14.8` pulls `httpx2` (forced `idna==3.20`, `anyio==4.15.1`, `typing_extensions==4.16.0`); langchain 1.4.6, langchain-core 1.6.10, langchain-openai 1.7.2, langchain-anthropic 1.7.6, langgraph 1.2.15, openai 3.31, anthropic 1.14.

## Cloud sessions (Claude Code on the web)
- `.claude/settings.json` runs `scripts/cloud_setup.sh` on SessionStart (`startup|resume`, 600s timeout). The script exits immediately unless `CLAUDE_CODE_REMOTE=true`, so it no-ops locally.
- Cloud VMs have PostgreSQL but **no MySQL** until the hook starts MariaDB (`service mariadb start`, fallback `mysqld_safe`). It creates `portfolio` + `portfolio_test` and a throwaway `ci`/`ci` user (same as CI), installs deps, and runs `alembic upgrade head`.
- No `backend/.env` in the cloud: the hook exports `DATABASE_URL`, `SYNC_DATABASE_URL`, `TEST_DATABASE_URL`, `SECRET_KEY` via `$CLAUDE_ENV_FILE` (skipped if a `.env` exists). Use `venv/bin/<tool>` in `backend/`.
- Python must be **3.12** (`uv venv venv --python 3.12`); the VM default is 3.13 and 3.14 breaks pydantic_core and watchfiles wheels.
- yfinance needs the Yahoo domains (`*.finance.yahoo.com`, `fc.yahoo.com`) on the environment's network allowlist. A 429 from Yahoo is their rate limit, not the proxy. Tests don't hit Yahoo.
- Verified 2026-10-15 on MariaDB: ruff, ruff format, mypy, pytest (298 passed, 2 skipped); frontend lint (2 known warnings), format:check, typecheck, build.

## Direction (decided 2026-09-16)
- Goal: **portfolio showcase** (public repo for job hunting) — polish, CI and a clean README matter.
- Hosting: undecided, **local first**. DB: MySQL for now, Postgres possible once hosting is chosen — avoid MySQL-only SQL.
- Phase 1 (backend cleanup) DONE 2026-09-16.
- Phase 2 (ruff, mypy, ESLint, Prettier, pre-commit, GitHub Actions, showcase README) DONE 2026-09-16. Not pushed yet; CI verified locally only (MariaDB, not MySQL 8.4).
- Known gaps / backlog:
  - Frontend PerformancePage expects `portfolio_score` / per-holding `score` (see docs/backend/portfolio_performance_scoring.md) but the backend does NOT implement scoring yet.
  - `total_dividends_base` in reports is never calculated (always 0).
  - Groups router has no tests yet (auth, trades CRUD + import, reports, research, scoring are covered).
  - README screenshots placeholder (docs/screenshots/).
  - Alembic downgrade of b46451958cb3 fails; `datetime.utcnow()` (DTZ003 ignored) and `(str, Enum)` (UP042 ignored) to revisit.
  - GitHub repo is bhanu18/portfolio-manager (renamed from portfolio_tracker); origin and badges updated.
