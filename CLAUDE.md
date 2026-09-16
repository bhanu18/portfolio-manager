# CLAUDE.md — Portfolio Dashboard

Monorepo created 2026-09-16 by merging two projects:
- `backend/`  ← was `portfolio_tracker` (git history preserved; this repo's history is that repo's, remote `github.com/bhanu18/portfolio_tracker`)
- `frontend/` ← was `portfolio_manager` (no prior git history)
Originals still exist at `~/Documents/projects/portfolio_tracker` and `portfolio_manager` as backups.

## Stack
- **Backend:** Python 3.10, FastAPI, async SQLAlchemy (aiomysql / Cloud SQL MySQL), Alembic migrations, JWT auth (OAuth2 password flow, roles `user`/`admin`, scoped group roles), yfinance + forex-python for prices/FX, SMTP email, slowapi rate limits. No deployment configured (old Cloud Run/Docker/Cloud Build files removed 2026-09-16 — starting fresh).
- **Frontend:** Vite 5 + React 18 + TypeScript, react-router v6, @tanstack/react-query v5, axios. No UI lib — plain CSS in `src/styles/index.css`.

## Layout
- `backend/main.py` — app, CORS origins, router registration, migrations on startup
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
- Backend dev: `cd backend && source venv/bin/activate && uvicorn main:app --reload`
- Backend tests: `cd backend && pytest`
- New migration: `cd backend && alembic revision --autogenerate -m "..." && alembic upgrade head`
- Frontend dev: `cd frontend && npm run dev` (port 5173, strictPort)
- Frontend typecheck/build: `npm run typecheck` / `npm run build`

## Conventions & gotchas
- When changing a backend response model, update `frontend/src/types/index.ts` and the matching `frontend/src/api/*.ts` in the same change.
- Login is form-encoded (`username`=email), not JSON.
- `/assets/{symbol}` and `/assets/{asset_id}` share a path shape — frontend uses numeric IDs.
- CORS: allowed origins are hardcoded in `backend/main.py` (localhost:5173 + paulbespokesuits.com).
- Deployment: none yet. Removed Dockerfile, .dockerignore, deploy.sh, cloudbuild.yaml, DEPLOY_README.md, GITHUB_DEPLOYMENT.md (recoverable from git history). `backend/main.py` still runs Alembic migrations on startup when DATABASE_URL is set.
- Never commit `.env` files (root `.gitignore` covers backend + frontend).
- `venv/` and `node_modules/` are not copied — recreate after cloning.

## Direction (decided 2026-09-16)
- Goal: **portfolio showcase** (public repo for job hunting) — polish, CI and a clean README matter.
- Hosting: undecided, **local first**. DB: MySQL for now, Postgres possible once hosting is chosen — avoid MySQL-only SQL.
- Next up, in order: (1) backend cleanup, (2) code quality + CI. Plan is in the chat; nothing built yet.
