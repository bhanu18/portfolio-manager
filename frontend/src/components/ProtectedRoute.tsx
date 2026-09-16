// ---------------------------------------------------------------------------
// Route guard. Redirects unauthenticated users to /login (preserving the
// attempted location), and waits for the initial session-restore to finish
// before deciding so we don't flash the login page on reload.
// ---------------------------------------------------------------------------

import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Spinner } from "./Spinner";

export function ProtectedRoute() {
  const { isAuthenticated, initializing } = useAuth();
  const location = useLocation();

  if (initializing) {
    return <Spinner block label="Restoring your session…" />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
