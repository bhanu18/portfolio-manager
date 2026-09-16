# CLAUDE.md — Portfolio Dashboard

Monorepo created 2026-09-16 by merging two projects:
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
- Backend tests: `cd backend && pytest`
- New migration: `cd backend && alembic revision --autogenerate -m "..." && alembic upgrade head`
- Frontend dev: `cd frontend && npm run dev` (port 5173, strictPort)
- Frontend typecheck/build: `npm run typecheck` / `npm run build`

## Conventions & gotchas
- When changing a backend response model, update `frontend/src/types/index.ts` and the matching `frontend/src/api/*.ts` in the same change.
- Login is form-encoded (`username`=email), not JSON.
- `/assets/{symbol}` and `/assets/{asset_id}` share a path shape — frontend uses numeric IDs.
- CORS: set `CORS_ORIGINS` in `backend/.env` (default `http://localhost:5173`).
- Deployment: only `backend/Dockerfile` + `.dockerignore`. No CI/CD yet.
- Use `lifespan` in main.py, not `@app.on_event`. New settings go in `core/config.py` AND `.env.example`.
- Never commit `.env` files (root `.gitignore` covers backend + frontend).
- `venv/` and `node_modules/` are not copied — recreate after cloning.

## Direction (decided 2026-09-16)
- Goal: **portfolio showcase** (public repo for job hunting) — polish, CI and a clean README matter.
- Hosting: undecided, **local first**. DB: MySQL for now, Postgres possible once hosting is chosen — avoid MySQL-only SQL.
- Phase 1 (backend cleanup) DONE 2026-09-16.
- Phase 2 next: ruff + mypy (backend), ESLint + Prettier (frontend; `npm run lint` currently just runs tsc), pre-commit, GitHub Actions (backend job with MySQL service container; frontend lint/typecheck/build), showcase README (badges, screenshots, architecture diagram).
- Later: tests for trades/reports (only test_auth.py exists); `tests/conftest.py` uses deprecated custom event_loop fixture.
