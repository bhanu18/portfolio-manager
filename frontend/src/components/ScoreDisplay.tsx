import { useState } from "react";
import type { Score } from "../types";

interface ScoreDisplayProps {
  score: Score | null | undefined;
  compact?: boolean;
  expandable?: boolean;
}

/**
 * Displays a risk-adjusted performance score (composite + grade).
 * - `compact`: true → badge only (grade + number), false → full metrics breakdown
 * - `expandable`: true → render clickable, toggle expanded state
 */
export function ScoreDisplay({
  score,
  compact = true,
  expandable = true,
}: ScoreDisplayProps) {
  const [expanded, setExpanded] = useState(false);

  // Score is null or not available
  if (!score || score.composite_score === null) {
    return (
      <div className="score-display score-display--unavailable">
        <span className="score-display__placeholder">—</span>
        <span className="score-display__label">Not scored</span>
      </div>
    );
  }

  const handleClick = () => {
    if (expandable) setExpanded(!expanded);
  };

  // Helper: format metric values
  const formatMetric = (value: number | null, suffix: string = ""): string => {
    if (value === null) return "—";
    if (suffix === "%") return `${(value * 100).toFixed(2)}%`;
    if (suffix === "") return value.toFixed(4);
    return `${value.toFixed(2)}${suffix}`;
  };

  return (
    <div
      className={`score-display ${expandable ? "score-display--clickable" : ""} ${
        expanded ? "score-display--expanded" : ""
      }`}
      onClick={handleClick}
      role={expandable ? "button" : undefined}
      tabIndex={expandable ? 0 : undefined}
      onKeyDown={(e) => {
        if (expandable && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          setExpanded(!expanded);
        }
      }}
    >
      {/* Badge (always visible) */}
      <div className="score-display__badge">
        <div className={`score-display__grade score-display__grade--${score.grade?.toLowerCase()}`}>
          {score.grade}
        </div>
        <div className="score-display__composite">
          <span className="score-display__composite-value">{score.composite_score.toFixed(0)}</span>
          <span className="score-display__composite-max">/ 100</span>
        </div>
      </div>

      {/* Data quality indicator */}
      {score.short_history && (
        <div className="score-display__flag">
          {score.insufficient_history ? "(insufficient data)" : "(limited data)"}
        </div>
      )}

      {/* Expanded metrics (conditional) */}
      {expanded && !compact && (
        <div className="score-display__details">
          <div className="score-display__metrics">
            <h4 className="score-display__metrics-title">Performance Metrics</h4>
            <div className="score-display__metrics-grid">
              <div className="score-display__metric">
                <span className="score-display__metric-label">CAGR:</span>
                <span className="score-display__metric-value">
                  {formatMetric(score.metrics.cagr, "%")}
                </span>
              </div>
              <div className="score-display__metric">
                <span className="score-display__metric-label">Volatility:</span>
                <span className="score-display__metric-value">
                  {formatMetric(score.metrics.volatility, "%")}
                </span>
              </div>
              <div className="score-display__metric">
                <span className="score-display__metric-label">Max Drawdown:</span>
                <span className="score-display__metric-value">
                  {formatMetric(score.metrics.max_drawdown, "%")}
                </span>
              </div>
            </div>

            <h4 className="score-display__metrics-title">Risk-Adjusted Metrics</h4>
            <div className="score-display__metrics-grid">
              <div className="score-display__metric">
                <span className="score-display__metric-label">Sharpe Ratio:</span>
                <span className="score-display__metric-value">
                  {formatMetric(score.metrics.sharpe)}
                </span>
              </div>
              <div className="score-display__metric">
                <span className="score-display__metric-label">Sortino Ratio:</span>
                <span className="score-display__metric-value">
                  {formatMetric(score.metrics.sortino)}
                </span>
              </div>
              <div className="score-display__metric">
                <span className="score-display__metric-label">Beta:</span>
                <span className="score-display__metric-value">
                  {formatMetric(score.metrics.beta)}
                </span>
              </div>
              <div className="score-display__metric">
                <span className="score-display__metric-label">Alpha:</span>
                <span className="score-display__metric-value">
                  {formatMetric(score.metrics.alpha, "%")}
                </span>
              </div>
            </div>

            <div className="score-display__data-quality">
              <p className="score-display__sample">Sample Days: {score.sample_days}</p>
              {score.insufficient_history && (
                <p className="score-display__warning">
                  ⚠ Insufficient data (&lt;30 trading days). Volatility-based metrics are not reliable.
                </p>
              )}
              {score.short_history && !score.insufficient_history && (
                <p className="score-display__warning">
                  ⚠ Limited data (&lt;60 trading days). Results are directionally useful but less
                  statistically reliable.
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
