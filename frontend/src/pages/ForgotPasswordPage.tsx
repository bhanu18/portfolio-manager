import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import * as authApi from "../api/auth";
import { getErrorMessage } from "../lib/errors";
import { validateEmail } from "../lib/validation";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setFormError(null);

    const err = validateEmail(email);
    setEmailError(err);
    if (err) return;

    setSubmitting(true);
    try {
      await authApi.forgotPassword({ email: email.trim() });
      // Backend always returns a generic success (no account enumeration).
      setDone(true);
    } catch (e2) {
      setFormError(getErrorMessage(e2));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-layout">
      <div className="auth-card">
        <h1 className="auth-card__title">Reset your password</h1>

        {done ? (
          <>
            <div className="alert alert--success" role="status">
              If an account exists for that email, we've sent a reset link. Check your inbox and
              follow the link to choose a new password.
            </div>
            <div className="auth-card__links">
              <Link to="/reset-password">I have a reset token</Link>
              <Link to="/login">Back to sign in</Link>
            </div>
          </>
        ) : (
          <>
            <p className="auth-card__subtitle">Enter your email and we'll send a reset link.</p>

            {formError && (
              <div className="alert alert--error" role="alert">
                {formError}
              </div>
            )}

            <form onSubmit={handleSubmit} noValidate>
              <div className="field">
                <label htmlFor="email" className="field__label">
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  className="field__input"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  aria-invalid={Boolean(emailError)}
                />
                {emailError && <span className="field__error">{emailError}</span>}
              </div>

              <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
                {submitting ? "Sending…" : "Send reset link"}
              </button>
            </form>

            <div className="auth-card__links">
              <Link to="/login">Back to sign in</Link>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
