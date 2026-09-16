// ---------------------------------------------------------------------------
// Shared error parsing. FastAPI returns errors as { "detail": ... } where
// `detail` is usually a string, but for validation errors it is an array of
// { loc, msg, type } objects. This utility normalizes everything to a single
// human-readable string and exposes the HTTP status for callers that need it.
// ---------------------------------------------------------------------------

import { AxiosError } from "axios";

export interface ParsedApiError {
  status: number | null;
  message: string;
  isRateLimited: boolean; // HTTP 429
  isForbidden: boolean; // HTTP 403
  isUnauthorized: boolean; // HTTP 401
  isNotFound: boolean; // HTTP 404
}

interface FastApiValidationItem {
  loc?: (string | number)[];
  msg?: string;
  type?: string;
}

function formatDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;

  if (Array.isArray(detail)) {
    const parts = (detail as FastApiValidationItem[])
      .map((item) => {
        const field = Array.isArray(item.loc) ? item.loc.filter((p) => p !== "body").join(".") : "";
        const msg = item.msg ?? "Invalid value";
        return field ? `${field}: ${msg}` : msg;
      })
      .filter(Boolean);
    if (parts.length > 0) return parts.join("; ");
  }

  if (detail && typeof detail === "object") {
    const maybeMsg = (detail as Record<string, unknown>).msg;
    if (typeof maybeMsg === "string") return maybeMsg;
  }

  return null;
}

export function parseApiError(error: unknown): ParsedApiError {
  // Axios error with a response from the server.
  if (error instanceof AxiosError) {
    const status = error.response?.status ?? null;
    const data = error.response?.data as
      { detail?: unknown; error?: unknown; message?: unknown } | undefined;

    let message: string | null = null;
    if (data) {
      message =
        formatDetail(data.detail) ??
        (typeof data.error === "string" ? data.error : null) ??
        (typeof data.message === "string" ? data.message : null);
    }

    if (!message) {
      if (error.code === "ERR_NETWORK") {
        message = "Cannot reach the API. Is the backend running and CORS configured?";
      } else if (status === 429) {
        message = "Too many attempts. Please try again later.";
      } else if (status === 403) {
        message = "You don't have permission to perform this action.";
      } else if (status === 401) {
        message = "Your session has expired. Please sign in again.";
      } else {
        message = error.message || "Something went wrong.";
      }
    }

    return {
      status,
      message,
      isRateLimited: status === 429,
      isForbidden: status === 403,
      isUnauthorized: status === 401,
      isNotFound: status === 404,
    };
  }

  if (error instanceof Error) {
    return {
      status: null,
      message: error.message,
      isRateLimited: false,
      isForbidden: false,
      isUnauthorized: false,
      isNotFound: false,
    };
  }

  return {
    status: null,
    message: "An unexpected error occurred.",
    isRateLimited: false,
    isForbidden: false,
    isUnauthorized: false,
    isNotFound: false,
  };
}

export function getErrorMessage(error: unknown): string {
  return parseApiError(error).message;
}
