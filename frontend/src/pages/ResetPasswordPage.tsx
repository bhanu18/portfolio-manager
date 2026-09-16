import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import * as authApi from "../api/auth";
import { useToast } from "../context/ToastContext";
import { getErrorMessage } from "../lib/errors";
import { validatePassword, validateRequired } from "../lib/validation";

export function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();

  // Token may arrive via ?token=... in the URL; allow manual entry otherwise.
  const [token, setToken] = useState(searchParams.get("token") ?? "");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setFormError(null);

    const nextErrors: Record<string, string | null> = {
      token: validateRequired(token, "Reset token"),
      newPassword: validatePassword(newPassword),
      confirm: confirm !== newPassword ? "Passwords do not match." : null,
    };
    setErrors(nextErrors);
    if (Object.values(nextErrors).some(Boolean)) return;

    setSubmitting(true);
    try {
      await authApi.resetPassword({
        token: token.trim(),
        new_password: newPassword,
      });
      toast.success("Password reset. You can now sign in.");
      navigate("/login", { replace: true });
    } catch (err) {
      setFormError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-layout">
      <div className="auth-card">
        <h1 className="auth-card__title">Choose a new password</h1>
        <p className="auth-card__subtitle">
          Paste the token from your reset email and set a new password.
        </p>

        {formError && (
          <div className="alert alert--error" role="alert">
            {formError}
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <label htmlFor="token" className="field__label">
              Reset token
            </label>
            <input
              id="token"
              type="text"
              className="field__input"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              aria-invalid={Boolean(errors.token)}
            />
            {errors.token && <span className="field__error">{errors.token}</span>}
          </div>

          <div className="field">
            <label htmlFor="newPassword" className="field__label">
              New password
            </label>
            <input
              id="newPassword"
              type="password"
              autoComplete="new-password"
              className="field__input"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              aria-invalid={Boolean(errors.newPassword)}
            />
            {errors.newPassword && <span className="field__error">{errors.newPassword}</span>}
          </div>

          <div className="field">
            <label htmlFor="confirm" className="field__label">
              Confirm new password
            </label>
            <input
              id="confirm"
              type="password"
              autoComplete="new-password"
              className="field__input"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              aria-invalid={Boolean(errors.confirm)}
            />
            {errors.confirm && <span className="field__error">{errors.confirm}</span>}
          </div>

          <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
            {submitting ? "Resetting…" : "Reset password"}
          </button>
        </form>

        <div className="auth-card__links">
          <Link to="/login">Back to sign in</Link>
        </div>
      </div>
    </div>
  );
}
