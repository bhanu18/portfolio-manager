import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as authApi from "../api/auth";
import { createGroup, deleteGroup } from "../api/groups";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { getErrorMessage, parseApiError } from "../lib/errors";
import { validatePassword, validateRequired } from "../lib/validation";
import { formatDateTime } from "../lib/format";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Modal } from "../components/Modal";

export function ProfilePage() {
  const { user, isAdmin, refreshUser } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();

  // Refresh on mount so groups are always up to date.
  useEffect(() => {
    void refreshUser();
  }, [refreshUser]);

  // ── Change password form ────────────────────────────────────────────────
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pwErrors, setPwErrors] = useState<Record<string, string | null>>({});
  const [pwFormError, setPwFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handlePasswordSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setPwFormError(null);

    const nextErrors: Record<string, string | null> = {
      current: validateRequired(currentPassword, "Current password"),
      newPassword: validatePassword(newPassword),
      confirm: confirm !== newPassword ? "Passwords do not match." : null,
    };
    setPwErrors(nextErrors);
    if (Object.values(nextErrors).some(Boolean)) return;

    setSubmitting(true);
    try {
      await authApi.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      toast.success("Password changed successfully.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirm("");
    } catch (err) {
      setPwFormError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  // ── Create group ────────────────────────────────────────────────────────
  const [showCreate, setShowCreate] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: (name: string) => createGroup(name),
    onSuccess: async () => {
      toast.success("Group created.");
      setShowCreate(false);
      setNewGroupName("");
      await refreshUser();
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    onError: (err) => toast.error(parseApiError(err).message),
  });

  function handleCreate() {
    const trimmed = newGroupName.trim();
    if (!trimmed) { setNameError("Group name is required."); return; }
    setNameError(null);
    createMutation.mutate(trimmed);
  }

  // ── Delete group ────────────────────────────────────────────────────────
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; name: string } | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const deleteMutation = useMutation({
    mutationFn: (groupId: number) => deleteGroup(groupId),
    onSuccess: async () => {
      toast.success("Group deleted.");
      setDeleteTarget(null);
      setDeleteError(null);
      await refreshUser();
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
    onError: (err) => setDeleteError(parseApiError(err).message),
  });

  // ── Render ──────────────────────────────────────────────────────────────
  if (!user) return null;

  const groups = user.groups ?? [];
  const role = user.role ?? "user";

  return (
    <div className="page">
      <div className="page__header">
        <h1 className="page__title">Profile</h1>
      </div>

      <div className="grid grid--2">
        {/* ── Account info + Groups ── */}
        <section className="card">
          <h2 className="card__title">Account</h2>
          <dl className="detail-list">
            <div className="detail-list__row">
              <dt>Name</dt>
              <dd>{user.name}</dd>
            </div>
            <div className="detail-list__row">
              <dt>Email</dt>
              <dd>{user.email}</dd>
            </div>
            <div className="detail-list__row">
              <dt>Role</dt>
              <dd>
                <span className={`badge ${role === "admin" ? "badge--admin" : "badge--muted"}`}>
                  {role}
                </span>
              </dd>
            </div>
            <div className="detail-list__row">
              <dt>Status</dt>
              <dd>
                <span className={`badge ${user.is_active ? "badge--buy" : "badge--sell"}`}>
                  {user.is_active ? "Active" : "Inactive"}
                </span>
              </dd>
            </div>
            {user.created_at && (
              <div className="detail-list__row">
                <dt>Member since</dt>
                <dd>{formatDateTime(user.created_at)}</dd>
              </div>
            )}
          </dl>

          {/* Groups section */}
          <div className="card__section-header">
            <h3 className="card__subtitle">Groups</h3>
            {isAdmin && (
              <button
                type="button"
                className="btn btn--primary btn--sm"
                onClick={() => setShowCreate(true)}
              >
                + New group
              </button>
            )}
          </div>

          {groups.length === 0 ? (
            <p className="muted">You're not a member of any groups yet.</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Your role</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {groups.map((g) => (
                    <tr key={g.id}>
                      <td>
                        <Link to={`/groups/${g.id}`} className="link-button">
                          {g.name}
                        </Link>
                      </td>
                      <td>
                        <span className={`badge ${g.role === "group_admin" ? "badge--admin" : "badge--muted"}`}>
                          {g.role === "group_admin" ? "admin" : "member"}
                        </span>
                      </td>
                      <td className="row-actions">
                        <Link to={`/groups/${g.id}`} className="btn btn--ghost btn--sm">
                          View
                        </Link>
                        {isAdmin && (
                          <button
                            type="button"
                            className="btn btn--danger btn--sm"
                            onClick={() => { setDeleteError(null); setDeleteTarget({ id: g.id, name: g.name }); }}
                          >
                            Delete
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* ── Change password ── */}
        <section className="card">
          <h2 className="card__title">Change password</h2>

          {pwFormError && (
            <div className="alert alert--error" role="alert">
              {pwFormError}
            </div>
          )}

          <form onSubmit={handlePasswordSubmit} noValidate>
            <div className="field">
              <label htmlFor="current" className="field__label">Current password</label>
              <input
                id="current"
                type="password"
                autoComplete="current-password"
                className="field__input"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                aria-invalid={Boolean(pwErrors.current)}
              />
              {pwErrors.current && <span className="field__error">{pwErrors.current}</span>}
            </div>

            <div className="field">
              <label htmlFor="newPassword" className="field__label">New password</label>
              <input
                id="newPassword"
                type="password"
                autoComplete="new-password"
                className="field__input"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                aria-invalid={Boolean(pwErrors.newPassword)}
              />
              {pwErrors.newPassword && <span className="field__error">{pwErrors.newPassword}</span>}
            </div>

            <div className="field">
              <label htmlFor="confirm" className="field__label">Confirm new password</label>
              <input
                id="confirm"
                type="password"
                autoComplete="new-password"
                className="field__input"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                aria-invalid={Boolean(pwErrors.confirm)}
              />
              {pwErrors.confirm && <span className="field__error">{pwErrors.confirm}</span>}
            </div>

            <button type="submit" className="btn btn--primary" disabled={submitting}>
              {submitting ? "Saving…" : "Change password"}
            </button>
          </form>
        </section>
      </div>

      {/* ── Create group modal ── */}
      <Modal
        open={showCreate}
        title="Create Group"
        onClose={() => { setShowCreate(false); setNewGroupName(""); setNameError(null); }}
        footer={
          <>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => { setShowCreate(false); setNewGroupName(""); setNameError(null); }}
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

      {/* ── Delete group confirmation ── */}
      <ConfirmDialog
        open={deleteTarget !== null && !deleteMutation.isSuccess}
        title={`Delete "${deleteTarget?.name}"`}
        message={
          deleteError
            ? deleteError
            : `Are you sure you want to delete "${deleteTarget?.name}"? This cannot be undone.`
        }
        confirmLabel="Delete"
        busy={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
        onCancel={() => { setDeleteTarget(null); setDeleteError(null); }}
      />
    </div>
  );
}
