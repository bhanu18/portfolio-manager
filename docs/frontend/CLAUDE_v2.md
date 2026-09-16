# Portfolio Tracker Frontend — v2 Build Context

## Prerequisites
This is a continuation of v1. v1 delivered:
- Authentication (login, register, forgot/reset password, change password, profile)
- Assets CRUD (list, create, edit, delete, refresh prices)
- Trades CRUD (list by group, create, edit, delete)

v2 adds:
1. **Groups & Member Management**
2. **Reports** (single-asset valuation + full portfolio performance)

Do not re-build v1 screens. Extend the existing router, API client modules, and shared components.

---

## 1. Groups & Member Management

### Endpoint reference

All under `/groups` prefix. Auth required on all.

#### Create Group
```
POST /groups/
```
- Access: **global admin only** (`role === "admin"`)
- Body: `{ name: string }`
- Returns 201 + `Group`

#### Get Group Detail (with members)
```
GET /groups/{group_id}
```
- Access: **group members only** (403 if not a member)
- Returns `GroupWithMembers`

#### Add or Update a Member's Role
```
POST /groups/{group_id}/members/{user_id}?role={role}
```
- Access: **group admin** (the user whose `UserGroupAssociation.role === "group_admin"` for this group — NOT global admin role)
- `role` is a **query param**, not body: `GroupMemberRole` enum → `"member"` or `"group_admin"`
- Returns updated `GroupWithMembers`
- Behaviour: idempotent — if user is already a member, updates their role

#### Remove a Member
```
DELETE /groups/{group_id}/members/{user_id}
```
- Access: **global admin only**
- Returns updated `GroupWithMembers`

#### Delete Group
```
DELETE /groups/{group_id}
```
- Access: **global admin only**
- Returns 204 on success
- Returns 400 if group still has members — surface this message to user

#### Update Group (STUB — DO NOT FULLY IMPLEMENT)
```
PUT /groups/{group_id}
```
- This endpoint currently returns `None` (backend stub, not yet implemented)
- Build the UI as a disabled edit form with a message: *"Group renaming is coming soon"*
- Show the form fields pre-filled but all inputs `disabled`
- Do **not** send the API request

### TypeScript interfaces

```ts
interface Group {
  id: number;
  name: string;
}

interface UserInGroup {
  id: number;
  name: string;
  email: string;
}

interface GroupWithMembers extends Group {
  members: UserInGroup[];
}

type GroupMemberRole = "member" | "group_admin";
```

### Role hierarchy clarification (important for UI gating)

There are **two separate role systems** — do not conflate them:

| Role | Where stored | What it controls |
|---|---|---|
| `"admin"` / `"user"` | `User.role` (global) | Platform-wide admin actions (create group, delete group, remove any member, manage assets) |
| `"group_admin"` / `"member"` | `UserGroupAssociation.role` (per-group) | Group-scoped actions (add/update members within one group) |

The current user's global role comes from `GET /users/me` → `role`.
The current user's role within a specific group must be inferred from `GET /groups/{group_id}` → `members` list, but **the member list does not currently include the role field in the response** (it only returns `{id, name, email}`). This is a backend limitation — the `members` computed property on `Group` strips roles.

Workaround: the user's groups and group-level role are not directly exposed via the API in v1/v2. Use the following logic for gating:
- Global admin (`User.role === "admin"`) → can do all group admin actions (treat as having group_admin everywhere)
- Non-admin users → assume `"member"` role for all groups (cannot add/remove members, cannot see the member management UI)
- If the backend adds role to the member list later, this logic should be updated

### Pages / views to build

**Group List** (new page: `/groups`)
- Visible to all authenticated users
- Show only groups the current user is a member of (from `GET /users/me` → `groups`)
- Each group card/row links to Group Detail
- Global admin sees a "Create Group" button (opens modal/inline form → `POST /groups/`)
- Global admin sees a "Delete Group" button per group (with confirmation → `DELETE /groups/{group_id}`, handle 400 error "group still has members" with an inline message)

**Group Detail** (new page: `/groups/{group_id}`)
- Call `GET /groups/{group_id}` on mount
- Show group name, member list (name + email per member)
- Global admin sees:
  - "Rename Group" button → opens a disabled form (stub UI as described above)
  - "Remove Member" button per member row → `DELETE /groups/{group_id}/members/{user_id}` (with confirmation)
  - "Add Member" form: a user ID input (or email lookup if you have `GET /users` available for admin) + role selector (`member` / `group_admin`) → `POST /groups/{group_id}/members/{user_id}?role={role}`
    - Admin can use `GET /users` (admin-only endpoint) to search/select a user by email for the add-member flow
  - "Change Role" per member → same `POST /groups/{group_id}/members/{user_id}?role={new_role}` (it's idempotent/upsert)
- Non-admin users see: member list read-only, no management controls
- Quick link to "View Trades for this Group" → existing trades list filtered by `group_id`

---

## 2. Reports

### Endpoint reference

All under `/reports` prefix.

#### Single Asset Valuation
```
GET /reports/valuation/{symbol}/{target_currency}
```
- No auth guard on this endpoint (same pattern as some asset endpoints — treat it as authenticated anyway for consistency)
- Path params: `symbol` (e.g. `AAPL`), `target_currency` (e.g. `THB`, `USD`, `EUR`)
- Returns:

```ts
interface ValuationReport {
  symbol: string;
  asset_native_currency: string;
  reporting_currency: string;
  holdings: {
    quantity: number;
    average_cost_usd: number;
  };
  valuation: {
    current_value_native: number;
    current_value_usd: number;
    current_value_in_target_currency: number;
  };
  performance: {
    total_cost_in_target_currency: number;
    profit_loss_in_target_currency: number;
  };
}
```
- Error cases to handle:
  - 404: "Asset not found" or "No trades found for this asset" — show inline empty state
  - 503: FX rates unavailable — show "Exchange rate service temporarily unavailable, try again later"

#### Portfolio Performance (slow endpoint)
```
GET /reports/portfolio-performance?base_currency={currency}&benchmark_ticker={ticker}
```
- Query params (both optional, defaults: `base_currency=USD`, `benchmark_ticker=SPY`)
- This endpoint is **slow** — it fetches live prices + historical FX rates for every holding via yfinance. Expect 10–60+ seconds depending on portfolio size.
- Returns a large object — full interface below

```ts
interface PortfolioPerformanceReport {
  report_date: string;
  base_currency: string;
  exchange_rates_current: Record<string, number>;
  portfolio_summary: {
    total_cost_basis: number;
    total_current_value: number;
    total_unrealized_gain_loss: number;
    total_unrealized_gain_loss_pct: number;
    total_dividends_received: number;
    total_return_with_dividends: number;
    benchmark_ticker: string;
    benchmark_return: number;
    alpha: number;
    currency_impact_summary: {
      total_fx_gain_loss: number;
      total_fx_contribution_pct: number;
      total_local_contribution_pct: number;
    };
  };
  holdings: HoldingAnalysis[];
  by_currency: Record<string, CurrencyBreakdown>;
  by_asset_type: Record<string, AssetTypeBreakdown>;
  top_performers: { ticker: string; total_return_pct: number }[];
  bottom_performers: { ticker: string; total_return_pct: number }[];
  fx_warnings: { ticker: string; message: string }[];
}

interface HoldingAnalysis {
  ticker: string;
  asset_name: string;
  purchase_date: string | null;
  original_currency: string;
  purchase_price_original: number;
  current_price_original: number;
  quantity: number;
  fx_rate_at_purchase: number;
  fx_rate_current: number;
  cost_basis_original: number;
  cost_basis_base: number;
  current_value_original: number;
  current_value_base: number;
  unrealized_gain_loss_base: number;
  unrealized_gain_loss_pct: number;
  local_return_pct: number;
  fx_return_pct: number;
  total_return_pct: number;
  holding_period_days: number;
  is_long_term: boolean;
  annualized_return: number;
  weight_pct: number;
  asset_type: string;
}

interface CurrencyBreakdown {
  value_base: number;
  cost_basis_base: number;
  weight_pct: number;
  local_return_pct: number;
  fx_return_pct: number;
  total_return_pct: number;
}

interface AssetTypeBreakdown {
  value_base: number;
  cost_basis_base: number;
  weight_pct: number;
}
```

### Portfolio Performance — Background Polling UX

Since this endpoint can take 10–60+ seconds, implement a **simulated background polling** pattern:

**The endpoint is synchronous** (no real job ID from the backend). Simulate async UX as follows:

1. User lands on the Portfolio Performance page and sees a "Run Report" button with `base_currency` and `benchmark_ticker` inputs.
2. On click → immediately transition to a **progress UI** showing:
   - An animated progress bar or spinner
   - A series of rotating status messages cycling every ~3–5 seconds, e.g.:
     - *"Fetching trade history…"*
     - *"Getting live prices from Yahoo Finance…"*
     - *"Calculating historical FX rates…"*
     - *"Computing return attribution…"*
     - *"Comparing against benchmark…"*
     - *"Almost there…"*
   - Elapsed time counter (e.g. "Running… 12s")
   - A "Cancel" button — on cancel, abort the fetch (use `AbortController`) and return user to the input form
3. On response (success) → transition to the results view (see below)
4. On error (network error, 5xx, AbortError) → show an error state with a "Try Again" button that returns to the input form

**Do not use a real polling loop** (no `setInterval` hitting the endpoint repeatedly — the backend has no job-tracking for this). The fake progress messages are purely cosmetic UX.

**Cache the last result in component state** so switching away and back to the page doesn't re-run the report automatically. Show a banner: *"Showing report from [timestamp]. Run again?"*

### Pages / views to build

**Reports hub** (new page: `/reports`)
- Two sections/tabs: "Asset Valuation" and "Portfolio Performance"
- Or two sub-routes: `/reports/valuation` and `/reports/performance`

**Asset Valuation view**
- Input form: symbol text input + target currency text input (or dropdown of common currencies: USD, THB, EUR, GBP, JPY, SGD — plus a free-text fallback)
- On submit → `GET /reports/valuation/{symbol}/{target_currency}`
- Show results as a clean summary card:
  - Holdings: quantity + avg cost
  - Current value in native, USD, and target currency
  - P&L in target currency (color-coded green/red)
- Allow running multiple valuations on the same page (e.g. different currencies) without navigating away

**Portfolio Performance view**
- Input form: base currency selector + benchmark ticker input (default `SPY`)
- Progress UI as described above
- Results layout (after report loads):
  - **Summary card**: total value, total cost, unrealized P&L (%), benchmark return, alpha, FX impact
  - **Holdings table**: sortable by return %, weight, annualized return. Columns: ticker, name, quantity, cost basis, current value, unrealized gain/loss, total return %, local return %, FX return %, holding period, long-term flag
  - **Top / Bottom Performers** section: two small ranked lists
  - **By Currency** breakdown table
  - **By Asset Type** breakdown table (pie chart optional but nice)
  - **FX Warnings** section: only show if `fx_warnings.length > 0`, collapsed by default
  - Report timestamp + "Run Again" button

---

## 3. Navigation updates

Add to the main nav:
- **Groups** link → `/groups` (visible to all authenticated users)
- **Reports** link → `/reports` (visible to all authenticated users)

---

## 4. Known backend quirks (v2 additions)

- `POST /groups/{group_id}/members/{user_id}` sends `role` as a **query param**, not JSON body — e.g. `?role=member` or `?role=group_admin`. The enum values on the backend are `"MEMBER"` and `"ADMIN"` in the Python enum definition but the DB stores `"member"` and `"group_admin"` — the API accepts the lowercase string values, use those.
- `GET /groups/{group_id}` → `members` array has `{id, name, email}` only — no role field exposed. See role-gating workaround in Groups section above.
- `PUT /groups/{group_id}` is a stub — don't call it. Show a disabled form with "coming soon" messaging.
- `DELETE /groups/{group_id}` returns 400 (not 409) when the group has members. Parse `detail` from the response body and show it inline.
- Portfolio Performance report: if `fx_warnings` is present, it means some historical FX rates fell back to current-day rates. Surface these warnings to the user so they know cost basis may be slightly inaccurate.
- The `/reports/valuation` endpoint calls `forex_python` for FX rates which can be flaky. Handle 503 gracefully with a user-friendly message.

---

## 5. Non-functional requirements (carry-over from v1)

- TypeScript strict mode throughout
- Extend the existing typed API client modules (don't create parallel fetch logic)
- Loading + error states on all data-fetching views
- All new forms with client-side validation
- No backend changes — frontend only against the API as documented
