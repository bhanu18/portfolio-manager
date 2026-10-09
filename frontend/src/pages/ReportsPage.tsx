// ---------------------------------------------------------------------------
// Reports hub — /reports
// Tab bar that routes to /reports/valuation and /reports/performance.
// ---------------------------------------------------------------------------

import { NavLink, Navigate, Outlet, useMatch } from "react-router-dom";

export function ReportsPage() {
  const atRoot = useMatch("/reports");

  return (
    <div className="container">
      <div className="page">
        <h1 className="page__title">Reports</h1>

        {/* Tab nav */}
        <nav className="report-tabs" aria-label="Report type">
          <NavLink
            to="/reports/valuation"
            className={({ isActive }) =>
              isActive ? "report-tab report-tab--active" : "report-tab"
            }
          >
            Asset Valuation
          </NavLink>
          <NavLink
            to="/reports/performance"
            className={({ isActive }) =>
              isActive ? "report-tab report-tab--active" : "report-tab"
            }
          >
            Portfolio Performance
          </NavLink>
        </nav>

        {/* Redirect /reports → /reports/performance */}
        {atRoot && <Navigate to="/reports/performance" replace />}

        {/* Child route renders here */}
        <Outlet />
      </div>
    </div>
  );
}
