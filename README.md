# Portfolio Dashboard

Multi-currency stock/crypto portfolio tracker — FastAPI backend + React/TypeScript frontend in one repo.

```
portfolio_dashboard/
├── backend/          FastAPI + SQLAlchemy (async MySQL), Alembic, Docker → Cloud Run
├── frontend/         Vite + React 18 + TypeScript, React Query, axios
├── docs/
│   ├── backend/      reports, scoring, permissions & roles
│   └── frontend/     build context, changes, scoring UI guide, wireframes
├── cloudbuild.yaml   Cloud Build → Cloud Run (builds backend/)
└── CLAUDE.md
```

## Run locally

**Backend** (http://localhost:8000, docs at `/docs`)
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in DB + SECRET_KEY + SMTP
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

## Deploy (backend)
- CI: `cloudbuild.yaml` at repo root (build context `backend/`).
- Manual: `./backend/deploy.sh <GCP_PROJECT_ID>`.
- Frontend origin must be listed in `origins` in `backend/main.py` (CORS).
