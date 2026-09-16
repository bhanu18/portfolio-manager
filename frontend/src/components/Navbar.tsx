import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export function Navbar() {
  const { user, isAdmin, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    isActive ? "navbar__link navbar__link--active" : "navbar__link";

  return (
    <header className="navbar">
      <div className="navbar__inner">
        <NavLink to="/portfolio" className="navbar__brand">
          📈 Portfolio Tracker
        </NavLink>

        <nav className="navbar__links" aria-label="Primary">
          <NavLink to="/portfolio" className={linkClass}>
            Portfolio
          </NavLink>
          <NavLink to="/reports" className={linkClass}>
            Reports
          </NavLink>
          <NavLink to="/profile" className={linkClass}>
            Profile
          </NavLink>
        </nav>

        <div className="navbar__user">
          {user && (
            <span className="navbar__greeting">
              {user.name}
              {isAdmin && <span className="badge badge--admin">admin</span>}
            </span>
          )}
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={handleLogout}
          >
            Log out
          </button>
        </div>
      </div>
    </header>
  );
}
