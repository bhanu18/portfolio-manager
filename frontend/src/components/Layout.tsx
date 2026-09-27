import { Outlet } from "react-router-dom";
import { ModernistNav } from "./ModernistNav";
import "../styles/modernist.css";

/** App shell for authenticated pages: Modernist top nav + routed content.
 *
 *  The `.mod` class scopes the Modernist design system to the shell. The
 *  "legacy bridge" section at the end of modernist.css re-points the old dark
 *  theme's tokens at Modernist values, so pages inside still render coherently
 *  while they are ported page by page. */
export function Layout() {
  return (
    <div className="mod app-shell">
      <ModernistNav />
      <main className="app-main">
        <div className="container">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
