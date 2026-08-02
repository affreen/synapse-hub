import { ActionChatData, PendingAction } from "@/lib/api";
import { Button } from "@/components/ui/button";

const STATUS_STYLES: Record<string, string> = {
  SUCCESS: "bg-emerald-50 text-emerald-700 border-emerald-200",
  REFUSED: "bg-red-50 text-red-700 border-red-200",
  ERROR: "bg-red-50 text-red-700 border-red-200",
  CANCELLED: "bg-slate-50 text-slate-600 border-slate-200",
  AWAITING_CONFIRMATION: "bg-amber-50 text-amber-700 border-amber-200",
  NOT_APPLICABLE: "bg-slate-50 text-slate-600 border-slate-200",
};

export function ActionResultCard({
  data,
  onConfirm,
  onCancel,
}: {
  data: ActionChatData;
  onConfirm?: (pending: PendingAction) => void;
  onCancel?: () => void;
}) {
  const style = STATUS_STYLES[data.action_status || ""] || "bg-slate-50 text-slate-600 border-slate-200";

  return (
    <div className={`mt-2 rounded-lg border px-3 py-2 text-xs ${style}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{data.tool_called ? data.tool_called.replaceAll("_", " ") : "action"}</span>
        <span className="rounded-full bg-white/60 px-2 py-0.5 text-[10px] uppercase tracking-wide">
          {data.action_status}
        </span>
      </div>

      {data.requires_confirmation && data.pending_action && (
        <div className="mt-2 flex gap-2">
          <Button size="sm" type="button" onClick={() => onConfirm?.(data.pending_action as PendingAction)}>
            Confirm
          </Button>
          <Button size="sm" variant="outline" type="button" onClick={() => onCancel?.()}>
            Cancel
          </Button>
        </div>
      )}
    </div>
  );
}
