// ---------------------------------------------------------------------------
// Auth resource module. Maps 1:1 to the backend's auth endpoints (no prefix).
// ---------------------------------------------------------------------------

import { apiClient } from "../lib/apiClient";
import type {
  ChangePasswordPayload,
  ForgotPasswordPayload,
  GroupAssociation,
  GroupMemberRoleValue,
  LoginResponse,
  RawUser,
  RegisterPayload,
  ResetPasswordPayload,
  User,
} from "../types";

/**
 * Normalize groups from the `/users/me` response into GroupAssociation[].
 * The actual backend shape is:
 *   group_associations: [{ group_id, group_name, role }]
 * but we also handle flat/nested variants for robustness.
 */
function normalizeGroups(raw: RawUser): GroupAssociation[] {
  const rows: unknown[] =
    (raw.group_associations as unknown[]) ??
    (raw.groups as unknown[]) ??
    (raw.memberships as unknown[]) ??
    (raw.user_groups as unknown[]) ??
    [];

  if (!Array.isArray(rows)) return [];

  return rows.flatMap((row): GroupAssociation[] => {
    if (!row || typeof row !== "object") return [];
    const r = row as Record<string, unknown>;

    const role: GroupMemberRoleValue = r.role === "group_admin" ? "group_admin" : "member";

    // 1. Association columns: { group_id, group_name, role } — actual backend shape
    if (r.group_id != null) {
      const id = typeof r.group_id === "number" ? r.group_id : Number(r.group_id);
      if (!Number.isNaN(id) && id > 0) {
        const name =
          (typeof r.group_name === "string" ? r.group_name : null) ??
          (typeof r.name === "string" ? r.name : null) ??
          `Group #${id}`;
        return [{ id, name, role }];
      }
    }

    // 2. Nested group object: { group: { id, name }, role }
    if (r.group && typeof r.group === "object") {
      const g = r.group as Record<string, unknown>;
      const gId = typeof g.id === "number" ? g.id : Number(g.id);
      const gName = typeof g.name === "string" ? g.name : null;
      if (!Number.isNaN(gId) && gId > 0 && gName) {
        return [{ id: gId, name: gName, role }];
      }
    }

    // 3. Direct flat group: { id, name }
    if (r.id != null && r.name != null && typeof r.name === "string") {
      const id = typeof r.id === "number" ? r.id : Number(r.id);
      if (!Number.isNaN(id) && id > 0) {
        return [{ id, name: r.name, role }];
      }
    }

    return [];
  });
}

/** Map a raw `/users/me` payload into the normalized app-wide User. */
function normalizeUser(raw: RawUser): User {
  return {
    id: raw.id,
    name: raw.name,
    email: raw.email,
    role: raw.role ?? "user",
    is_active: raw.is_active ?? true,
    groups: normalizeGroups(raw),
    created_at: raw.created_at,
    updated_at: raw.updated_at,
  };
}

/** POST /register — create a new account. Rate-limited 3/hour. */
export async function register(payload: RegisterPayload): Promise<User> {
  const { data } = await apiClient.post<RawUser>("/register", payload);
  return normalizeUser(data);
}

/**
 * POST /login/access-token — OAuth2 password flow.
 * IMPORTANT: this endpoint is form-encoded (NOT JSON) and expects
 * `username` (= email) and `password` fields.
 */
export async function login(email: string, password: string): Promise<LoginResponse> {
  const form = new URLSearchParams();
  form.append("username", email);
  form.append("password", password);

  const { data } = await apiClient.post<LoginResponse>("/login/access-token", form, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  return data;
}

/** GET /users/me — current user profile (groups normalized to a flat list). */
export async function getMe(): Promise<User> {
  const { data } = await apiClient.get<RawUser>("/users/me");
  return normalizeUser(data);
}

/** GET /users — admin only. */
export async function listUsers(): Promise<User[]> {
  const { data } = await apiClient.get<User[]>("/users");
  return data;
}

/** POST /change-password — requires auth. Rate-limited 5/hour. */
export async function changePassword(
  payload: ChangePasswordPayload,
): Promise<{ message?: string }> {
  const { data } = await apiClient.post<{ message?: string }>("/change-password", payload);
  return data;
}

/** POST /forgot-password — always returns a generic success message. */
export async function forgotPassword(
  payload: ForgotPasswordPayload,
): Promise<{ message?: string }> {
  const { data } = await apiClient.post<{ message?: string }>("/forgot-password", payload);
  return data;
}

/** POST /reset-password — body { token, new_password }. */
export async function resetPassword(payload: ResetPasswordPayload): Promise<{ message?: string }> {
  const { data } = await apiClient.post<{ message?: string }>("/reset-password", payload);
  return data;
}
