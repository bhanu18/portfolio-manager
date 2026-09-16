# Portfolio Dashboard

Multi-currency stock/crypto portfolio tracker — FastAPI backend + React/TypeScript frontend in one repo.

```
portfolio_dashboard/
├── backend/          FastAPI + SQLAlchemy (async MySQL), Alembic
├── frontend/         Vite + React 18 + TypeScript, React Query, axios
├── docs/
│   ├── backend/      reports, scoring, permissions & roles
│   └── frontend/     build context, changes, scoring UI guide, wireframes
└── CLAUDE.md
```

## Run locally

**Backend** (http://localhost:8000, docs at `/docs`)

Requires **Python 3.12** (pinned in `backend/.python-version`). Python 3.14 will fail to build `pydantic_core` / `watchfiles`.
```bash
cd backend
uv venv venv --python 3.12 && source venv/bin/activate   # or: python3.12 -m venv venv
uv pip install -r requirements-dev.txt   # or pip install; runtime + test deps
cp .env.example .env   # fill in DB + SECRET_KEY + SMTP
alembic upgrade head   # migrations are NOT run on app start
uvicorn main:app --reload
```

**Frontend** (http://localhost:5173)
```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_BASE_URL=http://localhost:8000
npm run dev
```

## Tests / checks
```bash
cd backend && pytest
cd frontend && npm run typecheck
```

## Docker (backend)
```bash
cd backend
docker build -t portfolio-api .
docker run --env-file .env portfolio-api alembic upgrade head
docker run --env-file .env -p 8000:8000 portfolio-api
```
Health check: `GET /health`. No hosting/deploy pipeline is set up yet.

Allowed frontend origins are set with `CORS_ORIGINS` (comma-separated) in `backend/.env`.
