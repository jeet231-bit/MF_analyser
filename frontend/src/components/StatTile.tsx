import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { formatNumber } from "@/lib/format";

export type DeltaDirection = "up" | "down" | "flat";

export interface Delta {
  value: number;
  direction: DeltaDirection;
  label?: string;
  decimals?: number;
}

const deltaTone: Record<DeltaDirection, string> = {
  up: "text-positive",
  down: "text-negative",
  flat: "text-muted",
};

const deltaGlyph: Record<DeltaDirection, string> = { up: "▲", down: "▼", flat: "•" };

/** Label above a large tabular figure, with an optional delta line. */
export function StatTile({
  label,
  value,
  delta,
  hint,
  className,
}: {
  label: string;
  value: ReactNode;
  delta?: Delta;
  hint?: string;
  className?: string;
}) {
  return (
    <div className={cn("rounded-md border border-hairline bg-surface px-3 py-2", className)}>
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="tabular mt-1 font-heading text-2xl font-semibold text-ink" data-testid="stat-value">
        {value}
      </div>
      {delta && (
        <div className={cn("tabular mt-0.5 text-xs", deltaTone[delta.direction])} data-testid="stat-delta">
          <span aria-hidden>{deltaGlyph[delta.direction]} </span>
          {formatNumber(Math.abs(delta.value), { decimals: delta.decimals ?? 2 })}
          {delta.label ? ` ${delta.label}` : ""}
        </div>
      )}
      {hint && !delta && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </div>
  );
}
