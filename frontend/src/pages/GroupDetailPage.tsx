// ---------------------------------------------------------------------------
// Group detail page — /groups/:groupId
// Shows group members. Global admins can add/remove members and change roles.
// Rename group is a stub (backend not yet implemented).
// ---------------------------------------------------------------------------

import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getGroup, addOrUpdateMember, removeMember } from "../api/groups";
import { listUsers } from "../api/auth";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { parseApiError } from "../lib/errors";
import type { GroupMemberRole, User } from "../types";
import { Spinner } from "../components/Spinner";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Modal } from "../components/Modal";

export function GroupDetailPage() {
  const { groupId } = useParams<{ groupId: string }>();
  const id = Number(groupId);
  const { isAdmin } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();

  // Fetch group detail.
  const { data: group, isLoading, isError, error } = useQuery({
    queryKey: ["group", id],
    queryFn: () => getGroup(id),
    enabled: !Number.isNaN(id),
  });

  // Fetch all users (admin-only) for the Add Member user picker.
  const { data: allUsers } = useQuery({
    queryKey: ["users"],
    queryFn: listUsers,
    enabled: isAdmin,
  });

  // --- Remove member state ---
  const [removeTarget, setRemoveTarget] = useState<{ id: number; name: string } | null>(null);

  const removeMutation = useMutation({
    mutationFn: (userId: number) => removeMember(id, userId),
    onSuccess: () => {
      toast.success("Member removed.");
      setRemoveTarget(null);
      queryClient.invalidateQueries({ queryKey: ["group", id] });
    },
    onError: (err) => {
      toast.error(parseApiError(err).message);
    },
  });

  // --- Add member modal state ---
  const [showAddMember, setShowAddMember] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState<string>("");
  const [selectedRole, setSelectedRole] = useState<GroupMemberRole>("member");
  const [addMemberError, setAddMemberError] = useState<string | null>(null);

  const addMemberMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: GroupMemberRole }) =>
      addOrUpdateMember(id, userId, role),
    onSuccess: () => {
      toast.success("Member added / role updated.");
      setShowAddMember(false);
      setSelectedUserId("");
      setSelectedRole("member");
      setAddMemberError(null);
      queryClient.invalidateQueries({ queryKey: ["group", id] });
    },
    onError: (err) => {
      setAddMemberError(parseApiError(err).message);
    },
  });

  // --- Change role state ---
  const [changeRoleTarget, setChangeRoleTarget] = useState<{ id: number; name: string } | null>(null);
  const [changeRoleValue, setChangeRoleValue] = useState<GroupMemberRole>("member");

  const changeRoleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: GroupMemberRole }) =>
      addOrUpdateMember(id, userId, role),
    onSuccess: () => {
      toast.success("Role updated.");
      setChangeRoleTarget(null);
      queryClient.invalidateQueries({ queryKey: ["group", id] });
    },
    onError: (err) => {
      toast.error(parseApiError(err).message);
    },
  });

  // --- Rename stub state ---
  const [showRename, setShowRename] = useState(false);

  // --- Handlers -----------------------------------------------------------

  function handleAddMember() {
    if (!selectedUserId) {
      setAddMemberError("Please select a user.");
      return;
    }
    setAddMemberError(null);
    addMemberMutation.mutate({ userId: Number(selectedUserId), role: selectedRole });
  }

  function handleChangeRoleConfirm() {
    if (!changeRoleTarget) return;
    changeRoleMutation.mutate({ userId: changeRoleTarget.id, role: changeRoleValue });
  }

  // --- Render -------------------------------------------------------------

  if (isLoading) return <Spinner block label="Loading group…" />;

  if (isError) {
    const parsed = parseApiError(error);
    return (
      <div className="container">
        <p className="back-link">
          <Link to="/groups">← Back to Groups</Link>
        </p>
        <div className="error-state" style={{ marginTop: "1rem" }}>
          <p className="error-state__message">{parsed.message}</p>
        </div>
      </div>
    );
  }

  if (!group) return null;

  // Build a lookup of existing member IDs to filter them out of the add-member picker.
  const existingMemberIds = new Set(group.members.map((m) => m.id));

  // Users available to add (exclude existing members).
  const usersToAdd: User[] = (allUsers ?? []).filter((u) => !existingMemberIds.has(u.id));

  return (
    <div className="container">
      <div className="page">
        {/* Back link */}
        <p className="back-link">
          <Link to="/groups">← Back to Groups</Link>
        </p>

        {/* Header */}
        <div className="page__header">
          <h1 className="page__title">
            {group.name}
            <span className="muted small" style={{ marginLeft: "0.5rem", fontWeight: 400 }}>
              #{group.id}
            </span>
          </h1>
          <div className="page__actions">
            <Link
              to={`/trades?group=${group.id}`}
              className="btn btn--ghost btn--sm"
            >
              View Trades →
            </Link>
            {isAdmin && (
              <>
                <button
                  type="button"
                  className="btn btn--secondary btn--sm"
                  onClick={() => setShowRename(true)}
                >
                  Rename Group
                </button>
                <button
                  type="button"
                  className="btn btn--primary btn--sm"
                  onClick={() => setShowAddMember(true)}
                >
                  + Add Member
                </button>
              </>
            )}
          </div>
        </div>

        {/* Members table */}
        <div className="card">
          <h2 className="card__title">Members ({group.members.length})</h2>
          {group.members.length === 0 ? (
            <p className="muted" style={{ marginTop: "1rem" }}>No members yet.</p>
          ) : (
            <div className="table-wrap" style={{ marginTop: "1rem" }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>ID</th>
                    {isAdmin && <th />}
                  </tr>
                </thead>
                <tbody>
                  {group.members.map((member) => (
                    <tr key={member.id}>
                      <td>{member.name}</td>
                      <td className="muted">{member.email}</td>
                      <td className="muted small">{member.id}</td>
                      {isAdmin && (
                        <td>
                          <div className="row-actions">
                            <button
                              type="button"
                              className="btn btn--ghost btn--sm"
                              onClick={() => {
                                setChangeRoleTarget({ id: member.id, name: member.name });
                                setChangeRoleValue("member");
                              }}
                            >
                              Change Role
                            </button>
                            <button
                              type="button"
                              className="btn btn--danger btn--sm"
                              onClick={() => setRemoveTarget({ id: member.id, name: member.name })}
                            >
                              Remove
                            </button>
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Rename stub modal */}
      <Modal
        open={showRename}
        title="Rename Group"
        onClose={() => setShowRename(false)}
        footer={
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => setShowRename(false)}
          >
            Close
          </button>
        }
      >
        <div className="alert alert--info" style={{ marginBottom: "1rem" }}>
          Group renaming is coming soon.
        </div>
        <div className="field">
          <label className="field__label" htmlFor="rename-group">Group name</label>
          <input
            id="rename-group"
            className="field__input"
            defaultValue={group.name}
            disabled
          />
        </div>
      </Modal>

      {/* Add member modal */}
      <Modal
        open={showAddMember}
        title="Add Member"
        onClose={() => {
          setShowAddMember(false);
          setSelectedUserId("");
          setSelectedRole("member");
          setAddMemberError(null);
        }}
        footer={
          <>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => {
                setShowAddMember(false);
                setSelectedUserId("");
                setSelectedRole("member");
                setAddMemberError(null);
              }}
              disabled={addMemberMutation.isPending}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn--primary"
              onClick={handleAddMember}
              disabled={addMemberMutation.isPending}
            >
              {addMemberMutation.isPending ? "Adding…" : "Add Member"}
            </button>
          </>
        }
      >
        {addMemberError && (
          <div className="alert alert--error" style={{ marginBottom: "1rem" }}>
            {addMemberError}
          </div>
        )}

        <div className="field">
          <label className="field__label" htmlFor="add-member-user">
            User <span aria-hidden>*</span>
          </label>
          {usersToAdd.length > 0 ? (
            <select
              id="add-member-user"
              className="field__input"
              value={selectedUserId}
              onChange={(e) => setSelectedUserId(e.target.value)}
            >
              <option value="">— Select a user —</option>
              {usersToAdd.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} ({u.email})
                </option>
              ))}
            </select>
          ) : (
            <p className="muted small">
              All available users are already members of this group.
            </p>
          )}
        </div>

        <div className="field">
          <label className="field__label" htmlFor="add-member-role">Role</label>
          <select
            id="add-member-role"
            className="field__input"
            value={selectedRole}
            onChange={(e) => setSelectedRole(e.target.value as GroupMemberRole)}
          >
            <option value="member">Member</option>
            <option value="group_admin">Group Admin</option>
          </select>
        </div>
      </Modal>

      {/* Change role modal */}
      <Modal
        open={changeRoleTarget !== null}
        title={`Change Role — ${changeRoleTarget?.name ?? ""}`}
        onClose={() => setChangeRoleTarget(null)}
        footer={
          <>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => setChangeRoleTarget(null)}
              disabled={changeRoleMutation.isPending}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn--primary"
              onClick={handleChangeRoleConfirm}
              disabled={changeRoleMutation.isPending}
            >
              {changeRoleMutation.isPending ? "Saving…" : "Save Role"}
            </button>
          </>
        }
      >
        <div className="field">
          <label className="field__label" htmlFor="change-role-value">New role</label>
          <select
            id="change-role-value"
            className="field__input"
            value={changeRoleValue}
            onChange={(e) => setChangeRoleValue(e.target.value as GroupMemberRole)}
          >
            <option value="member">Member</option>
            <option value="group_admin">Group Admin</option>
          </select>
        </div>
      </Modal>

      {/* Remove member confirmation */}
      <ConfirmDialog
        open={removeTarget !== null}
        title={`Remove "${removeTarget?.name}"`}
        message={`Remove ${removeTarget?.name} from this group? They will lose access to the group's trades.`}
        confirmLabel="Remove"
        busy={removeMutation.isPending}
        onConfirm={() => removeTarget && removeMutation.mutate(removeTarget.id)}
        onCancel={() => setRemoveTarget(null)}
      />
    </div>
  );
}
