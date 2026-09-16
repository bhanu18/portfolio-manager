// ---------------------------------------------------------------------------
// Asset Valuation report — /reports/valuation
// Users can run multiple valuations on the same page without navigating away.
// ---------------------------------------------------------------------------

import { useState } from "react";
import { getValuation } from "../api/reports";
import { parseApiError } from "../lib/errors";
import { formatNumber } from "../lib/format";
import type { ValuationReport } from "../types";

// Common currencies presented as quick-select options; user can also free-type.
const COMMON_CURRENCIES = ["USD", "THB", "EUR", "GBP", "JPY", "SGD"];

interface ValuationResult {
  id: number;
  symbol: string;
  currency: string;
  data: ValuationReport;
}

let nextId = 1;

export function ValuationPage() {
  const [symbol, setSymbol] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [customCurrency, setCustomCurrency] = useState("");
  const [symbolError, setSymbolError] = useState<string | null>(null);
  const [currencyError, setCurrencyError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<ValuationResult[]>([]);
  const [runError, setRunError] = useState<string | null>(null);

  const effectiveCurrency =
    currency === "__custom__" ? customCurrency.trim().toUpperCase() : currency;

  function validate(): boolean {
    let ok = true;
    if (!symbol.trim()) {
      setSymbolError("Symbol is required (e.g. AAPL).");
      ok = false;
    } else {
      setSymbolError(null);
    }
    if (!effectiveCurrency) {
      setCurrencyError("Please enter a currency code.");
      ok = false;
    } else {
      setCurrencyError(null);
    }
    return ok;
  }

  async function handleRun() {
    if (!validate()) return;
    setRunError(null);
    setLoading(true);
    try {
      const data = await getValuation(symbol.trim().toUpperCase(), effectiveCurrency);
      setResults((prev) => [
        { id: nextId++, symbol: symbol.trim().toUpperCase(), currency: effectiveCurrency, data },
        ...prev,
      ]);
    } catch (err) {
      const parsed = parseApiError(err);
      if (parsed.status === 503) {
        setRunError("Exchange rate service is temporarily unavailable. Please try again later.");
      } else if (parsed.status === 404) {
        setRunError(parsed.message || "Asset not found or no trades recorded for this symbol.");
      } else {
        setRunError(parsed.message);
      }
    } finally {
      setLoading(false);
    }
  }

  function dismissResult(id: number) {
    setResults((prev) => prev.filter((r) => r.id !== id));
  }

  return (
    <div className="page" style={{ gap: "1.5rem" }}>
      {/* Input form */}
      <div className="card">
        <h2 className="card__title">Asset Valuation</h2>
        <p className="muted small" style={{ marginBottom: "1.25rem" }}>
          Look up the current value and P&amp;L of any asset you hold, converted to your chosen
          currency.
        </p>

        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "flex-end" }}>
          {/* Symbol */}
          <div className="field" style={{ flex: "1 1 160px", marginBottom: 0 }}>
            <label className="field__label" htmlFor="val-symbol">
              Symbol <span aria-hidden>*</span>
            </label>
            <input
              id="val-symbol"
              className="field__input"
              aria-invalid={symbolError ? "true" : undefined}
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleRun()}
              placeholder="e.g. AAPL"
            />
            {symbolError && <span className="field__error">{symbolError}</span>}
          </div>

          {/* Currency quick-select */}
          <div className="field" style={{ flex: "1 1 160px", marginBottom: 0 }}>
            <label className="field__label" htmlFor="val-currency">
              Target currency <span aria-hidden>*</span>
            </label>
            <select
              id="val-currency"
              className="field__input"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
            >
              {COMMON_CURRENCIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
              <option value="__custom__">Other…</option>
            </select>
          </div>

          {/* Free-text currency fallback */}
          {currency === "__custom__" && (
            <div className="field" style={{ flex: "1 1 120px", marginBottom: 0 }}>
              <label className="field__label" htmlFor="val-currency-custom">
                Currency code
              </label>
              <input
                id="val-currency-custom"
                className="field__input"
                aria-invalid={currencyError ? "true" : undefined}
                value={customCurrency}
                onChange={(e) => setCustomCurrency(e.target.value)}
                placeholder="e.g. CHF"
                maxLength={8}
              />
              {currencyError && <span className="field__error">{currencyError}</span>}
            </div>
          )}

          <button
            type="button"
            className="btn btn--primary"
            onClick={handleRun}
            disabled={loading}
            style={{ flexShrink: 0, marginBottom: symbolError || currencyError ? "1.4rem" : 0 }}
          >
            {loading ? "Fetching…" : "Get Valuation"}
          </button>
        </div>

        {runError && (
          <div className="alert alert--error" style={{ marginTop: "1rem" }}>
            {runError}
          </div>
        )}
      </div>

      {/* Results (most recent on top) */}
      {results.map((r) => (
        <ValuationResultCard key={r.id} result={r} onDismiss={() => dismissResult(r.id)} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Individual result card
// ---------------------------------------------------------------------------

function ValuationResultCard({
  result,
  onDismiss,
}: {
  result: ValuationResult;
  onDismiss: () => void;
}) {
  const { data } = result;
  const pnl = data.performance.profit_loss_in_target_currency;
  const pnlPositive = pnl >= 0;

  return (
    <div className="card valuation-card">
      <div className="valuation-card__header">
        <div>
          <span className="valuation-card__symbol">{data.symbol}</span>
          <span className="muted small" style={{ marginLeft: "0.5rem" }}>
            native: {data.asset_native_currency} → {data.reporting_currency}
          </span>
        </div>
        <button type="button" className="modal__close" onClick={onDismiss} aria-label="Dismiss">
          &times;
        </button>
      </div>

      <div className="grid grid--2" style={{ marginTop: "1.25rem" }}>
        {/* Holdings */}
        <div>
          <p className="field__label">Holdings</p>
          <dl className="detail-list">
            <div className="detail-list__row">
              <dt>Quantity</dt>
              <dd>{formatNumber(data.holdings.quantity)}</dd>
            </div>
            <div className="detail-list__row">
              <dt>Avg cost (USD)</dt>
              <dd>{formatNumber(data.holdings.average_cost_usd)}</dd>
            </div>
          </dl>
        </div>

        {/* Valuation */}
        <div>
          <p className="field__label">Current Value</p>
          <dl className="detail-list">
            <div className="detail-list__row">
              <dt>In {data.asset_native_currency}</dt>
              <dd>{formatNumber(data.valuation.current_value_native)}</dd>
            </div>
            <div className="detail-list__row">
              <dt>In USD</dt>
              <dd>{formatNumber(data.valuation.current_value_usd)}</dd>
            </div>
            <div className="detail-list__row">
              <dt>In {data.reporting_currency}</dt>
              <dd>
                <strong>{formatNumber(data.valuation.current_value_in_target_currency)}</strong>
              </dd>
            </div>
          </dl>
        </div>

        {/* P&L */}
        <div>
          <p className="field__label">Performance ({data.reporting_currency})</p>
          <dl className="detail-list">
            <div className="detail-list__row">
              <dt>Total cost</dt>
              <dd>{formatNumber(data.performance.total_cost_in_target_currency)}</dd>
            </div>
            <div className="detail-list__row">
              <dt>P&amp;L</dt>
              <dd className={pnlPositive ? "pnl pnl--positive" : "pnl pnl--negative"}>
                {pnlPositive ? "+" : ""}
                {formatNumber(pnl)}
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </div>
  );
}
