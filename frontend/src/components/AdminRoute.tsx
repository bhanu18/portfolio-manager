// ---------------------------------------------------------------------------
// Admin-only route guard. Nest inside <ProtectedRoute> (which handles login and
// session restore). This is UX only — the API enforces admin access itself.
// ---------------------------------------------------------------------------

import { Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ErrorState } from "./ErrorState";

export function AdminRoute() {
  const { isAdmin } = useAuth();
  if (!isAdmin) {
    return <ErrorState message="This page is only available to administrators." />;
  }
  return <Outlet />;
}
