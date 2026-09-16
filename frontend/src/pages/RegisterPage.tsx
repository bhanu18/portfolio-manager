import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { getErrorMessage } from "../lib/errors";
import {
  validateEmail,
  validatePassword,
  validateRequired,
} from "../lib/validation";

export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setFormError(null);

    const nextErrors: Record<string, string | null> = {
      name: validateRequired(name, "Name"),
      email: validateEmail(email),
      password: validatePassword(password),
      confirm:
        confirm !== password ? "Passwords do not match." : null,
    };
    setErrors(nextErrors);
    if (Object.values(nextErrors).some(Boolean)) return;

    setSubmitting(true);
    try {
      await register(name.trim(), email.trim(), password);
      toast.success("Account created — you're signed in.");
      navigate("/assets", { replace: true });
    } catch (err) {
      setFormError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-layout">
      <div className="auth-card">
        <h1 className="auth-card__title">Create your account</h1>
        <p className="auth-card__subtitle">Start tracking your portfolio.</p>

        {formError && (
          <div className="alert alert--error" role="alert">
            {formError}
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <label htmlFor="name" className="field__label">
              Name
            </label>
            <input
              id="name"
              type="text"
              autoComplete="name"
              className="field__input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              aria-invalid={Boolean(errors.name)}
            />
            {errors.name && <span className="field__error">{errors.name}</span>}
          </div>

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
              aria-invalid={Boolean(errors.email)}
            />
            {errors.email && (
              <span className="field__error">{errors.email}</span>
            )}
          </div>

          <div className="field">
            <label htmlFor="password" className="field__label">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              className="field__input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={Boolean(errors.password)}
            />
            {errors.password && (
              <span className="field__error">{errors.password}</span>
            )}
          </div>

          <div className="field">
            <label htmlFor="confirm" className="field__label">
              Confirm password
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
            {errors.confirm && (
              <span className="field__error">{errors.confirm}</span>
            )}
          </div>

          <button
            type="submit"
            className="btn btn--primary btn--block"
            disabled={submitting}
          >
            {submitting ? "Creating account…" : "Create account"}
          </button>
        </form>

        <div className="auth-card__links">
          <span>
            Already have an account? <Link to="/login">Sign in</Link>
          </span>
        </div>
      </div>
    </div>
  );
}
