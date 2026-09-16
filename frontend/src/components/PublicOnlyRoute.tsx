// ---------------------------------------------------------------------------
// Inverse guard for auth pages (login/register/etc): if the user is already
// authenticated, send them to the app instead of showing the auth screens.
// ---------------------------------------------------------------------------

import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Spinner } from "./Spinner";

export function PublicOnlyRoute() {
  const { isAuthenticated, initializing } = useAuth();

  if (initializing) {
    return <Spinner block label="Loading…" />;
  }

  if (isAuthenticated) {
    return <Navigate to="/assets" replace />;
  }

  return <Outlet />;
}
