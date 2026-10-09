import { useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createTrade } from "../api/trades";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { parseApiError } from "../lib/errors";
import { TradeFormModal, type TradeFormResult } from "./TradeFormModal";

export function RecordTradeButton({ onRecorded }: { onRecorded?: () => void }) {
  const [params, setParams] = useSearchParams();
  const open = params.get("recordTrade") === "1";
  const setOpen = (value: boolean) => {
    const next = new URLSearchParams(params);
    if (value) next.set("recordTrade", "1");
    else next.delete("recordTrade");
    setParams(next, { replace: !value });
  };
  const { user, refreshUser } = useAuth();
  const toast = useToast();
  const client = useQueryClient();
  const groups = user?.groups ?? [];
  const mutation = useMutation({
    mutationFn: (result: TradeFormResult) => createTrade(result.symbol!, result.values),
    onSuccess: () => {
      setOpen(false);
      toast.success("Trade recorded.");
      for (const key of ["trades", "assets", "asset", "performance", "overview"]) {
        void client.invalidateQueries({ queryKey: [key] });
      }
      onRecorded?.();
    },
    onError: (error) => {
      const parsed = parseApiError(error);
      toast.error(parsed.message);
      if (parsed.isForbidden) void refreshUser();
    },
  });
  return (
    <>
      <button className="btn btn-primary" type="button" onClick={() => setOpen(true)}>
        + Record trade
      </button>
      {open && (
        <TradeFormModal
          open
          groups={groups}
          defaultGroupId={
            groups.find((g) => String(g.id) === params.get("group"))?.id ?? groups[0]?.id ?? null
          }
          busy={mutation.isPending}
          onCancel={() => {
            if (!mutation.isPending) setOpen(false);
          }}
          onSubmit={(result) => mutation.mutate(result)}
        />
      )}
    </>
  );
}
