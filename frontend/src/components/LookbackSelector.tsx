interface LookbackSelectorProps {
  currentLookback: string;
  onLookbackChange: (period: string) => void;
  loading?: boolean;
}

const LOOKBACK_OPTIONS = [
  { value: "1mo", label: "1 month" },
  { value: "3mo", label: "3 months" },
  { value: "6mo", label: "6 months" },
  { value: "1y", label: "1 year" },
  { value: "2y", label: "2 years" },
];

/**
 * Selector for risk-adjusted score lookback window.
 * Allows users to re-fetch scores with different historical windows.
 */
export function LookbackSelector({
  currentLookback,
  onLookbackChange,
  loading = false,
}: LookbackSelectorProps) {
  return (
    <div className="lookback-selector">
      <label htmlFor="lookback-select" className="lookback-selector__label">
        Risk-Adjusted Metrics Lookback:
      </label>
      <select
        id="lookback-select"
        value={currentLookback}
        onChange={(e) => onLookbackChange(e.target.value)}
        disabled={loading}
        className="lookback-selector__select"
      >
        {LOOKBACK_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {loading && <span className="lookback-selector__loading">Updating scores...</span>}
      <p className="lookback-selector__note">
        (Re-fetches scores independently; existing FIFO metrics unchanged)
      </p>
    </div>
  );
}
