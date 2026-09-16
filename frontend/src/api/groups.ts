// ---------------------------------------------------------------------------
// Groups resource module (/groups prefix).
// All endpoints require authentication.
// ---------------------------------------------------------------------------

import { apiClient } from "../lib/apiClient";
import type { Group, GroupMemberRole, GroupWithMembers } from "../types";

/** POST /groups/ — create a new group. Global admin only. */
export async function createGroup(name: string): Promise<Group> {
  const { data } = await apiClient.post<Group>("/groups/", { name });
  return data;
}

/**
 * GET /groups/{group_id} — group detail including members list.
 * Caller must be a member of the group (403 otherwise).
 */
export async function getGroup(groupId: number): Promise<GroupWithMembers> {
  const { data } = await apiClient.get<GroupWithMembers>(`/groups/${groupId}`);
  return data;
}

/**
 * POST /groups/{group_id}/members/{user_id}?role={role}
 * Add a new member or update an existing member's role within the group.
 * Role is sent as a query param (NOT body). Idempotent / upsert.
 * Access: group admin (see v2 role-gating notes — global admin is treated as group admin).
 */
export async function addOrUpdateMember(
  groupId: number,
  userId: number,
  role: GroupMemberRole,
): Promise<GroupWithMembers> {
  const { data } = await apiClient.post<GroupWithMembers>(
    `/groups/${groupId}/members/${userId}`,
    null,
    { params: { role } },
  );
  return data;
}

/**
 * DELETE /groups/{group_id}/members/{user_id}
 * Remove a member from the group. Global admin only.
 * Returns updated GroupWithMembers.
 */
export async function removeMember(
  groupId: number,
  userId: number,
): Promise<GroupWithMembers> {
  const { data } = await apiClient.delete<GroupWithMembers>(
    `/groups/${groupId}/members/${userId}`,
  );
  return data;
}

/**
 * DELETE /groups/{group_id} — delete a group. Global admin only.
 * Returns 204 on success. Returns 400 if group still has members —
 * callers should catch and surface the `detail` message.
 */
export async function deleteGroup(groupId: number): Promise<void> {
  await apiClient.delete(`/groups/${groupId}`);
}
