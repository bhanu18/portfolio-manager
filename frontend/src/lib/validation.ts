// ---------------------------------------------------------------------------
// Small client-side validation helpers mirroring backend constraints.
// Returns an error string, or null when the value is valid.
// ---------------------------------------------------------------------------

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Backend password minimum length (kept here so all forms agree). */
export const PASSWORD_MIN_LENGTH = 8;

export function validateRequired(value: string, label = "This field"): string | null {
  return value.trim().length === 0 ? `${label} is required.` : null;
}

export function validateEmail(value: string): string | null {
  if (value.trim().length === 0) return "Email is required.";
  return EMAIL_RE.test(value.trim()) ? null : "Enter a valid email address.";
}

export function validatePassword(value: string): string | null {
  if (value.length === 0) return "Password is required.";
  if (value.length < PASSWORD_MIN_LENGTH) {
    return `Password must be at least ${PASSWORD_MIN_LENGTH} characters.`;
  }
  return null;
}

/** Positive number validation for trade quantity / price fields. */
export function validatePositiveNumber(value: string, label = "Value"): string | null {
  if (value.trim().length === 0) return `${label} is required.`;
  const num = Number(value);
  if (Number.isNaN(num)) return `${label} must be a number.`;
  if (num <= 0) return `${label} must be greater than 0.`;
  return null;
}

/** Returns true when every value in the record is null (no errors). */
export function isValid(errors: Record<string, string | null>): boolean {
  return Object.values(errors).every((e) => e === null);
}
