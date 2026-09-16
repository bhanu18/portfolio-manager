// ---------------------------------------------------------------------------
// Client-side permission helpers.
//
// These mirror the server's authorization model described in
// docs/permissions_and_roles.md. They are used for **optimistic UI only**
// (showing/hiding controls). The server is always the source of truth — any
// 403 response must be treated as authoritative regardless of what these
// helpers return.
//
// Two independent role systems:
//   1. User.role — global role ("user" | "admin")
//   2. group_associations[].role — per-group role ("member" | "group_admin")
// ---------------------------------------------------------------------------

import type { User, TradeResponse } from "../types";

/** True when the user is a site-wide administrator. */
export function isGlobalAdmin(user: User | null): boolean {
  return user?.role === "admin";
}

/**
 * True when the user is a member (any role) of the given group,
 * or is a global admin (who can access all groups).
 */
export function isGroupMember(user: User | null, groupId: number): boolean {
  if (!user) return false;
  if (isGlobalAdmin(user)) return true;
  return user.groups.some((g) => g.id === groupId);
}

/**
 * True when the user holds the `group_admin` role in the given group,
 * or is a global admin.
 */
export function isGroupAdmin(user: User | null, groupId: number): boolean {
  if (!user) return false;
  if (isGlobalAdmin(user)) return true;
  return user.groups.some((g) => g.id === groupId && g.role === "group_admin");
}

/**
 * True when the current user is allowed to edit or delete the given trade.
 *
 * Rules (any one of):
 *   (a) global admin
 *   (b) the trade's creator  (trade.created_by_user_id === user.id)
 *   (c) group_admin of the trade's group
 *
 * When `created_by_user_id` or `group_id` are absent from the trade response
 * (older API or partial response), we fall back to false for (b)/(c) rather
 * than accidentally granting access.
 */
export function canEditOrDeleteTrade(
  user: User | null,
  trade: Pick<TradeResponse, "created_by_user_id" | "group_id">,
): boolean {
  if (!user) return false;
  if (isGlobalAdmin(user)) return true;
  if (trade.created_by_user_id != null && trade.created_by_user_id === user.id) return true;
  if (trade.group_id != null && isGroupAdmin(user, trade.group_id)) return true;
  return false;
}
