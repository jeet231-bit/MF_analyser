import { Button, Pill } from "@/components";
import { formatSeconds } from "@/lib/format";
import type { RunSession } from "./useRunSession";

/**
 * Fixed bottom bar: "n changes · Run analysis / Reset" while a draft exists, and the what-if
 * caption once a run is active. Hidden when there is nothing to say.
 */
export function OverridesBar({ session }: { session: RunSession }) {
  const { draft, activeRun, running, error } = session;
  const overrideCount = activeRun ? Object.keys(activeRun.overrides).length : 0;
  if (draft.size === 0 && !activeRun && !error) return null;
  return (
    <div
      role="region"
      aria-label="Overrides"
      className="fixed inset-x-0 bottom-0 z-20 border-t border-hairline bg-surface/95 backdrop-blur md:left-60"
    >
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-2 px-4 py-2">
        {draft.size > 0 ? (
          <>
            <span className="tabular font-heading text-sm font-medium text-ink">
              {draft.size} change{draft.size === 1 ? "" : "s"}
            </span>
            <span className="text-xs text-muted">·</span>
            <Button variant="primary" size="sm" onClick={() => void session.runAnalysis()} disabled={running}>
              {running ? "Running…" : "Run analysis"}
            </Button>
            <Button variant="ghost" size="sm" onClick={session.resetDraft} disabled={running}>
              Reset
            </Button>
          </>
        ) : activeRun ? (
          <>
            <Pill tone="accent">what-if run</Pill>
            <span className="tabular text-sm text-ink">
              {overrideCount} override{overrideCount === 1 ? "" : "s"} · {formatSeconds(activeRun.summary.seconds)} ·{" "}
              {activeRun.summary.blocks_evaluated} blocks recomputed
            </span>
            <Button variant="ghost" size="sm" onClick={session.backToBaseline}>
              Back to baseline
            </Button>
          </>
        ) : null}
        {error && (
          <span role="alert" className="ml-auto text-xs text-negative">
            {error}
          </span>
        )}
      </div>
    </div>
  );
}
