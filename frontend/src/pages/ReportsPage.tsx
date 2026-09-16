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
        <div className="report-tabs" role="tablist">
          <NavLink
            to="/reports/valuation"
            className={({ isActive }) =>
              isActive ? "report-tab report-tab--active" : "report-tab"
            }
            role="tab"
          >
            Asset Valuation
          </NavLink>
          <NavLink
            to="/reports/performance"
            className={({ isActive }) =>
              isActive ? "report-tab report-tab--active" : "report-tab"
            }
            role="tab"
          >
            Portfolio Performance
          </NavLink>
        </div>

        {/* Redirect /reports → /reports/valuation */}
        {atRoot && <Navigate to="/reports/valuation" replace />}

        {/* Child route renders here */}
        <Outlet />
      </div>
    </div>
  );
}
