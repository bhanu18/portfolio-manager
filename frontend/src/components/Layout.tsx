import { Outlet } from "react-router-dom";
import { Navbar } from "./Navbar";

/** App shell for authenticated pages: navbar + routed content. */
export function Layout() {
  return (
    <div className="app-shell">
      <Navbar />
      <main className="app-main">
        <div className="container">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
