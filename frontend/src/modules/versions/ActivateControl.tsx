import { useState } from "react";
import { activateVersion } from "@/api/validation";
import type { WorkbookVersion } from "@/api/workbooks";
import { Button } from "@/components";
import { describeError } from "@/lib/useAsync";

/** Activate (or roll back to) a version, asking for an override reason when validation failed. */
export function ActivateControl({
  version,
  activeId,
  activeUploadedAt = null,
  onBusy,
  onDone,
  size = "sm",
}: {
  version: WorkbookVersion;
  activeId: string | null;
  activeUploadedAt?: string | null;
  onBusy: (busy: boolean, label?: string) => void;
  onDone: () => void;
  size?: "sm" | "md";
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const isActive = version.id === activeId;
  const failed = version.validation_status === "failed";
  const unvalidated = !version.validation_status;
  const label = activeUploadedAt && version.uploaded_at < activeUploadedAt ? "Roll back to this" : "Activate";

  const run = async (override?: string) => {
    setError(null);
    onBusy(true, "Activating version");
    try {
      await activateVersion(version.id, override);
      setOpen(false);
      setReason("");
      onDone();
    } catch (err) {
      setError(describeError(err));
    } finally {
      onBusy(false);
    }
  };

  if (isActive) return <span className="text-xs text-muted">active</span>;
  return (
    <div className="space-y-1">
      <Button
        size={size}
        variant={failed ? "secondary" : "primary"}
        disabled={unvalidated}
        title={unvalidated ? "Validate this version first" : undefined}
        onClick={() => (failed ? setOpen(true) : void run())}
        aria-label={`${label} ${version.filename}`}
      >
        {failed ? `${label} anyway…` : label}
      </Button>
      {open && (
        <div className="space-y-1 rounded-md border border-hairline bg-surface p-2">
          <p className="text-xs text-muted">Validation failed. Give a reason; it is stored with the version.</p>
          <textarea
            aria-label="Override reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            className="w-full rounded-sm border border-hairline bg-surface px-2 py-1 text-sm text-ink focus:border-accent focus:outline-none"
          />
          <div className="flex gap-1">
            <Button size="sm" variant="primary" disabled={!reason.trim()} onClick={() => void run(reason)}>
              Activate with this reason
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="text-xs text-negative">
          {error}
        </p>
      )}
    </div>
  );
}
