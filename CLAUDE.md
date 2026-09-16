# CLAUDE.md — Portfolio Manager

Monorepo created 2026-09-16 by merging two projects (folder was `portfolio_dashboard`, renamed to `portfolio-manager` the same day):
- `backend/`  ← was `portfolio_tracker` (git history preserved; this repo's history is that repo's, remote `github.com/bhanu18/portfolio_tracker`)
- `frontend/` ← was `portfolio_manager` (no prior git history)
Originals still exist at `~/Documents/projects/portfolio_tracker` and `portfolio_manager` as backups.

## Stack
- **Backend:** Python 3.12 (pinned: `backend/.python-version`, Dockerfile `python:3.12-slim`; 3.14 breaks pydantic_core/watchfiles wheels — upgrade deps before moving past 3.12), FastAPI, async SQLAlchemy (aiomysql / Cloud SQL MySQL), Alembic migrations, JWT auth (OAuth2 password flow, roles `user`/`admin`, scoped group roles), yfinance + forex-python for prices/FX, SMTP email, slowapi rate limits. Dockerfile kept; no hosting/deploy pipeline (Cloud Run/Cloud Build scripts removed 2026-09-16).
- **Frontend:** Vite 5 + React 18 + TypeScript, react-router v6, @tanstack/react-query v5, axios. No UI lib — plain CSS in `src/styles/index.css`.

## Layout
- `backend/main.py` — app, lifespan, CORS (from settings), routers, `/` and `/health`
- `backend/core/config.py` — pydantic-settings; `CORS_ORIGINS` comma-separated, `TEST_DATABASE_URL` optional, `DB_ECHO`
- `backend/scripts/` — one-off import scripts (`import_csv.py <file>`, `import_portfolio_history.py`)
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
- New migration: `cd backend && alembic revision --autogenerate -m "..." && alembic upgrade head`
- Frontend dev: `cd frontend && npm run dev` (port 5173, strictPort)
- Frontend checks: `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run build`
- Pre-commit: `pre-commit install` at repo root (ruff + prettier + eslint + whitespace hooks)

## Conventions & gotchas
- When changing a backend response model, update `frontend/src/types/index.ts` and the matching `frontend/src/api/*.ts` in the same change.
- Login is form-encoded (`username`=email), not JSON.
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
  - `scripts/import_portfolio_history.py` needs openpyxl, which is not in requirements.
  - Badge URLs point at github.com/bhanu18/portfolio_tracker — update if the repo is renamed.
