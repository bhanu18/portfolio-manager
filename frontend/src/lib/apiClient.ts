// ---------------------------------------------------------------------------
// Centralized, typed axios instance shared by all resource modules.
//
//  - Attaches the Bearer token on every request (from token storage).
//  - On 401 it clears the token and dispatches a global "auth:unauthorized"
//    event so the AuthProvider can redirect to /login. (403 is intentionally
//    NOT handled here — pages surface permission errors inline.)
// ---------------------------------------------------------------------------

import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";
import { getToken, clearToken } from "./token";

const DEFAULT_BASE_URL = "http://localhost:8000";

function resolveBaseUrl(): string {
  const fromEnv = import.meta.env.VITE_API_BASE_URL?.trim();
  const base = fromEnv && fromEnv.length > 0 ? fromEnv : DEFAULT_BASE_URL;
  // Strip any trailing slash so we can safely concatenate paths.
  return base.replace(/\/+$/, "");
}

export const API_BASE_URL = resolveBaseUrl();

/** Event name dispatched on window when the API reports an expired/invalid token. */
export const UNAUTHORIZED_EVENT = "auth:unauthorized";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getToken();
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      clearToken();
      // Let the app react (redirect to login) without coupling axios to React.
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
      }
    }
    return Promise.reject(error);
  },
);
