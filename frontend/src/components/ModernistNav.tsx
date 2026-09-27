// ---------------------------------------------------------------------------
// ModernistNav — the app's single top nav.
//
// Implements the `.nav` chrome from docs/frontend/Portfolio Dashboard
// (Modernist).dc.html. It replaces the old dark <Navbar>: every authenticated
// page now carries this nav, either through <Layout> or (for the pages that own
// their own chrome) by rendering it directly.
//
// It must sit inside a `.mod` wrapper — every rule in modernist.css is scoped
// there. <Layout> provides that wrapper for routed pages.
//
// `children` render between the links and the right-hand spacer, which is where
// the design puts page-level chrome (the base-currency / benchmark tags and the
// "Refresh prices" button on Overview).
// ---------------------------------------------------------------------------

import type { ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";

/** NavLink already sets aria-current="page" when active, which is what the
 *  design's active-link rule keys off — no className juggling needed. */
const LINKS = [
  { to: "/overview", label: "Overview" },
  { to: "/holdings", label: "Holdings" },
  { to: "/reports", label: "Reports" },
  { to: "/profile", label: "Profile" },
];

export function ModernistNav({ children }: { children?: ReactNode }) {
  const { user, isAdmin, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="nav">
      <Link to="/holdings" className="nav-brand">
        Portfolio
      </Link>

      {LINKS.map((link) => (
        <NavLink key={link.to} to={link.to}>
          {link.label}
        </NavLink>
      ))}

      {children}

      <span className="nav-spacer" />

      {user && (
        <span className="fig nav-user">
          {user.name}
          {isAdmin && <span className="tag tag-outline nav-user__badge">admin</span>}
        </span>
      )}
      <button type="button" className="btn btn-ghost" onClick={handleLogout}>
        Log out
      </button>
    </div>
  );
}
