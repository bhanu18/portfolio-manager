import { useState } from "react";
import type { ScoringWarning } from "../types";

interface ScoringWarningsBannerProps {
  warnings: ScoringWarning[] | undefined;
}

/**
 * Displays scoring warnings in a dismissible banner.
 * Shows a compact view with count, expandable for details.
 */
export function ScoringWarningsBanner({ warnings }: ScoringWarningsBannerProps) {
  const [dismissed, setDismissed] = useState(false);
  const [expanded, setExpanded] = useState(false);

  if (!warnings || warnings.length === 0 || dismissed) {
    return null;
  }

  const portfolioWarnings = warnings.filter((w) => w.ticker === null);
  const holdingWarnings = warnings.filter((w) => w.ticker !== null);

  return (
    <div className="scoring-warnings-banner">
      <div className="scoring-warnings-banner__header">
        <button
          className="scoring-warnings-banner__toggle"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
        >
          <span className="scoring-warnings-banner__icon">ⓘ</span>
          <span className="scoring-warnings-banner__title">
            {warnings.length} scoring {warnings.length === 1 ? "warning" : "warnings"}
          </span>
          <span className={`scoring-warnings-banner__caret ${expanded ? "scoring-warnings-banner__caret--open" : ""}`}>
            ▼
          </span>
        </button>
        <button
          className="scoring-warnings-banner__dismiss"
          onClick={() => setDismissed(true)}
          aria-label="Dismiss warnings"
          title="Dismiss"
        >
          ✕
        </button>
      </div>

      {expanded && (
        <div className="scoring-warnings-banner__details">
          {portfolioWarnings.length > 0 && (
            <div className="scoring-warnings-banner__section">
              <h4 className="scoring-warnings-banner__section-title">Portfolio</h4>
              <ul className="scoring-warnings-banner__list">
                {portfolioWarnings.map((warning, idx) => (
                  <li key={idx} className="scoring-warnings-banner__item">
                    {warning.message}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {holdingWarnings.length > 0 && (
            <div className="scoring-warnings-banner__section">
              <h4 className="scoring-warnings-banner__section-title">Holdings</h4>
              <ul className="scoring-warnings-banner__list">
                {holdingWarnings.map((warning, idx) => (
                  <li key={idx} className="scoring-warnings-banner__item">
                    <strong>{warning.ticker}:</strong> {warning.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
