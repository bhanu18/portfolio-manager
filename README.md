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

## Deploy
Not set up yet — deployment config was removed on 2026-09-16 to start fresh.

Note: the frontend origin must be listed in `origins` in `backend/main.py` (CORS).
