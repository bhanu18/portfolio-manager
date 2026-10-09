import { Link } from "react-router-dom";
import "../styles/modernist.css";

export function NotFoundPage() {
  return (
    // Rendered outside <Layout>, so it carries its own `.mod` scope.
    <div className="mod" style={{ minHeight: "100vh", paddingTop: "var(--space-8)" }}>
      <div className="container">
        <div className="page">
          <div className="empty-state">
            <h1 className="page__title">Page not found</h1>
            <p className="muted">The page you're looking for doesn't exist.</p>
            <Link to="/overview" className="btn btn--primary">
              Go to overview
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
