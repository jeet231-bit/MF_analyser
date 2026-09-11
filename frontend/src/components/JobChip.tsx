import type { RunOut } from "@/api/runs";
import { formatSeconds } from "@/lib/format";
import { Pill } from "./Pill";

/** Status of a background full run: running, done, or failed with its message. */
export function JobChip({ job, onDismiss }: { job: RunOut | null; onDismiss: () => void }) {
  if (!job) return null;
  const tone = job.status === "running" ? "accent" : job.status === "ok" ? "positive" : "negative";
  const label =
    job.status === "running"
      ? "Full run in progress…"
      : job.status === "ok"
        ? `Full run done in ${formatSeconds(job.summary.seconds)}`
        : `Full run failed: ${job.error ?? "unknown error"}`;
  return (
    <div className="flex items-center gap-2" role="status" aria-live="polite">
      <Pill tone={tone}>{label}</Pill>
      {job.status !== "running" && (
        <button type="button" onClick={onDismiss} className="text-xs text-muted hover:text-ink">
          Dismiss
        </button>
      )}
    </div>
  );
}
