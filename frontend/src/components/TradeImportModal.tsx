import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { importTrades } from "../api/trades";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { parseApiError } from "../lib/errors";
import type { Group, TradeImportResult } from "../types";
import { Modal } from "./Modal";

const FIELD_LABELS: Record<string, string> = {
  symbol: "Symbol",
  trade_date: "Trade date",
  quantity: "Quantity",
  price: "Price",
  side: "Buy/sell",
  fee: "Fee",
  currency: "Currency",
  broker_ref: "Reference",
};

interface TradeImportModalProps {
  groups: Group[];
  defaultGroupId: number | null;
  onClose: () => void;
}

/**
 * Upload a Yahoo Finance portfolio export. "Preview" runs a dry run; "Import"
 * commits it. Mounted only while open, so every opening starts from a clean form.
 */
export function TradeImportModal({ groups, defaultGroupId, onClose }: TradeImportModalProps) {
  const toast = useToast();
  const client = useQueryClient();
  const { refreshUser } = useAuth();
  const [groupId, setGroupId] = useState<number | null>(defaultGroupId);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<TradeImportResult | null>(null);

  const mutation = useMutation({
    mutationFn: ({ dryRun }: { dryRun: boolean }) => importTrades(file!, groupId!, dryRun),
    onSuccess: (result) => {
      if (result.dry_run) {
        setPreview(result);
        return;
      }
      toast.success(
        `Imported: ${result.inserted} new, ${result.updated} updated, ${result.unchanged} unchanged.`,
      );
      for (const key of ["trades", "assets", "asset", "performance", "overview"]) {
        void client.invalidateQueries({ queryKey: [key] });
      }
      onClose();
    },
    onError: (error) => {
      const parsed = parseApiError(error);
      toast.error(parsed.message);
      if (parsed.isForbidden) void refreshUser();
    },
  });

  const busy = mutation.isPending;
  const ready = file !== null && groupId !== null;
  const changesSomething = preview !== null && preview.inserted + preview.updated > 0;

  return (
    <Modal
      open
      title="Import trades from Yahoo Finance"
      onClose={() => {
        if (!busy) onClose();
      }}
      footer={
        <>
          <button type="button" className="btn btn--ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          {preview ? (
            <button
              type="button"
              className="btn btn--primary"
              disabled={busy || !changesSomething}
              onClick={() => mutation.mutate({ dryRun: false })}
            >
              {busy ? "Importing…" : "Import"}
            </button>
          ) : (
            <button
              type="button"
              className="btn btn--primary"
              disabled={busy || !ready}
              onClick={() => mutation.mutate({ dryRun: true })}
            >
              {busy ? "Reading file…" : "Preview"}
            </button>
          )}
        </>
      }
    >
      <p className="field__hint">
        In Yahoo Finance, open your portfolio and choose Export to download a CSV. Re-importing the
        same file updates existing trades instead of duplicating them.
      </p>
      <div className="grid grid--2">
        <div className="field">
          <label htmlFor="import-file" className="field__label">
            File (.csv, .xlsx)
          </label>
          <input
            id="import-file"
            className="field__input"
            type="file"
            accept=".csv,.xlsx,.xls"
            disabled={busy}
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setPreview(null);
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="import-group" className="field__label">
            Group
          </label>
          <select
            id="import-group"
            className="field__input"
            value={groupId ?? ""}
            disabled={busy}
            onChange={(e) => {
              setGroupId(e.target.value ? Number(e.target.value) : null);
              setPreview(null);
            }}
          >
            <option value="">Choose a group</option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {preview && (
        <section className="trade-preview" aria-label="Import preview" aria-live="polite">
          <strong>Preview</strong>
          <p>
            {preview.inserted} new · {preview.updated} updated · {preview.unchanged} unchanged
            {preview.skipped > 0 && ` · ${preview.skipped} skipped`}
          </p>
          {preview.mapping && (
            <p className="field__hint">
              Columns mapped by the local model:{" "}
              {Object.entries(preview.mapping)
                .map(([field, column]) => `${FIELD_LABELS[field] ?? field} ← “${column}”`)
                .join(", ")}
              . Check the counts before importing.
            </p>
          )}
          {preview.assets_created.length > 0 && (
            <p>New assets to create: {preview.assets_created.join(", ")}</p>
          )}
          {preview.changes.length > 0 && (
            <details>
              <summary>{preview.changes.length} changed trades</summary>
              <ul>
                {preview.changes.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </details>
          )}
          {preview.warnings.length > 0 && (
            <details>
              <summary>{preview.warnings.length} warnings</summary>
              <ul>
                {preview.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </details>
          )}
          {!changesSomething && <p className="field__hint">Nothing new to import.</p>}
        </section>
      )}
    </Modal>
  );
}
