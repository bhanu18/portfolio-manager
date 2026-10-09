// ---------------------------------------------------------------------------
// Create / edit trade modal.
//   - Create mode: requires a symbol (sent as a query param by the caller),
//     plus the full TradeCreate body. Includes a symbol "picker" that verifies
//     the asset exists by looking it up.
//   - Edit mode: symbol is not editable (the backend update takes no symbol);
//     all body fields are optional but we submit the edited values.
// ---------------------------------------------------------------------------

import { useEffect, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { money } from "../lib/overview";
import { Modal } from "./Modal";
import * as assetsApi from "../api/assets";
import * as tradesApi from "../api/trades";
import { isAsset } from "../api/assets";
import { getErrorMessage } from "../lib/errors";
import { formatNumber, toDateInputValue } from "../lib/format";
import { validatePositiveNumber, validateRequired } from "../lib/validation";
import type { Group, Trade, TradeType } from "../types";

export interface TradeFormResult {
  symbol: string | null; // present only in create mode
  values: {
    trade_type: TradeType;
    trade_date: string;
    quantity: number;
    price_per_unit: number;
    currency: string;
    group_id: number;
  };
}

interface TradeFormModalProps {
  open: boolean;
  trade?: Trade | null;
  groups: Group[];
  defaultGroupId: number | null;
  /** Used in edit mode to show which symbol the trade belongs to (read-only). */
  knownSymbol?: string | null;
  busy?: boolean;
  onCancel: () => void;
  onSubmit: (result: TradeFormResult) => void;
}

const TRADE_TYPES: TradeType[] = ["buy", "sell"];

export function TradeFormModal({
  open,
  trade,
  groups,
  defaultGroupId,
  knownSymbol,
  busy = false,
  onCancel,
  onSubmit,
}: TradeFormModalProps) {
  const isEdit = Boolean(trade);

  const [symbol, setSymbol] = useState("");
  const [tradeType, setTradeType] = useState<TradeType>("buy");
  const [tradeDate, setTradeDate] = useState("");
  const [quantity, setQuantity] = useState("");
  const [pricePerUnit, setPricePerUnit] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [groupId, setGroupId] = useState<number | "">("");
  const [errors, setErrors] = useState<Record<string, string | null>>({});

  // Symbol verification state (create mode).
  const [verifying, setVerifying] = useState(false);
  const [verifiedName, setVerifiedName] = useState<string | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  // Holdings summary fetched alongside verification.
  const groupTrades = useQuery({
    queryKey: ["trades", "group", groupId],
    queryFn: () => tradesApi.listTradesInGroup(Number(groupId)),
    enabled: open && groupId !== "",
    staleTime: 0,
  });
  const normalizedSymbol = symbol.trim().toUpperCase();
  const matchingTrades = groupTrades.data?.filter(
    (t) => t.id !== trade?.id && t.symbol?.toUpperCase() === normalizedSymbol,
  );
  const hasUnknownSymbols = groupTrades.data?.some((t) => !t.symbol);
  const holdingsQty =
    groupId !== "" && normalizedSymbol && matchingTrades && !hasUnknownSymbols
      ? matchingTrades.reduce(
          (sum, t) => sum + (t.trade_type === "buy" ? t.quantity : -t.quantity),
          0,
        )
      : null;
  const validNumbers =
    Number.isFinite(Number(quantity)) &&
    Number(quantity) > 0 &&
    Number.isFinite(Number(pricePerUnit)) &&
    Number(pricePerUnit) > 0;
  const resultingQuantity =
    holdingsQty === null || !validNumbers
      ? null
      : holdingsQty + (tradeType === "buy" ? Number(quantity) : -Number(quantity));

  useEffect(() => {
    if (!open) return;
    setSymbol(knownSymbol ?? "");
    setTradeType(trade?.trade_type ?? "buy");
    setTradeDate(
      trade ? toDateInputValue(trade.trade_date) : toDateInputValue(new Date().toISOString()),
    );
    setQuantity(trade ? String(trade.quantity) : "");
    setPricePerUnit(trade ? String(trade.price_per_unit) : "");
    setCurrency(trade?.currency ?? "USD");
    setGroupId(trade?.group_id ?? defaultGroupId ?? "");
    setErrors({});
    setVerifiedName(null);
    setVerifyError(null);
  }, [open, trade, knownSymbol, defaultGroupId]);

  const verifySymbol = async () => {
    const s = symbol.trim().toUpperCase();
    if (!s) return;
    setVerifying(true);
    setVerifyError(null);
    setVerifiedName(null);
    try {
      const result = await assetsApi.getAssetBySymbol(s);
      if (isAsset(result)) {
        setVerifiedName(result.name);
      } else {
        setVerifyError(result.error || `No asset found for "${s}".`);
      }
    } catch (err) {
      setVerifyError(getErrorMessage(err));
    } finally {
      setVerifying(false);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const nextErrors: Record<string, string | null> = {
      symbol: isEdit ? null : validateRequired(symbol, "Symbol"),
      tradeDate: validateRequired(tradeDate, "Trade date"),
      quantity: validatePositiveNumber(quantity, "Quantity"),
      pricePerUnit: validatePositiveNumber(pricePerUnit, "Price per unit"),
      currency: validateRequired(currency, "Currency"),
      groupId: groupId === "" ? "Group is required." : null,
    };
    setErrors(nextErrors);
    if (Object.values(nextErrors).some(Boolean)) return;

    onSubmit({
      symbol: isEdit ? null : symbol.trim().toUpperCase(),
      values: {
        trade_type: tradeType,
        // Send a full datetime so the backend's datetime field parses cleanly.
        trade_date: `${tradeDate}T00:00:00`,
        quantity: Number(quantity),
        price_per_unit: Number(pricePerUnit),
        currency: currency.trim().toUpperCase(),
        group_id: Number(groupId),
      },
    });
  };

  return (
    <Modal
      open={open}
      title={isEdit ? `Edit trade #${trade?.id}` : "Record trade"}
      onClose={() => {
        if (!busy) onCancel();
      }}
      footer={
        <>
          <button type="button" className="btn btn--ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button type="submit" form="trade-form" className="btn btn--primary" disabled={busy}>
            {busy ? "Saving…" : isEdit ? "Save changes" : "Record trade"}
          </button>
        </>
      }
    >
      <form id="trade-form" onSubmit={handleSubmit} noValidate>
        <div className="field">
          <label htmlFor="trade-symbol" className="field__label">
            Asset symbol
          </label>
          {isEdit ? (
            <input
              id="trade-symbol"
              type="text"
              className="field__input"
              value={knownSymbol ?? `Asset #${trade?.asset_id}`}
              readOnly
              disabled
            />
          ) : (
            <>
              <div className="input-row">
                <input
                  id="trade-symbol"
                  type="text"
                  className="field__input"
                  placeholder="AAPL"
                  value={symbol}
                  onChange={(e) => {
                    setSymbol(e.target.value);
                    setVerifiedName(null);
                    setVerifyError(null);
                  }}
                  onBlur={verifySymbol}
                  aria-invalid={Boolean(errors.symbol)}
                />
                <button
                  type="button"
                  className="btn btn--secondary"
                  onClick={verifySymbol}
                  disabled={verifying || symbol.trim().length === 0}
                >
                  {verifying ? "Checking…" : "Verify"}
                </button>
              </div>
              {errors.symbol && <span className="field__error">{errors.symbol}</span>}
              {verifiedName && (
                <span className="field__hint field__hint--ok">✓ {verifiedName}</span>
              )}
              {verifyError && <span className="field__hint field__hint--warn">{verifyError}</span>}
            </>
          )}
        </div>

        <div className="grid grid--2">
          <div className="field">
            <label htmlFor="trade-type" className="field__label">
              Type
            </label>
            <select
              id="trade-type"
              className="field__input"
              value={tradeType}
              onChange={(e) => setTradeType(e.target.value as TradeType)}
            >
              {TRADE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="trade-date" className="field__label">
              Date
            </label>
            <input
              id="trade-date"
              type="date"
              className="field__input"
              value={tradeDate}
              onChange={(e) => setTradeDate(e.target.value)}
              aria-invalid={Boolean(errors.tradeDate)}
            />
            {errors.tradeDate && <span className="field__error">{errors.tradeDate}</span>}
          </div>
        </div>

        <div className="grid grid--2">
          <div className="field">
            <label htmlFor="trade-qty" className="field__label">
              Quantity
            </label>
            <input
              id="trade-qty"
              type="number"
              step="any"
              min="0"
              className="field__input"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              aria-invalid={Boolean(errors.quantity)}
            />
            {errors.quantity && <span className="field__error">{errors.quantity}</span>}
          </div>

          <div className="field">
            <label htmlFor="trade-price" className="field__label">
              Price per unit
            </label>
            <input
              id="trade-price"
              type="number"
              step="any"
              min="0"
              className="field__input"
              value={pricePerUnit}
              onChange={(e) => setPricePerUnit(e.target.value)}
              aria-invalid={Boolean(errors.pricePerUnit)}
            />
            {errors.pricePerUnit && <span className="field__error">{errors.pricePerUnit}</span>}
          </div>
        </div>

        <div className="grid grid--2">
          <div className="field">
            <label htmlFor="trade-currency" className="field__label">
              Currency
            </label>
            <input
              id="trade-currency"
              type="text"
              className="field__input"
              placeholder="USD"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              aria-invalid={Boolean(errors.currency)}
            />
            {errors.currency && <span className="field__error">{errors.currency}</span>}
          </div>

          <div className="field">
            <label htmlFor="trade-group" className="field__label">
              Group
            </label>
            <select
              id="trade-group"
              className="field__input"
              value={groupId}
              onChange={(e) => setGroupId(e.target.value === "" ? "" : Number(e.target.value))}
              aria-invalid={Boolean(errors.groupId)}
            >
              <option value="">Select a group…</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
            {errors.groupId && <span className="field__error">{errors.groupId}</span>}
          </div>
        </div>
        <section className="trade-preview" aria-label="Trade preview" aria-live="polite">
          <strong>{tradeType === "buy" ? "Purchase total" : "Sale proceeds"}</strong>
          <p>
            {validNumbers
              ? `${money(Number(quantity) * Number(pricePerUnit), currency.trim().toUpperCase())} ${currency.trim().toUpperCase()}`
              : "Enter quantity and price to preview the total."}
          </p>
          <p className="field__hint">
            Excludes fees and taxes. This records a trade; it does not place an order.
          </p>
          {holdingsQty !== null ? (
            <>
              <p>
                {isEdit ? "Position excluding this trade" : "Current position"} in{" "}
                {groups.find((g) => g.id === groupId)?.name}: {formatNumber(holdingsQty)} units
              </p>
              {!isEdit && tradeType === "sell" && holdingsQty > 0 && (
                <div className="input-row">
                  {[25, 50, 100].map((percent) => (
                    <button
                      key={percent}
                      type="button"
                      className="btn btn--secondary"
                      disabled={busy}
                      onClick={() => setQuantity(String((holdingsQty * percent) / 100))}
                    >
                      {percent === 100 ? "Sell all" : `Sell ${percent}%`}
                    </button>
                  ))}
                </div>
              )}
              {resultingQuantity !== null && (
                <p>
                  Position after saving: <strong>{formatNumber(resultingQuantity)} units</strong>
                </p>
              )}
              {resultingQuantity !== null && resultingQuantity < 0 && (
                <p className="field__hint field__hint--warn">
                  This would leave a negative position in this group. Check the quantity and trade
                  history.
                </p>
              )}
            </>
          ) : (
            <p className="field__hint">
              {groupId === ""
                ? "Select a group to preview your position."
                : groupTrades.isFetching
                  ? "Loading group position…"
                  : "Group position unavailable."}
            </p>
          )}
        </section>
      </form>
    </Modal>
  );
}
