import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="page">
      <div className="empty-state">
        <h1 className="page__title">Page not found</h1>
        <p className="muted">The page you're looking for doesn't exist.</p>
        <Link to="/assets" className="btn btn--primary">
          Go to assets
        </Link>
      </div>
    </div>
  );
}
