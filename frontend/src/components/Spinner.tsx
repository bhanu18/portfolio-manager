interface SpinnerProps {
  label?: string;
  /** Renders a larger, centered block suitable for full-page loading. */
  block?: boolean;
}

export function Spinner({ label = "Loading…", block = false }: SpinnerProps) {
  return (
    <div className={block ? "spinner-block" : "spinner-inline"} role="status">
      <span className="spinner" aria-hidden="true" />
      <span className={block ? "" : "sr-only"}>{label}</span>
    </div>
  );
}
