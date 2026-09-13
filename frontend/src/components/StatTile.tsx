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
  up: "bg-positive-soft text-positive",
  down: "bg-negative-soft text-negative",
  flat: "bg-surface-lifted text-muted",
};

const deltaGlyph: Record<DeltaDirection, string> = { up: "▲", down: "▼", flat: "•" };

/** A label with an optional icon bubble, a large tabular figure, and a delta pill. */
export function StatTile({
  label,
  value,
  delta,
  hint,
  icon,
  className,
}: {
  label: string;
  value: ReactNode;
  delta?: Delta;
  hint?: string;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("rounded-xl glass rise px-[20px] py-[18px]", className)}>
      <div className="flex items-center gap-[10px]">
        {icon && (
          <span className="grid h-[34px] w-[34px] flex-none place-items-center rounded-full bg-accent-soft text-accent" aria-hidden>
            {icon}
          </span>
        )}
        <div className="text-[13px] font-semibold text-ink-2">{label}</div>
      </div>
      <div className="mt-[10px] flex flex-wrap items-baseline gap-[10px]">
        <div className="tabular font-heading text-[26px] font-extrabold tracking-[-0.02em] text-ink" data-testid="stat-value">
          {value}
        </div>
        {delta && (
          <span className={cn("tabular rounded-full px-[9px] py-[3px] text-[11.5px] font-bold", deltaTone[delta.direction])} data-testid="stat-delta">
            <span aria-hidden>{deltaGlyph[delta.direction]} </span>
            {formatNumber(Math.abs(delta.value), { decimals: delta.decimals ?? 2 })}
            {delta.label ? ` ${delta.label}` : ""}
          </span>
        )}
      </div>
      {hint && !delta && <div className="mt-[4px] text-xs text-muted">{hint}</div>}
    </div>
  );
}
