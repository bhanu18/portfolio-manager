# Portfolio Tracker — Frontend

A TypeScript single-page app for the **Portfolio Management API** (FastAPI). It
covers v1 scope: authentication, assets CRUD, and trades CRUD (scoped by group).

Built with **Vite + React + TypeScript**, **React Router**, **TanStack Query**,
and **axios**. No CSS framework — styling is a small hand-rolled design system
in `src/styles/index.css`.

## Requirements

- Node.js 18+ (developed against Node 22)
- The Portfolio Management API running and reachable (default `http://localhost:8000`)

## Getting started

```bash
# 1. Install dependencies
npm install

# 2. Configure the API base URL
cp .env.example .env.local
# then edit .env.local if your backend isn't on http://localhost:8000

# 3. Start the dev server (http://localhost:5173)
npm run dev
```

### Available scripts

| Script              | Description                                  |
| ------------------- | -------------------------------------------- |
| `npm run dev`       | Start the Vite dev server on port **5173**   |
| `npm run build`     | Type-check (strict) and build for production |
| `npm run typecheck` | Run the TypeScript compiler with no emit     |
| `npm run preview`   | Preview the production build locally         |

## Configuration

The frontend reads a single environment variable:

| Variable            | Default                 | Description                                          |
| ------------------- | ----------------------- | ---------------------------------------------------- |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Base URL of the FastAPI backend (no trailing slash). |

Vite only exposes variables prefixed with `VITE_`. Put local overrides in
`.env.local` (git-ignored). See `.env.example` for the documented variable.

## Backend expectations / CORS

This app talks directly to the FastAPI backend from the browser, so the backend
must allow this origin via CORS.

- The dev server runs on **`http://localhost:5173`**, which the backend already
  allow-lists — so **no backend change is needed** for local development.
- If you change the dev port (e.g. via `vite --port`), you **must** add that new
  origin to the backend's CORS allow-list, or requests will fail.
- The API uses the OAuth2 password flow and returns a **JWT in the JSON body**
  (it does not set a cookie). The token is stored in `localStorage` and attached
  as `Authorization: Bearer <token>` on every authenticated request.

## How auth works here

- `POST /login/access-token` is **form-encoded** (`username` = email,
  `password`) — handled in `src/api/auth.ts`.
- The token is persisted (`src/lib/token.ts`) and injected by an axios request
  interceptor (`src/lib/apiClient.ts`).
- A `401` anywhere clears the token and redirects to `/login`. A `403` is shown
  inline as a permission error (no redirect).
- `429` (rate limit) is surfaced as a distinct "too many attempts" message.
- Admin-only actions (asset create/edit/delete, full asset list) are hidden for
  non-admin users and fail gracefully if attempted.

## Project structure

```
src/
  api/          Typed API modules, one per resource (auth, assets, trades)
  components/   Reusable UI (Layout, Navbar, Modal, ConfirmDialog, guards, …)
  context/      Global providers (AuthContext, ToastContext)
  lib/          apiClient (axios), token storage, error parsing, validation,
                formatting helpers
  pages/        Route-level screens (Login, Register, Assets, Trades, …)
  styles/       Global stylesheet / design tokens
  types/        Shared domain interfaces mirroring API response shapes
```

## Implemented v1 features

- **Auth**: register, login, logout, forgot password, reset password (token via
  `?token=` URL param or manual entry), change password, profile + groups view.
- **Assets**: admin list with create / edit / delete, "Refresh prices" bulk
  action with a result summary, symbol search, and an asset detail view that
  also lists that asset's trades.
- **Trades**: group selector (sourced from the user's `groups` on their
  profile), list trades in a group, and create / edit / delete with client-side
  validation. Trade creation sends `symbol` as a **query param** alongside the
  JSON body, per the API contract.

## Out of scope (per the build brief)

Groups admin, reports/analytics dashboards, and email-sending UI are intentionally
not built in v1.

## Notes on backend quirks handled

- `GET /assets/{symbol}` can return `{ "error": "Asset not found" }` with a
  200-style response; the symbol lookup checks the body, not just the status.
- `GET /trades/symbol/{symbol}` returns `404` (not an empty array) when there are
  no trades — the asset detail page treats that as "no trades yet".
- `GET /assets/` and asset mutations are admin-only; the UI gates these by role.
- `PATCH /assets/{id}` requires `type` even on partial updates; the edit form
  always sends it.
