# Permission Structure — Frontend / UX Reference

This document explains the API's authorization model in detail so the
frontend can decide **what UI to show, hide, disable, or gate** for a given
user, and **what error responses to expect** when a user attempts something
they're not allowed to do.

It reflects the backend as of the "trade ownership" change (creators + group
admins can edit/delete trades).

---

## 1. The two roles you need to know about

There are **two independent role systems**. Don't confuse them — a user's
global role and their per-group role are unrelated.

### 1.1 Global role — `User.role`

Every user account has exactly one of:

| Value | Meaning |
|---|---|
| `user` | Default. A normal member of the platform. |
| `admin` | Site-wide administrator. **Bypasses almost every ownership/membership check in the system.** Can see and manage everything. |

This comes back on the user object as `role` (see `GET /users/me`).

> **UX implication:** If `role === "admin"`, treat the user as a superuser
> across the whole app — they should see all groups, all trades, all assets,
> regardless of membership. You may want a distinct "Admin" badge/mode in the
> nav.

### 1.2 Per-group role — `GroupMemberRole` (via `group_associations[].role`)

Within a specific group, a user is one of:

| Value (wire format) | Meaning |
|---|---|
| `member` | Regular member of that group. |
| `group_admin` | Admin of that **specific** group only. Does not grant any rights in other groups, and does not grant global admin. |

A user's group memberships (and their role in each) are returned as an array,
e.g. on `GET /users/me`:

```json
{
  "id": 12,
  "name": "Jane",
  "role": "user",
  "group_associations": [
    { "group_id": 3, "group_name": "Family Fund", "role": "member" },
    { "group_id": 7, "group_name": "Retirement", "role": "group_admin" }
  ]
}
```

> **UX implication:** A user can be a plain `member` of one group and
> `group_admin` of another at the same time. Any "can I edit this?" logic
> must be evaluated **per group**, not globally. Don't cache a single
> "isAdmin" boolean for the whole app based on one group.

---

## 2. How authorization actually works (for context)

Every request must include `Authorization: Bearer <token>` except for
`/`, `/docs`, `/redoc`, `/openapi.json`, `/register`, and
`/login/access-token`. Anything else with a missing/invalid/expired token
gets a blanket `401 Not authenticated` before your route logic even runs —
this is enforced globally, not per-endpoint, so **assume every screen behind
login needs a valid token or the user gets logged out.**

Beyond that, two more dependencies commonly gate routes:
- **Active check** — inactive accounts (`is_active: false`) get
  `400 Inactive user` on every authenticated call. (There's currently no
  "reactivate" self-service flow — this would need an admin.)
- **Global-admin-only routes** — some endpoints require `role === "admin"`
  outright (see tables below); anyone else gets `403 The user does not have
  sufficient privileges`.

On top of role checks, most resource endpoints do an **ownership/membership**
check specific to that resource (a trade, a group, etc.) — detailed below.

---

## 3. Resource-by-resource permission matrix

### 3.1 Trades

This is the area with the most nuanced rules — pay close attention here.

Every trade now has a `created_by_user_id` field (the user who logged it).
This is included on trade objects returned by list/create/update endpoints.

| Action | Endpoint | Who is allowed | Error if not allowed |
|---|---|---|---|
| View trades in a group | `GET /trades/in-group/{group_id}` | Any **member** of that group (any role), or global admin | `403 incorrect group` |
| View trades by symbol | `GET /trades/symbol/{symbol}` | Any authenticated user — results are silently filtered to only the groups they belong to (admins see all) | N/A (empty/404 if nothing visible) |
| Create a trade | `POST /trades/?symbol=...` | Any **member** of the target group (any role), or global admin | `403 Not authorized to create a trade in this group` |
| Edit a trade | `PATCH /trades/{trade_id}` | **Only**: (a) the trade's creator, (b) that group's `group_admin`, or (c) a global admin | `403 Not authorized to update this trade` |
| Delete a trade | `DELETE /trades/{trade_id}` | Same rule as edit: creator, group admin, or global admin | `403 Not authorized to delete this trade` |

**This is the key behavior change to design for:** a regular group
`member` who did **not** create a trade can **see** it (it shows up in the
group's trade list) but **cannot edit or delete it**. Only:
- the person who originally logged it,
- the admin of that group, or
- a site-wide admin

...can modify/delete it.

> **UX recommendations:**
> - On each trade row/card, compare `trade.created_by_user_id` to the logged-in
>   user's `id`, **and** check the user's role in `trade`'s group (from
>   `group_associations`), **and** check global `role === "admin"`. Only show
>   Edit/Delete controls (or enable them) if one of those three is true.
> - Since the API will still return `403` if the frontend gets this wrong
>   (e.g. stale cached role data), always handle `403` on PATCH/DELETE trade
>   calls gracefully — show a toast like "You don't have permission to modify
>   this trade" rather than a generic error, and consider refetching the
>   user's group roles when this happens (their role may have just changed).
> - Consider surfacing "Created by {name}" on trade detail views so members
>   understand why they can't edit certain entries.
> - There is intentionally **no way for a client to set `created_by_user_id`**
>   on create — it's always derived server-side from the authenticated user.
>   Don't add a "created by" picker on the create-trade form.

### 3.2 Groups

| Action | Endpoint | Who is allowed | Error if not allowed |
|---|---|---|---|
| Create a group | `POST /groups/` | Global admin only | `403` |
| List groups | `GET /groups/` | Any user — admins see **all** groups; regular users see only groups they belong to | `404 Group not found` if the user belongs to none |
| View group details/members | `GET /groups/{group_id}` | Any **member** of that group, or global admin | `403 Not authorized to access this group's details` |
| Add/update a member's role in a group | `POST /groups/{group_id}/members/{user_id}` | That group's `group_admin`, or global admin | `403` |
| Remove a member from a group | `DELETE /groups/{group_id}/members/{user_id}` | Global admin only (**not** group admins, currently) | `403` |
| Update a group's name | `PUT /groups/{group_id}` | Global admin only | `403` |
| Delete a group | `DELETE /groups/{group_id}` | Global admin only; fails with `400` if the group still has members | `403` / `400 Cannot delete group. It may still contain members.` |

> **UX note:** Notice the asymmetry — a `group_admin` can add/change a
> member's role, but **cannot** remove a member or delete/rename the group
> itself; only a site-wide admin can. Don't assume "group admin" means full
> control of the group in the UI — surface only the member-role-management
> actions to group admins, and hide delete-group/remove-member/rename-group
> controls unless `role === "admin"`.
>
> Also: when a group creator makes a group, they're automatically made that
> group's `group_admin` — so "create group" flows should expect the creator
> to immediately land with admin-level member management for it.

### 3.3 Assets

Assets are **global** (not owned by a group or user).

| Action | Endpoint | Who is allowed |
|---|---|---|
| List / view assets (with the user's own holdings) | `GET /assets/`, `GET /assets/{symbol}` | Any authenticated user |
| Create an asset | `POST /assets/create` | Global admin only |
| Update all asset prices | `POST /assets/update-all-prices` | Global admin only |
| Update an asset | `PATCH /assets/{asset_id}` | Global admin only |
| Delete an asset | `DELETE /assets/{asset_id}` | Global admin only; fails with `400` if trades reference it |

> **UX note:** Regular users should only ever see a read-only asset catalog
> (with their personal quantity held). All create/edit/delete/price-refresh
> controls for assets should be admin-only in the UI — gate these entirely
> behind `role === "admin"`, there is no group-level asset management.

### 3.4 Reports

| Action | Endpoint | Who is allowed | Scoping |
|---|---|---|---|
| Asset valuation report | `GET /reports/valuation/{symbol}/{target_currency}` | Any authenticated user | Non-admins only see figures derived from trades in **their own groups**; admins see figures across all groups |
| Portfolio performance report | `GET /reports/portfolio-performance` | Any authenticated user | Same scoping as above |

> **UX note:** These endpoints never 403 based on role — everyone can call
> them — but the **data returned is silently scoped** to the caller's groups
> unless they're a global admin. No special permission-gating UI is needed
> here beyond normal auth; just be aware two different users hitting the
> same report endpoint can legitimately get different numbers.

### 3.5 Users / Auth

| Action | Endpoint | Who is allowed |
|---|---|---|
| Register | `POST /register` | Public (rate-limited: 3/hour/IP) |
| Login | `POST /login/access-token` | Public (rate-limited: 5/min/IP) |
| List all users | `GET /users` | Global admin only |
| Get own profile | `GET /users/me` | Any authenticated user (self only) |

> **UX note:** There is currently no "view another user's public profile"
> endpoint and no self-service "edit my profile" endpoint — don't build UI
> for those yet, they don't exist server-side.

---

## 4. Quick-reference: what to compute client-side

Given the current user object (from `GET /users/me`) and a resource, here's
the boolean logic the frontend should mirror to decide what to render/enable
(the server is always the source of truth — this is for optimistic UI only):

```text
isGlobalAdmin        = user.role === "admin"

isGroupMember(group)     = isGlobalAdmin || user.group_associations
                             .some(a => a.group_id === group.id)

isGroupAdmin(group)      = isGlobalAdmin || user.group_associations
                             .some(a => a.group_id === group.id && a.role === "group_admin")

canViewTrade(trade)      = isGroupMember({ id: trade.group_id })

canEditOrDeleteTrade(trade) =
     isGlobalAdmin
  || trade.created_by_user_id === user.id
  || isGroupAdmin({ id: trade.group_id })
```

Always treat any `401`/`403` response as authoritative — if the optimistic
check above says "yes" but the server says `403`, trust the server (the
user's role/membership may have changed since the token/profile was last
fetched) and re-sync the user's profile/group data.

---

## 5. Summary cheat sheet

| Role | Can see | Can create trades | Can edit/delete **any** trade | Can edit/delete **own** trade | Manage group members (roles) | Remove members / delete / rename group | Manage assets |
|---|---|---|---|---|---|---|---|
| Regular member | Own groups' data | ✅ (in own groups) | ❌ | ✅ | ❌ | ❌ | ❌ |
| Group admin (in that group) | Own groups' data | ✅ (in own groups) | ✅ (within that group only) | ✅ | ✅ (within that group only) | ❌ | ❌ |
| Global admin | Everything | ✅ (any group) | ✅ (anywhere) | ✅ | ✅ (any group) | ✅ | ✅ |

If anything here doesn't match what you're observing from the API, treat the
API's actual response codes as the source of truth and flag it — this doc
should be kept in sync with `service/permissions.py` and the router files
whenever the rules change.
