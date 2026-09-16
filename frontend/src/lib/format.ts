// ---------------------------------------------------------------------------
// Display formatting helpers.
// ---------------------------------------------------------------------------

export function formatPrice(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  });
}

export function formatNumber(value: number): string {
  return value.toLocaleString(undefined, {
    maximumFractionDigits: 8,
  });
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString();
}

/** Convert an ISO datetime to a value usable by <input type="date">. */
export function toDateInputValue(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 10);
}

/**
 * Returns a short currency prefix/symbol for display.
 * Falls back to the ISO code itself (e.g. "THB ") when no known symbol exists.
 */
export function currencyPrefix(currency: string | null | undefined): string {
  if (!currency) return "$";
  switch (currency.toUpperCase()) {
    case "USD":
      return "$";
    case "EUR":
      return "€";
    case "GBP":
      return "£";
    case "JPY":
      return "¥";
    case "CNY":
      return "¥";
    case "INR":
      return "₹";
    case "KRW":
      return "₩";
    case "BTC":
      return "₿";
    default:
      return currency.toUpperCase() + " ";
  }
}

/**
 * Format a monetary value with the correct currency prefix.
 * e.g. formatValue(34.5, "THB") → "THB 34.50"
 *      formatValue(184.9, "USD") → "$184.90"
 */
export function formatValue(
  value: number | null | undefined,
  currency: string | null | undefined,
): string {
  if (value == null) return "—";
  return currencyPrefix(currency) + formatPrice(value);
}
