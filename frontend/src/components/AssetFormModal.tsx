// ---------------------------------------------------------------------------
// Create / edit asset modal (admin only). On create, the backend looks up a
// live price via yfinance, so only symbol/name/market/type are submitted.
// On edit, `type` is always sent (required by the AssetUpdate schema).
// ---------------------------------------------------------------------------

import { useEffect, useState, type FormEvent } from "react";
import { Modal } from "./Modal";
import type { Asset, AssetType } from "../types";
import { validateRequired } from "../lib/validation";

const ASSET_TYPES: AssetType[] = ["stock", "crypto", "cash", "etf"];

export interface AssetFormValues {
  symbol: string;
  name: string;
  market: string;
  type: AssetType;
}

interface AssetFormModalProps {
  open: boolean;
  /** When provided, the modal is in "edit" mode. */
  asset?: Asset | null;
  busy?: boolean;
  onCancel: () => void;
  onSubmit: (values: AssetFormValues) => void;
}

export function AssetFormModal({
  open,
  asset,
  busy = false,
  onCancel,
  onSubmit,
}: AssetFormModalProps) {
  const isEdit = Boolean(asset);

  const [values, setValues] = useState<AssetFormValues>({
    symbol: "",
    name: "",
    market: "",
    type: "stock",
  });
  const [errors, setErrors] = useState<Record<string, string | null>>({});

  // Reset form whenever the modal opens or the target asset changes.
  useEffect(() => {
    if (open) {
      setValues({
        symbol: asset?.symbol ?? "",
        name: asset?.name ?? "",
        market: asset?.market ?? "",
        type: asset?.type ?? "stock",
      });
      setErrors({});
    }
  }, [open, asset]);

  const update = <K extends keyof AssetFormValues>(
    key: K,
    value: AssetFormValues[K],
  ) => setValues((v) => ({ ...v, [key]: value }));

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const nextErrors: Record<string, string | null> = {
      symbol: validateRequired(values.symbol, "Symbol"),
      name: validateRequired(values.name, "Name"),
      market: validateRequired(values.market, "Market"),
    };
    setErrors(nextErrors);
    if (Object.values(nextErrors).some(Boolean)) return;

    onSubmit({
      symbol: values.symbol.trim().toUpperCase(),
      name: values.name.trim(),
      market: values.market.trim(),
      type: values.type,
    });
  };

  return (
    <Modal
      open={open}
      title={isEdit ? `Edit ${asset?.symbol}` : "Add asset"}
      onClose={onCancel}
      footer={
        <>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </button>
          <button
            type="submit"
            form="asset-form"
            className="btn btn--primary"
            disabled={busy}
          >
            {busy ? "Saving…" : isEdit ? "Save changes" : "Create asset"}
          </button>
        </>
      }
    >
      <form id="asset-form" onSubmit={handleSubmit} noValidate>
        <div className="field">
          <label htmlFor="asset-symbol" className="field__label">
            Symbol
          </label>
          <input
            id="asset-symbol"
            type="text"
            className="field__input"
            value={values.symbol}
            onChange={(e) => update("symbol", e.target.value)}
            placeholder="AAPL"
            aria-invalid={Boolean(errors.symbol)}
          />
          {errors.symbol && (
            <span className="field__error">{errors.symbol}</span>
          )}
        </div>

        <div className="field">
          <label htmlFor="asset-name" className="field__label">
            Name
          </label>
          <input
            id="asset-name"
            type="text"
            className="field__input"
            value={values.name}
            onChange={(e) => update("name", e.target.value)}
            placeholder="Apple Inc."
            aria-invalid={Boolean(errors.name)}
          />
          {errors.name && <span className="field__error">{errors.name}</span>}
        </div>

        <div className="field">
          <label htmlFor="asset-market" className="field__label">
            Market
          </label>
          <input
            id="asset-market"
            type="text"
            className="field__input"
            value={values.market}
            onChange={(e) => update("market", e.target.value)}
            placeholder="NASDAQ"
            aria-invalid={Boolean(errors.market)}
          />
          {errors.market && (
            <span className="field__error">{errors.market}</span>
          )}
        </div>

        <div className="field">
          <label htmlFor="asset-type" className="field__label">
            Type
          </label>
          <select
            id="asset-type"
            className="field__input"
            value={values.type}
            onChange={(e) => update("type", e.target.value as AssetType)}
          >
            {ASSET_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        {!isEdit && (
          <p className="muted small">
            The server fetches a live price automatically when the asset is
            created.
          </p>
        )}
      </form>
    </Modal>
  );
}
