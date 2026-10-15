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
- Tests: `tests/conftest.py` uses httpx AsyncClient + savepoint rollback; wipes the test DB by reflect+drop (Alembic downgrade of `b46451958cb3` is broken: unnamed FK). slowapi limiters are disabled in tests.
- Root `.gitignore` is the Python template; its `lib/` rule once hid `frontend/src/lib` — anchor new generic rules to `backend/`.
- Use `lifespan` in main.py, not `@app.on_event`. New settings go in `core/config.py` AND `.env.example`.
- Never commit `.env` files (root `.gitignore` covers backend + frontend).
- `venv/` and `node_modules/` are not copied — recreate after cloning.

## Research service (LLM orchestration)
- Lives in `backend/service/research/`; runs in a separate worker process (`python -m service.research.worker`) that claims queued `research_runs` rows. Fuller notes: `context.md` at repo root.
- `agent.py` (OpenAI Responses API), `anthropic_agent.py` (Messages API), `local_agent.py` (OpenAI-compatible/Ollama, plus `local_json` for routing) are hand-rolled httpx tool loops sharing `ResearchAgent` (budgets, evidence, citations, `checkpoint` progress). No LLM SDK or framework is used.
- `orchestrator.py`: `ResearchOrchestrator` (Auto) = classify (local JSON + regex floor) → gather (deterministic tools, no LLM) → web (cheap tier) → writer (tier by kind), with `ProviderUnavailable` failover + per-process cooldowns. `FailoverResearchAgent` = explicit provider with failover. Per-step usage goes in `research_runs.steps` (the frontend renders it — keep that shape).
- Tests: `tests/test_orchestrator.py` swaps `AGENTS` with `FakeAgent`; `test_research_agent.py`, `test_anthropic_research.py`, `test_local_agent.py` mock httpx payloads.
- Tracing (Phase 1, done 2026-10-15): `service/research/tracing.py` applies `LANGSMITH_*` settings via `langsmith.configure` (pydantic settings, not env) in the worker's `main()`; off unless `LANGSMITH_TRACING=true` AND a key. Spans: worker `research` (chain) → `classify`/`gather market data`/`web research` (chain) → `run_agent` as `llm` runs named `<role>: <provider>` with `ls_provider`/`ls_model_name` + `usage_metadata` → tools via `execute_tool` (body is `run_tool`). `local_json` is an `llm` run. `conftest.py` calls `langsmith.configure(enabled=False)`; trace-shape test uses `tracing_context(enabled=True, client=MagicMock(spec=Client))` (the `"local"` mode still hits the network).
- Evals (Phase 2, done 2026-10-15): `backend/evals/` — see its README. `python -m evals.run_research routing|full`, dataset `evals/datasets/research.jsonl` (40 labelled examples, `id` = LangSmith sync key), evaluators in `evals/evaluators.py`, offline market fixtures in `evals/fixtures.py`. Uploads to LangSmith dataset `portfolio-research` when `LANGSMITH_API_KEY` is set, else local + `evals/results/` (gitignored). `ResearchOrchestrator.profile` exposes the routing decision for evals. Rules-only baseline: kind 0.925, symbols 0.85 (router bugs: `P/E`→E,P; `T-bill`→T; lowercase/company names missed) — left unfixed on purpose as the baseline.
- LangSmith upload path (`run_langsmith`/`aevaluate`) is untested against the real service: cloud sessions block `api.smith.langchain.com` (add it to the allowlist). `sync_dataset` is unit-tested with a mock.
- Next (not started): Phase 3 provider adapters → LangChain chat models — step-by-step plan in `docs/backend/research_langchain_migration.md` (step 0 = paid `full --market offline` baseline per provider; key gotchas: `max_retries=0`, `output_version="v1"`, switch `run_agent` span to `chain` to avoid double-counted tokens, record real citation fixtures per provider); Phase 4 Auto as a LangGraph `StateGraph`. Gate each on eval parity vs a `full --market offline` baseline (needs API keys; none in cloud sessions).
- LangChain vs LangGraph (decided 2026-10-15: option 1, both): they are layers, not rivals. `langchain` 1.4.x depends on `langgraph` (its `create_agent` runs on LangGraph); checked versions: langchain 1.4.6, langchain-core 1.6.10, langchain-openai 1.7.2, langchain-anthropic 1.7.6, langgraph 1.2.15. Recommendation: Phase 3 = LangChain chat models + `@tool` + `create_agent`, with ModelCallLimit/ToolCallLimit middleware for the provider tool loops. Keep `ProviderUnavailable`/cooldowns/tier choice as our own code; don't use ModelFallbackMiddleware. Phase 4 = LangGraph `StateGraph` for Auto, running data and web in parallel. No checkpointer: LangGraph has no MySQL saver, and `research_runs` already stores run state.
- Deps: `langsmith==0.14.8` pulls `httpx2`, which forced `idna==3.20`, `anyio==4.15.1`, `typing_extensions==4.16.0`.

## Cloud sessions (Claude Code on the web)
- `.claude/settings.json` runs `scripts/cloud_setup.sh` on SessionStart (`startup|resume`, 600s timeout). The script exits immediately unless `CLAUDE_CODE_REMOTE=true`, so it no-ops locally.
- Cloud VMs have PostgreSQL but **no MySQL** until the hook starts MariaDB (`service mariadb start`, fallback `mysqld_safe`). It creates `portfolio` + `portfolio_test` and a throwaway `ci`/`ci` user (same as CI), installs deps, and runs `alembic upgrade head`.
- No `backend/.env` in the cloud: the hook exports `DATABASE_URL`, `SYNC_DATABASE_URL`, `TEST_DATABASE_URL`, `SECRET_KEY` via `$CLAUDE_ENV_FILE` (skipped if a `.env` exists). Use `venv/bin/<tool>` in `backend/`.
- Python must be **3.12** (`uv venv venv --python 3.12`); the VM default is 3.13 and 3.14 breaks pydantic_core and watchfiles wheels.
- yfinance needs the Yahoo domains (`*.finance.yahoo.com`, `fc.yahoo.com`) on the environment's network allowlist. A 429 from Yahoo is their rate limit, not the proxy. Tests don't hit Yahoo.
- Verified 2026-10-15 on MariaDB: ruff, ruff format, mypy, pytest (196 passed); frontend lint (2 known warnings), format:check, typecheck, build.

## Direction (decided 2026-09-16)
- Goal: **portfolio showcase** (public repo for job hunting) — polish, CI and a clean README matter.
- Hosting: undecided, **local first**. DB: MySQL for now, Postgres possible once hosting is chosen — avoid MySQL-only SQL.
- Phase 1 (backend cleanup) DONE 2026-09-16.
- Phase 2 (ruff, mypy, ESLint, Prettier, pre-commit, GitHub Actions, showcase README) DONE 2026-09-16. Not pushed yet; CI verified locally only (MariaDB, not MySQL 8.4).
- Known gaps / backlog:
  - Frontend PerformancePage expects `portfolio_score` / per-holding `score` (see docs/backend/portfolio_performance_scoring.md) but the backend does NOT implement scoring yet.
  - `total_dividends_base` in reports is never calculated (always 0).
  - Tests only cover auth; add trades/reports/groups tests.
  - README screenshots placeholder (docs/screenshots/).
  - Alembic downgrade of b46451958cb3 fails; `datetime.utcnow()` (DTZ003 ignored) and `(str, Enum)` (UP042 ignored) to revisit.
  - GitHub repo is bhanu18/portfolio-manager (renamed from portfolio_tracker); origin and badges updated.
