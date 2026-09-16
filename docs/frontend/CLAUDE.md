# Portfolio Tracker — Frontend Build Context

## Goal
Build a TypeScript frontend for the existing FastAPI "Portfolio Management API" (auth-protected, multi-currency stock/crypto portfolio tracker). You choose the framework, tooling, and styling approach you judge best for a maintainable SPA — explain your choice briefly before scaffolding.

## Scope for this build (v1)
Implement **only**:
1. Authentication (register, login, logout, forgot/reset password, change password, "me" profile)
2. Assets CRUD (list, view, create, update, delete, trigger price refresh)
3. Trades CRUD (list by group, list by symbol, create, update, delete)

Do **not** build Groups management UI, Reports/analytics dashboards, or Email sending UI yet — those come later. You do still need Group selection in the Trades UI (see below), since trades are scoped to a group_id, but full group admin screens (create group, manage members) are out of scope for now.

## Backend overview

Base URL: configurable via env var (e.g. `VITE_API_BASE_URL` or `.env.local`), default `http://localhost:8000`.

Auth: OAuth2 password flow. Login returns a JWT bearer token (`access_token`, `token_type: "bearer"`). Store it (e.g. in memory + localStorage or httpOnly-cookie pattern — your call, but note this API does NOT set cookies, it returns a token in the JSON body) and attach as `Authorization: Bearer <token>` on all authenticated requests.

There are two user roles: `user` and `admin`. Some endpoints are admin-only. Build the UI to hide/disable admin-only actions for non-admin users, and handle 403 responses gracefully.

### Endpoints

**Auth** (no prefix)
- `POST /register` — body `{name, email, password}` → returns User. Rate-limited 3/hour.
- `POST /login/access-token` — form-encoded (`username`=email, `password`), NOT JSON. Returns `{access_token, token_type}`. Rate-limited 5/min.
- `GET /users/me` — current user profile (includes `groups` array). Requires auth.
- `GET /users` — admin only, list all users.
- `POST /change-password` — body `{current_password, new_password}`. Requires auth. Rate-limited 5/hour.
- `POST /forgot-password` — body `{email}`. Always returns generic success message (no enumeration). Rate-limited 3/hour.
- `POST /reset-password` — body `{token, new_password}`. Rate-limited 5/hour.

**Assets** (`/assets` prefix)
- `GET /assets/` — admin only. Query params `skip`, `limit`. Returns `Asset[]`.
- `GET /assets/{symbol}` — public-ish (no auth dependency in code, but treat consistently with rest of app), fetch by symbol string.
- `GET /assets/{asset_id}` — fetch by numeric ID. ⚠️ Note: backend has both `/assets/{symbol}` and `/assets/{asset_id}` on the same path shape (`/assets/{value}`) — route matching ambiguity exists server-side. Build the UI to primarily use whichever one the list/detail flow naturally produces (numeric ID from the list response), and treat symbol-lookup as a search feature.
- `POST /assets/create` — body `{symbol, name, market, type}` where `type` ∈ `stock|crypto|cash|etf`. Server fetches live price via yfinance on create. Returns 201 + Asset, or 400 if symbol exists / price lookup fails.
- `POST /assets/update-all-prices` — bulk refresh action, returns `{message, updated_count, skipped_count, updated_symbols, skipped_symbols}`. Good candidate for a "Refresh Prices" button with a results toast/summary.
- `PATCH /assets/{asset_id}` — admin only. Partial update body matching `AssetUpdate` (`symbol?, name?, market?, type, currency?`) — note `type` is required in the update schema even though semantically it should probably be optional; send the asset's current type if unchanged.
- `DELETE /assets/{asset_id}` — admin only. 204 on success, 400 if trades still reference it (surface this error message to the user).

Asset shape (response):
```ts
interface Asset {
  id: number;
  symbol: string;
  name: string;
  market: string;
  type: "stock" | "crypto" | "cash" | "etf";
  current_price: number | null;
  price_last_updated: string | null; // ISO datetime
  created_at: string;
  updated_at: string;
}
```

**Trades** (`/trades` prefix) — all require auth
- `GET /trades/in-group/{group_id}` — list trades for a group. Caller must be a member of that group (403 otherwise). Returns `Trade[]`.
- `GET /trades/symbol/{symbol}` — list trades for an asset by symbol. Returns `TradeResponse[]` (note: different shape — has `symbol` string instead of `asset_id`, and 404 if none found rather than empty array).
- `POST /trades/?symbol={symbol}` — create a trade. ⚠️ `symbol` is a **query param**, not body. Body is `TradeCreate`: `{trade_type: "buy"|"sell", trade_date, quantity, price_per_unit, currency, group_id}`. Caller must be a member of `group_id`.
- `PATCH /trades/{trade_id}` — partial update, body `TradeUpdate` (all fields optional). Caller must be a member of the trade's group.
- `DELETE /trades/{trade_id}` — 204 on success. Caller must be a member of the trade's group.

Trade shape (response, from `GET /trades/in-group/{id}`):
```ts
interface Trade {
  id: number;
  asset_id: number;
  trade_type: "buy" | "sell";
  trade_date: string; // ISO datetime
  quantity: number;
  price_per_unit: number;
  currency: string;
  group_id: number;
}
```
TradeResponse shape (from `GET /trades/symbol/{symbol}`) swaps `asset_id`/`currency`/`group_id` for `symbol: string` — handle as a distinct type, don't conflate with `Trade`.

### Known backend quirks to design around
- Trades are scoped to `group_id`, and the user's group memberships come from `GET /users/me` → `groups: [{id, name}]`. The Trades UI needs a group selector (dropdown of the current user's groups) before listing/creating trades. Since Groups admin screens are out of scope, just consume the groups already returned on the user's profile — don't build group creation/editing.
- `POST /trades/` takes `symbol` as a query parameter alongside a JSON body — make sure your API client sends both correctly (e.g. `axios.post('/trades/', body, { params: { symbol } })`).
- Error responses are standard FastAPI `{"detail": "..."}` — build one shared error-parsing utility for toasts/inline errors.
- 401 → token invalid/expired: redirect to login and clear stored token. 403 → show a permission-denied message inline, don't redirect.
- Rate-limited endpoints return 429; handle this distinctly (e.g. "Too many attempts, try again later") rather than as a generic error.
- `GET /assets/{symbol}` returns a plain dict `{"error": "Asset not found"}` with a 200-looking tuple (not raising HTTPException) when not found — be defensive and check for an `error` key in the response body, not just HTTP status, when calling this specific endpoint.

## Required pages/views for v1
1. **Login** — email/password form, link to register and forgot-password.
2. **Register** — name/email/password.
3. **Forgot Password** → **Reset Password** (token from URL/query param).
4. **Profile / Change Password** — show current user info + groups, change-password form.
5. **Assets list** — table of assets (symbol, name, market, type, current price, last updated), "Refresh Prices" action, admin-only create/edit/delete.
6. **Asset detail** — single asset view, link to its trades.
7. **Trades** (scoped by selected group) — list, create, edit, delete trade forms with the fields above; asset picker should search/select existing assets by symbol.

## Non-functional requirements
- TypeScript throughout, strict mode on.
- Centralized typed API client (one module per resource: auth, assets, trades) with the request/response interfaces above.
- Global auth state (token + current user) accessible app-wide, with route guards redirecting unauthenticated users to login and gating admin-only UI by role.
- Loading and error states for every data-fetching view (don't leave blank screens on slow/failed requests).
- Form validation client-side mirroring backend constraints (e.g. password min length if any, required fields, numeric quantity/price > 0).
- `.env.example` for the frontend documenting the API base URL var.
- Brief README section on how to run dev server and how it expects the backend to be running/CORS-configured (backend currently allow-lists `http://localhost:5173` and one production domain — flag if you pick a dev port other than 5173, since CORS will need a backend-side update).

## Out of scope (do not build yet)
- Groups admin (create/delete groups, manage members/roles)
- Reports/analytics dashboard (`/reports/*` endpoints)
- Email sending UI (`/email/sendemail`)

Ask me before making any backend/API changes — this build should be frontend-only against the existing API as documented above.
