// ---------------------------------------------------------------------------
// Global auth state: holds the current user + token status, exposes
// login/register/logout, and listens for the apiClient's "unauthorized"
// event to force a logout when the token expires.
// ---------------------------------------------------------------------------

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import * as authApi from "../api/auth";
import { UNAUTHORIZED_EVENT } from "../lib/apiClient";
import { clearToken, getToken, setToken } from "../lib/token";
import type { User } from "../types";

interface AuthContextValue {
  user: User | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  /** True only during the initial "restore session from stored token" check. */
  initializing: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [initializing, setInitializing] = useState(true);

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
  }, []);

  const refreshUser = useCallback(async () => {
    const me = await authApi.getMe();
    setUser(me);
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const { access_token } = await authApi.login(email, password);
      setToken(access_token);
      try {
        await refreshUser();
      } catch (err) {
        // If profile fetch fails right after login, don't leave a half-state.
        clearToken();
        setUser(null);
        throw err;
      }
    },
    [refreshUser],
  );

  const register = useCallback(
    async (name: string, email: string, password: string) => {
      await authApi.register({ name, email, password });
      // Convenience: log the user straight in after a successful registration.
      await login(email, password);
    },
    [login],
  );

  // Restore session on first mount if a token is already stored.
  useEffect(() => {
    let cancelled = false;
    async function restore() {
      if (!getToken()) {
        setInitializing(false);
        return;
      }
      try {
        const me = await authApi.getMe();
        if (!cancelled) setUser(me);
      } catch {
        clearToken();
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setInitializing(false);
      }
    }
    void restore();
    return () => {
      cancelled = true;
    };
  }, []);

  // React to a 401 from anywhere in the app: drop the session.
  useEffect(() => {
    const handler = () => {
      setUser(null);
    };
    window.addEventListener(UNAUTHORIZED_EVENT, handler);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, handler);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: user !== null,
      isAdmin: user?.role === "admin",
      initializing,
      login,
      register,
      logout,
      refreshUser,
    }),
    [user, initializing, login, register, logout, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
