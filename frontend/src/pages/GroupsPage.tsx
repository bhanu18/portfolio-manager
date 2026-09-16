// ---------------------------------------------------------------------------
// Groups list page — /groups
// Shows groups the current user belongs to (from /users/me).
// Global admins can create and delete groups.
// ---------------------------------------------------------------------------

import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createGroup, deleteGroup } from "../api/groups";
import { getMe } from "../api/auth";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { parseApiError } from "../lib/errors";
import { Spinner } from "../components/Spinner";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Modal } from "../components/Modal";

export function GroupsPage() {
  const { isAdmin, refreshUser } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();

  // Fetch current user to get the groups list.
  const { data: user, isLoading, isError, error } = useQuery({
    queryKey: ["me"],
    queryFn: getMe,
  });

  // Create group modal state.
  const [showCreate, setShowCreate] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);

  // Delete confirmation state.
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; name: string } | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: (name: string) => createGroup(name),
    onSuccess: async () => {
      toast.success("Group created.");
      setShowCreate(false);
      setNewGroupName("");
      // Refresh user so new group appears in the list.
      await refreshUser();
      queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    onError: (err) => {
      const parsed = parseApiError(err);
      toast.error(parsed.message);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (groupId: number) => deleteGroup(groupId),
    onSuccess: async () => {
      toast.success("Group deleted.");
      setDeleteTarget(null);
      setDeleteError(null);
      await refreshUser();
      queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    onError: (err) => {
      const parsed = parseApiError(err);
      // Surface the specific backend message (e.g. "group still has members").
      setDeleteError(parsed.message);
    },
  });

  // --- Handlers -----------------------------------------------------------

  function handleCreate() {
    const trimmed = newGroupName.trim();
    if (!trimmed) {
      setNameError("Group name is required.");
      return;
    }
    setNameError(null);
    createMutation.mutate(trimmed);
  }

  function handleDeleteConfirm() {
    if (!deleteTarget) return;
    setDeleteError(null);
    deleteMutation.mutate(deleteTarget.id);
  }

  function handleDeleteCancel() {
    setDeleteTarget(null);
    setDeleteError(null);
  }

  // --- Render -------------------------------------------------------------

  if (isLoading) return <Spinner block label="Loading groups…" />;

  if (isError) {
    const msg = parseApiError(error).message;
    return (
      <div className="container">
        <div className="error-state">
          <p className="error-state__message">{msg}</p>
        </div>
      </div>
    );
  }

  const groups = user?.groups ?? [];

  return (
    <div className="container">
      <div className="page">
        {/* Header */}
        <div className="page__header">
          <h1 className="page__title">Groups</h1>
          {isAdmin && (
            <div className="page__actions">
              <button
                type="button"
                className="btn btn--primary btn--sm"
                onClick={() => setShowCreate(true)}
              >
                + Create Group
              </button>
            </div>
          )}
        </div>

        {/* Group list */}
        {groups.length === 0 ? (
          <div className="empty-state">
            <p>You are not a member of any groups yet.</p>
            {isAdmin && (
              <button
                type="button"
                className="btn btn--primary btn--sm"
                onClick={() => setShowCreate(true)}
              >
                Create your first group
              </button>
            )}
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>ID</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {groups.map((g) => (
                  <tr key={g.id}>
                    <td>
                      <Link to={`/groups/${g.id}`} className="navbar__link" style={{ padding: 0 }}>
                        {g.name}
                      </Link>
                    </td>
                    <td className="muted small">{g.id}</td>
                    <td>
                      <div className="row-actions">
                        <Link
                          to={`/groups/${g.id}`}
                          className="btn btn--ghost btn--sm"
                        >
                          View
                        </Link>
                        {isAdmin && (
                          <button
                            type="button"
                            className="btn btn--danger btn--sm"
                            onClick={() => {
                              setDeleteError(null);
                              setDeleteTarget({ id: g.id, name: g.name });
                            }}
                          >
                            Delete
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create group modal */}
      <Modal
        open={showCreate}
        title="Create Group"
        onClose={() => {
          setShowCreate(false);
          setNewGroupName("");
          setNameError(null);
        }}
        footer={
          <>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => {
                setShowCreate(false);
                setNewGroupName("");
                setNameError(null);
              }}
              disabled={createMutation.isPending}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn--primary"
              onClick={handleCreate}
              disabled={createMutation.isPending}
            >
              {createMutation.isPending ? "Creating…" : "Create"}
            </button>
          </>
        }
      >
        <div className="field">
          <label className="field__label" htmlFor="group-name">
            Group name <span aria-hidden>*</span>
          </label>
          <input
            id="group-name"
            className="field__input"
            aria-invalid={nameError ? "true" : undefined}
            value={newGroupName}
            onChange={(e) => setNewGroupName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
            placeholder="e.g. Family Portfolio"
            autoFocus
          />
          {nameError && <span className="field__error">{nameError}</span>}
        </div>
      </Modal>

      {/* Delete confirmation */}
      <ConfirmDialog
        open={deleteTarget !== null && !deleteMutation.isSuccess}
        title={`Delete "${deleteTarget?.name}"`}
        message={
          deleteError
            ? deleteError
            : `Are you sure you want to delete "${deleteTarget?.name}"? This action cannot be undone.`
        }
        confirmLabel="Delete"
        busy={deleteMutation.isPending}
        onConfirm={handleDeleteConfirm}
        onCancel={handleDeleteCancel}
      />
    </div>
  );
}
